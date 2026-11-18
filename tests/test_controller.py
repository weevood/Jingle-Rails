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
