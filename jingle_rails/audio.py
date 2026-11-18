"""Petite mélodie ORIGINALE de Noël, synthétisée localement (aucun fichier tiers)."""
import asyncio
import contextlib
import logging
import math
import os
import shutil
import struct
import tempfile
import wave

LOG = logging.getLogger(__name__)
# Air original « Le petit express », notes en Hz et durées en secondes.
MELODY = [
    (392, .28), (523, .28), (659, .40), (523, .28),
    (440, .28), (587, .28), (698, .40), (587, .28),
    (523, .30), (659, .30), (784, .50), (659, .24),
    (587, .28), (523, .28), (440, .42), (0, .20),
]

def make_wav(path: str, volume: float = .35, repeats: int = 2):
    rate = 22050
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        for pitch, duration in MELODY * repeats:
            count = int(rate * duration)
            for i in range(count):
                t = i / rate
                fade = min(1.0, i / (rate * .018), (count-i) / (rate * .04))
                sample = 0 if not pitch else math.sin(2*math.pi*pitch*t) * fade
                wav.writeframesraw(struct.pack("<h", int(11000*volume*sample)))

class Music:
    def __init__(self, enabled: bool, volume: float):
        self.enabled = enabled
        self.volume = volume
        self.process = None
        self.file = None
        self.task = None

    async def start(self):
        player = shutil.which("aplay")
        if not self.enabled:
            return
        if not player:
            LOG.warning("aplay absent : circulation sans musique (installer alsa-utils)")
            return
        fd, path = tempfile.mkstemp(prefix="jingle-rails-", suffix=".wav")
        os.close(fd)
        self.file = path
        make_wav(path, self.volume, repeats=2)
        async def play_loop():
            while True:
                self.process = await asyncio.create_subprocess_exec(
                    player, "-q", path, stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL)
                result = await self.process.wait()
                if result != 0:
                    LOG.warning("Lecture audio impossible (aplay code %s)", result)
                    return

        self.task = asyncio.create_task(play_loop())

    async def stop(self):
        if self.task:
            self.task.cancel()
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 2)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.task:
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        self.task = None
        self.process = None
        if self.file:
            try:
                os.unlink(self.file)
            except FileNotFoundError:
                pass
            self.file = None
