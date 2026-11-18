"""Application Jingle Rails : BLE, scénarios, horaires et arrêt de sécurité."""
import argparse
import asyncio
from datetime import datetime
import logging
from pathlib import Path
import tomllib

from .audio import Music
from .core import CHARACTERISTIC, Settings, idle_brightness, laps_at_hour, packet, scheduled_event, trip_duration

LOG = logging.getLogger("jingle_rails")
ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Path):
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    train, schedule, audio = (data.get(k, {}) for k in ("train", "schedule", "audio"))
    config = Settings(
        start_hour=int(schedule.get("start_hour", 7)),
        end_hour=int(schedule.get("end_hour", 22)),
        seconds_per_lap=float(train.get("seconds_per_lap", 15)),
        motor_power=int(train.get("motor_power", 55)),
        direction=int(train.get("direction", 1)),
        motor_port=int(train.get("motor_port", 0)),
        light_port=int(train.get("light_port", 1)),
        max_trip_seconds=float(train.get("max_trip_seconds", 240)),
        evening_start=int(schedule.get("evening_start", 17)),
        idle_evening_brightness=int(schedule.get("idle_evening_brightness", 30)),
        music_enabled=bool(audio.get("music_enabled", True)),
        music_volume=float(audio.get("music_volume", .35)),
    )
    config.validate()
    return data.get("train", {}).get("hub_address", ""), config


class Train:
    def __init__(self, client, config):
        self.client, self.config = client, config
        self.music = Music(config.music_enabled, config.music_volume)

    async def output(self, port, power):
        await self.client.write_gatt_char(CHARACTERISTIC, packet(port, power), response=False)

    async def lights(self, level):
        await self.output(self.config.light_port, int(level))

    async def motor(self, power):
        await self.output(self.config.motor_port, int(power) * self.config.direction)

    async def stop(self):
        await self.motor(0)

    async def safe_shutdown(self, *, stop_motor=True):
        """Best effort: never mask the real BLE failure with cleanup errors."""
        await self.music.stop()
        if not self.client.is_connected:
            LOG.warning("Hub déconnecté : arrêt moteur non transmissible ; vérifier physiquement le train")
            return
        actions = [("moteur", self.stop)] if stop_motor else []
        actions.append(("phares", lambda: self.lights(0)))
        for label, action in actions:
            try:
                await action()
            except Exception as exc:
                LOG.warning("Arrêt %s non confirmé (%s). Vérifier le hub.", label, exc)

    async def trip(self, laps):
        duration = trip_duration(laps, self.config)
        LOG.info("Départ : %d tour(s), %.1f s", laps, duration)
        await self.lights(100)
        try:
            # La musique n'empêche jamais le départ du train si l'audio est absent.
            await self.music.start()
            ramp = min(1.2, duration * .2)
            steps = (0.4, 0.65, 0.85, 1.0)
            for factor in steps:
                await self.motor(max(1, round(self.config.motor_power * factor)))
                await asyncio.sleep(ramp / len(steps))
            await asyncio.sleep(max(0, duration - 2*ramp))
            for factor in (0.85, 0.65, 0.4, 0.2):
                await self.motor(max(1, round(self.config.motor_power * factor)))
                await asyncio.sleep(ramp / 4)
        finally:
            # Ne pas laisser la musique active après une erreur BLE.
            try:
                await self.stop()
            finally:
                await self.music.stop()

    async def show(self, kind, hour):
        try:
            if kind == "hour":
                laps = laps_at_hour(hour)
                LOG.info("Carillon de %02dh : %d tours", hour, laps)
                await self.lights(30)
                await asyncio.sleep(1)
                await self.lights(100)
                await asyncio.sleep(1)
                await self.trip(laps)
            else:
                LOG.info("Demi-heure : petit express")
                for _ in range(3):
                    await self.lights(100)
                    await asyncio.sleep(.2)
                    await self.lights(0)
                    await asyncio.sleep(.2)
                await self.trip(1)
        finally:
            await self.lights(idle_brightness(datetime.now(), self.config))


async def scan():
    from bleak import BleakScanner
    print("Recherche des hubs Powered Up (12 secondes)…")
    devices = await BleakScanner.discover(timeout=12)
    for device in devices:
        if any(word in (device.name or "").lower() for word in ("lego", "hub", "powered")):
            print(f"{device.name or 'Hub'} : {device.address}")


async def serve(mode, address, config, seconds, hour):
    from bleak import BleakClient
    if not address:
        raise SystemExit("hub_address manquant dans config.local.toml ; exécuter 'scan'")
    last_slot = None
    while True:
        train = None
        try:
            async with BleakClient(
                address, timeout=20,
                disconnected_callback=lambda _client: LOG.warning("Signal BLE : hub déconnecté"),
            ) as client:
                train = Train(client, config)
                LOG.info("Hub connecté (%s)", mode)
                if mode not in ("lights-test", "ble-hold"):
                    await train.stop()
                if mode != "run":
                    try:
                        if mode == "ble-hold":
                            LOG.info("Test de stabilité BLE : connexion maintenue 20 s sans commande")
                            await asyncio.sleep(20)
                            LOG.info("État après 20 s : %s", "connecté" if client.is_connected else "déconnecté")
                        elif mode == "lights-test":
                            for brightness in (30, 100, 30, 0):
                                LOG.info("Phares : %d %%", brightness)
                                await train.lights(brightness)
                                await asyncio.sleep(2)
                        elif mode == "test":
                            await train.trip(1)
                        elif mode == "lap-test":
                            # Mesurer les secondes, sans modifier automatiquement la configuration.
                            await train.lights(100)
                            await train.motor(config.motor_power)
                            await asyncio.sleep(seconds)
                        elif mode == "hour-test":
                            await train.show("hour", hour)
                    finally:
                        if mode == "ble-hold":
                            await train.music.stop()
                        else:
                            await train.safe_shutdown(stop_motor=(mode != "lights-test"))
                    return
                LOG.info("Connecté, programme %02d:00–%02d:00", config.start_hour, config.end_hour)
                last_light = None
                while client.is_connected:
                    now = datetime.now().astimezone()
                    brightness = idle_brightness(now, config)
                    if brightness != last_light:
                        await train.lights(brightness)
                        last_light = brightness
                    event = scheduled_event(now, config)
                    slot = (now.date(), now.hour, now.minute)
                    if event and slot != last_slot:
                        # Marquer avant exécution : ne jamais répéter un trajet après erreur.
                        last_slot = slot
                        await train.show(event, now.hour)
                        last_light = None
                    await asyncio.sleep(.5)
                raise ConnectionError("Hub déconnecté")
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception("Connexion ou événement interrompu")
            if mode != "run":
                raise
        finally:
            if train is not None:
                if mode == "ble-hold":
                    await train.music.stop()
                else:
                    await train.safe_shutdown(stop_motor=(mode != "lights-test"))
        if mode != "run":
            return
        await asyncio.sleep(8)


def main():
    parser = argparse.ArgumentParser(description="Jingle Rails — horloge ferroviaire de Noël")
    parser.add_argument("mode", choices=("scan", "run", "test", "lap-test", "hour-test", "lights-test", "ble-hold", "music-test"))
    parser.add_argument("--config", type=Path, default=ROOT / "config.local.toml")
    parser.add_argument("--seconds", type=float, default=5)
    parser.add_argument("--hour", type=int, default=3)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.mode == "scan":
        asyncio.run(scan())
        return
    address, config = load_config(args.config)
    if args.mode == "music-test":
        async def test_music():
            music = Music(config.music_enabled, config.music_volume)
            try:
                await music.start()
                await asyncio.sleep(5)
            finally:
                await music.stop()
        asyncio.run(test_music())
        return
    if args.mode == "lap-test" and not 0 < args.seconds <= config.max_trip_seconds:
        parser.error("--seconds doit être strictement positif et rester sous max_trip_seconds")
    if args.mode == "hour-test" and not 0 <= args.hour <= 23:
        parser.error("--hour doit être entre 0 et 23")
    try:
        asyncio.run(serve(args.mode, address, config, args.seconds, args.hour))
    except KeyboardInterrupt:
        LOG.info("Interruption demandée; vérifier que le train est arrêté")


if __name__ == "__main__":
    main()
