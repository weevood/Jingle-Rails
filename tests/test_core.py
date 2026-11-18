from datetime import datetime
import pytest
from jingle_rails.core import Settings, packet, laps_at_hour, scheduled_event, idle_brightness, trip_duration

def test_schedule():
    c = Settings()
    assert scheduled_event(datetime(2026, 12, 1, 7, 0, 0), c) == "hour"
    assert scheduled_event(datetime(2026, 12, 1, 7, 30, 5), c) == "half"
    assert scheduled_event(datetime(2026, 12, 1, 21, 30, 1), c) == "half"
    assert scheduled_event(datetime(2026, 12, 1, 22, 0, 1), c) == "hour"
    assert scheduled_event(datetime(2026, 12, 1, 22, 30, 1), c) is None
    assert scheduled_event(datetime(2026, 12, 1, 6, 59, 59), c) is None
    assert scheduled_event(datetime(2026, 12, 1, 10, 0, 16), c) is None

def test_twelve_hour_clock():
    assert [laps_at_hour(h) for h in (7, 12, 13, 22)] == [7, 12, 1, 10]

def test_ble_packet():
    assert packet(0, 55) == bytes.fromhex("0800810011510037")
    assert packet(1, 0) == bytes.fromhex("0800810111510000")
    assert packet(0, -55)[-1] == 201
    with pytest.raises(ValueError):
        packet(2, 55)

def test_brightness():
    c = Settings()
    assert idle_brightness(datetime(2026, 12, 1, 17), c) == 30
    assert idle_brightness(datetime(2026, 12, 1, 22), c) == 0

def test_safety():
    c = Settings()
    assert trip_duration(12, c) == 180
    with pytest.raises(ValueError):
        trip_duration(21, c)
    with pytest.raises(ValueError):
        Settings(motor_port=0, light_port=0).validate()

def test_battery_request_and_keepalive_validation():
    from jingle_rails.core import battery_request
    assert battery_request() == bytes.fromhex("0500010605")
    Settings(keepalive_seconds=60).validate()
    with pytest.raises(ValueError):
        Settings(keepalive_seconds=5).validate()
    with pytest.raises(ValueError):
        Settings(keepalive_seconds=301).validate()
