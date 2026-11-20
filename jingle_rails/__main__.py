"""Application Jingle Rails : BLE, scénarios, horaires et arrêt de sécurité."""
import argparse
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
import logging
import time
from pathlib import Path
import tomllib

from .audio import Music
from .core import CHARACTERISTIC, Settings, battery_request, idle_brightness, laps_at_hour, packet, scheduled_event, trip_duration

LOG = logging.getLogger("jingle_rails")
ROOT = Path(__file__).resolve().parent.parent

def hub_notification(_sender, data):
    """Log LEGO LWP3 messages; feedback requires GATT notifications."""
    payload = bytes(data)
    if len(payload) < 3 or payload[0] != len(payload):
        LOG.warning("Notification LEGO inattendue : %s", payload.hex(" "))
        return
    kind = payload[2]
    if kind == 0x01 and len(payload) >= 6 and payload[3:5] == bytes((0x06, 0x06)):
        LOG.info("Batterie LEGO : %d %%", payload[5])
    elif kind == 0x82:
        feedback = [(payload[i], payload[i + 1]) for i in range(3, len(payload) - 1, 2)]
        LOG.info(
            "Retour commande LEGO (port, flags d’état hexadécimaux) : %s",
            [(port, f"0x{flags:02x}") for port, flags in feedback],
        )
    elif kind in (0x02, 0x03, 0x05):
        LOG.warning("Événement hub type=0x%02x : %s", kind, payload.hex(" "))
    else:
        LOG.debug("Hub event type=0x%02x : %s", kind, payload.hex(" "))


def load_config(path: Path):
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    train, schedule, audio = (data.get(k, {}) for k in ("train", "schedule", "audio"))
    config = Settings(
        start_hour=int(schedule.get("start_hour", 7)),
        end_hour=int(schedule.get("end_hour", 22)),
        seconds_per_lap=float(train.get("seconds_per_lap", 15)),
        motor_power=int(train.get("motor_power", 40)),
        ramp_seconds=float(train.get("ramp_seconds", 3.0)),
        direction=int(train.get("direction", 1)),
        motor_port=int(train.get("motor_port", 0)),
        light_port=int(train.get("light_port", 1)),
        max_trip_seconds=float(train.get("max_trip_seconds", 240)),
        evening_start=int(schedule.get("evening_start", 17)),
        idle_evening_brightness=int(schedule.get("idle_evening_brightness", 30)),
        keepalive_seconds=int(train.get("keepalive_seconds", 60)),
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
        # Wait for a GATT acknowledgement, distinct from LEGO command feedback.
        await self.client.write_gatt_char(CHARACTERISTIC, packet(port, power), response=True)

    async def poll_battery(self):
        """LWP3 standard query, not a motor command; may help avoid idle sleep."""
        await self.client.write_gatt_char(CHARACTERISTIC, battery_request(), response=True)

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
            # Schedule each motor change against a monotonic clock so the
            # duration includes BLE write latency rather than drifting.
            started = time.monotonic()
            ramp = min(self.config.ramp_seconds, duration / 2)
            # Begin with a modest but moving power; reach cruising speed smoothly.
            rise = (0.50, 0.60, 0.70, 0.80, 0.90, 1.00)
            fall = (0.90, 0.80, 0.70, 0.60, 0.50)
            for i, factor in enumerate(rise):
                await asyncio.sleep(max(0, started + ramp * i / len(rise) - time.monotonic()))
                power = max(1, round(self.config.motor_power * factor))
                LOG.info("Accélération : %d %% puissance", power)
                await self.motor(power)
            for i, factor in enumerate(fall):
                await asyncio.sleep(max(0, started + duration - ramp + ramp * i / len(fall) - time.monotonic()))
                power = max(1, round(self.config.motor_power * factor))
                LOG.info("Freinage : %d %% puissance", power)
                await self.motor(power)
            await asyncio.sleep(max(0, started + duration - time.monotonic()))
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


@asynccontextmanager
async def hub_connection(address):
    """Release BlueZ even if its D-Bus socket closes during disconnect."""
    from bleak import BleakClient
    client = BleakClient(
        address, timeout=20,
        disconnected_callback=lambda _client: LOG.warning("Signal BLE : hub déconnecté"),
    )
    await client.connect()
    try:
        # 0x11 output flags request feedback through asynchronous notifications.
        await client.start_notify(CHARACTERISTIC, hub_notification)
        LOG.info("Notifications LEGO activées")
        yield client
    finally:
        try:
            await client.disconnect()
        except (EOFError, OSError) as exc:
            LOG.warning("Fermeture BlueZ interrompue (%s) : pas une erreur de commande LEGO", exc)


async def serve(mode, address, config, seconds, hour, minutes=15):
    if not address:
        raise SystemExit("hub_address manquant dans config.local.toml ; exécuter 'scan'")
    last_slot = None
    while True:
        train = None
        cleaned = False
        try:
            async with hub_connection(address) as client:
                train = Train(client, config)
                LOG.info("Hub connecté (%s)", mode)
                if mode not in ("lights-test", "ble-hold", "idle-test"):
                    await train.stop()
                if mode != "run":
                    try:
                        if mode == "idle-test":
                            LOG.info("Test au repos : %.1f minutes, interrogation batterie chaque %d s", minutes, config.keepalive_seconds)
                            end_at = time.monotonic() + minutes * 60
                            while time.monotonic() < end_at:
                                await train.poll_battery()
                                LOG.info("Connexion au repos : %s", client.is_connected)
                                await asyncio.sleep(min(config.keepalive_seconds, max(0, end_at - time.monotonic())))
                        elif mode == "ble-hold":
                            LOG.info("Test de stabilité BLE : connexion maintenue 20 s sans commande")
                            await asyncio.sleep(20)
                            LOG.info("État après 20 s : %s", "connecté" if client.is_connected else "déconnecté")
                        elif mode == "lights-test":
                            for brightness in (10, 30, 10, 0):
                                LOG.info("Phares : %d %%", brightness)
                                await train.lights(brightness)
                                LOG.info("Écriture acceptée ; connecté=%s", client.is_connected)
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
                        if mode in ("ble-hold", "idle-test"):
                            await train.music.stop()
                        else:
                            await train.safe_shutdown(stop_motor=(mode != "lights-test"))
                        cleaned = True
                    return
                LOG.info("Connecté, programme %02d:00–%02d:00", config.start_hour, config.end_hour)
                last_light = None
                next_keepalive = time.monotonic()
                while client.is_connected:
                    now = datetime.now().astimezone()
                    if time.monotonic() >= next_keepalive:
                        await train.poll_battery()
                        next_keepalive = time.monotonic() + config.keepalive_seconds
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
            if train is not None and not cleaned:
                if mode in ("ble-hold", "idle-test"):
                    await train.music.stop()
                else:
                    await train.safe_shutdown(stop_motor=(mode != "lights-test"))
        if mode != "run":
            return
        await asyncio.sleep(8)


def main():
    parser = argparse.ArgumentParser(description="Jingle Rails — horloge ferroviaire de Noël")
    parser.add_argument("mode", choices=("scan", "run", "test", "lap-test", "hour-test", "lights-test", "ble-hold", "idle-test", "music-test"))
    parser.add_argument("--config", type=Path, default=ROOT / "config.local.toml")
    parser.add_argument("--seconds", type=float, default=5)
    parser.add_argument("--hour", type=int, default=3)
    parser.add_argument("--minutes", type=float, default=15, help="Durée idle-test, 1–120 minutes")
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
    if args.mode == "idle-test" and not 1 <= args.minutes <= 120:
        parser.error("--minutes doit être entre 1 et 120")
    if args.mode == "hour-test" and not 0 <= args.hour <= 23:
        parser.error("--hour doit être entre 0 et 23")
    try:
        asyncio.run(serve(args.mode, address, config, args.seconds, args.hour, args.minutes))
    except KeyboardInterrupt:
        LOG.info("Interruption demandée; vérifier que le train est arrêté")


if __name__ == "__main__":
    main()
