"""Tests des arrêts après une perte BLE (sans véritable hub LEGO)."""
import asyncio

from jingle_rails.__main__ import Train
from jingle_rails.core import Settings


class FakeClient:
    def __init__(self, connected, fail=False):
        self.is_connected = connected
        self.fail = fail
        self.writes = []

    async def write_gatt_char(self, characteristic, data, response=False):
        if self.fail:
            raise OSError("Not connected")
        self.writes.append(bytes(data))


def test_shutdown_after_disconnect_does_not_raise():
    client = FakeClient(False)
    train = Train(client, Settings(music_enabled=False))
    asyncio.run(train.safe_shutdown())
    assert client.writes == []


def test_shutdown_after_write_error_does_not_raise():
    client = FakeClient(True, fail=True)
    train = Train(client, Settings(music_enabled=False))
    asyncio.run(train.safe_shutdown())


def test_shutdown_turns_off_motor_and_lights():
    client = FakeClient(True)
    train = Train(client, Settings(music_enabled=False))
    asyncio.run(train.safe_shutdown())
    assert len(client.writes) == 2
    assert client.writes[0][3] == 0 and client.writes[0][-1] == 0
    assert client.writes[1][3] == 1 and client.writes[1][-1] == 0


def test_lights_only_cleanup_never_writes_motor():
    client = FakeClient(True)
    train = Train(client, Settings(music_enabled=False))
    asyncio.run(train.safe_shutdown(stop_motor=False))
    assert len(client.writes) == 1
    assert client.writes[0][3] == 1 and client.writes[0][-1] == 0


def test_ble_cleanup_suppresses_eof(monkeypatch):
    import bleak
    from jingle_rails.__main__ import hub_connection

    class FakeBleakClient:
        def __init__(self, *_args, **_kwargs):
            self.is_connected = False
        async def connect(self):
            self.is_connected = True
        async def start_notify(self, characteristic, callback):
            self.notifications = (characteristic, callback)
        async def disconnect(self):
            self.is_connected = False
            raise EOFError("BlueZ bus closed")

    monkeypatch.setattr(bleak, "BleakClient", FakeBleakClient)

    async def exercise():
        async with hub_connection("mock") as client:
            assert client.is_connected

    asyncio.run(exercise())


def test_lego_output_requests_gatt_acknowledgment():
    client = FakeClient(True)
    # FakeClient logs writes; actual GATT response flag must be True.
    async def write_gatt_char(characteristic, data, response=False):
        assert response is True
        client.writes.append(bytes(data))
    client.write_gatt_char = write_gatt_char
    train = Train(client, Settings(music_enabled=False))
    asyncio.run(train.lights(30))
    assert client.writes[0] == bytes.fromhex("080081011151001e")


def test_lego_feedback_parsing(caplog):
    from jingle_rails.__main__ import hub_notification
    with caplog.at_level("INFO", logger="jingle_rails"):
        hub_notification(None, bytes.fromhex("0500820102"))
    assert "Retour commande LEGO" in caplog.text
    assert "0x02" in caplog.text


def test_subscription_before_first_command(monkeypatch):
    import bleak
    from jingle_rails.__main__ import hub_connection
    from jingle_rails.core import CHARACTERISTIC

    events = []

    class MockHub:
        is_connected = False
        def __init__(self, *_args, **_kwargs):
            pass
        async def connect(self):
            self.is_connected = True
            events.append("connect")
        async def start_notify(self, characteristic, callback):
            assert characteristic == CHARACTERISTIC
            events.append("notify")
        async def write_gatt_char(self, characteristic, data, response=False):
            assert events == ["connect", "notify"]
            assert response is True
            events.append("write")
        async def disconnect(self):
            self.is_connected = False
            events.append("disconnect")

    monkeypatch.setattr(bleak, "BleakClient", MockHub)

    async def exercise():
        async with hub_connection("mock") as client:
            await Train(client, Settings(music_enabled=False)).lights(10)

    asyncio.run(exercise())
    assert events == ["connect", "notify", "write", "disconnect"]
