"""Planification et messages LEGO LWP3, sans dépendance matérielle."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

CHARACTERISTIC = "00001624-1212-efde-1623-785feabcd123"

@dataclass(frozen=True)
class Settings:
    start_hour: int = 7
    end_hour: int = 22
    seconds_per_lap: float = 15.0
    motor_power: int = 55
    direction: int = 1
    motor_port: int = 0
    light_port: int = 1
    max_trip_seconds: float = 240.0
    evening_start: int = 17
    idle_evening_brightness: int = 30
    keepalive_seconds: int = 60
    music_enabled: bool = True
    music_volume: float = 0.35

    def validate(self):
        if not 0 <= self.start_hour <= self.end_hour <= 23:
            raise ValueError("Horaires invalides")
        if self.keepalive_seconds < 10 or self.keepalive_seconds > 300:
            raise ValueError("Intervalle de maintien BLE hors limites (10–300 s)")
        if self.seconds_per_lap <= 0 or self.max_trip_seconds <= 0:
            raise ValueError("Durées invalides")
        if self.motor_power not in range(1, 101) or self.direction not in (-1, 1):
            raise ValueError("Puissance/direction invalides")
        if {self.motor_port, self.light_port} != {0, 1}:
            raise ValueError("Ports A/B distincts requis")
        if not 0 <= self.idle_evening_brightness <= 100 or not 0 <= self.music_volume <= 1:
            raise ValueError("Luminosité/volume invalides")

def packet(port: int, power: int) -> bytes:
    if port not in (0, 1) or not -100 <= power <= 100:
        raise ValueError("Port ou puissance invalide")
    return bytes([8, 0, 0x81, port, 0x11, 0x51, 0, power & 0xff])

def laps_at_hour(hour: int) -> int:
    return hour % 12 or 12

def scheduled_event(now: datetime, config: Settings) -> Optional[str]:
    """Départs à HH:00 ou HH:30, seulement pendant les 15 premières secondes."""
    if not config.start_hour <= now.hour <= config.end_hour or now.second >= 15:
        return None
    if now.minute == 0:
        return "hour"
    if now.minute == 30 and now.hour < config.end_hour:
        return "half"
    return None

def idle_brightness(now: datetime, config: Settings) -> int:
    return config.idle_evening_brightness if config.evening_start <= now.hour < config.end_hour else 0

def trip_duration(laps: int, config: Settings) -> float:
    duration = laps * config.seconds_per_lap
    if not 0 < duration <= config.max_trip_seconds:
        raise ValueError("Trajet trop long; réduire la durée d'un tour ou relever le plafond après vérification")
    return duration


def battery_request() -> bytes:
    """LWP3 Hub Property Request Update: battery level (0x06), op 0x05."""
    return bytes([5, 0, 0x01, 0x06, 0x05])
