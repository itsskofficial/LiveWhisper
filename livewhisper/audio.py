"""Capture system audio (WASAPI loopback) and the microphone, mixed to one track.

The loopback trick is the important part: WASAPI exposes every output device a
second time as an input device, so we can tap the mix of everything already
playing without a virtual cable and without rerouting the user's speakers.
"""

from __future__ import annotations

import logging
import wave
from dataclasses import dataclass

import numpy as np
import pyaudiowpatch as pyaudio
import soxr

log = logging.getLogger(__name__)

TARGET_RATE = 16000  # what Whisper wants; resampling here saves it the work
_CHUNK = 1024


class AudioError(RuntimeError):
    pass


@dataclass
class Recording:
    audio: np.ndarray  # mono float32 @ 16 kHz
    seconds: float
    system_peak: float  # 0.0 means the loopback delivered nothing but silence
    mic_peak: float


class _Track:
    """One capture stream accumulating into memory, normalised on read."""

    def __init__(self, pa: pyaudio.PyAudio, device: dict, label: str):
        self.label = label
        self.rate = int(device["defaultSampleRate"])
        self.channels = int(device["maxInputChannels"])
        self._chunks: list[bytes] = []
        self.level = 0.0  # most recent peak, read live by the recording overlay
        self._stream = pa.open(
            format=pyaudio.paFloat32,
            channels=self.channels,
            rate=self.rate,
            input=True,
            input_device_index=int(device["index"]),
            frames_per_buffer=_CHUNK,
            stream_callback=self._on_data,
        )
        log.info("capturing %s: %s (%d ch @ %d Hz)",
                 label, device["name"], self.channels, self.rate)

    def _on_data(self, in_data, frame_count, time_info, status):
        self._chunks.append(in_data)
        # Cheap peak for the meter. This runs on the audio callback thread, so
        # it must stay O(chunk) and allocation-light.
        block = np.frombuffer(in_data, dtype=np.float32)
        if block.size:
            self.level = float(np.abs(block).max())
        return (None, pyaudio.paContinue)

    def close(self) -> None:
        try:
            self._stream.stop_stream()
            self._stream.close()
        except Exception:
            log.warning("failed to close %s stream cleanly", self.label, exc_info=True)

    def mono_16k(self) -> np.ndarray:
        if not self._chunks:
            return np.zeros(0, dtype=np.float32)
        x = np.frombuffer(b"".join(self._chunks), dtype=np.float32)
        if self.channels > 1:
            # Trailing partial frame would break the reshape.
            x = x[: len(x) - (len(x) % self.channels)]
            x = x.reshape(-1, self.channels).mean(axis=1)
        if self.rate != TARGET_RATE:
            x = soxr.resample(x, self.rate, TARGET_RATE)
        return np.ascontiguousarray(x, dtype=np.float32)


def _default_loopback(pa: pyaudio.PyAudio) -> dict:
    """The loopback twin of whatever the user's current default speaker is."""
    try:
        wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
    except OSError as e:
        raise AudioError("WASAPI host API unavailable on this system") from e

    speakers = pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
    if speakers.get("isLoopbackDevice"):
        return speakers
    for candidate in pa.get_loopback_device_info_generator():
        if speakers["name"] in candidate["name"]:
            return candidate
    raise AudioError(f"no loopback device found for output {speakers['name']!r}")


class Recorder:
    """Start/stop capture. Not reentrant - one recording at a time."""

    def __init__(self, capture_system: bool, capture_mic: bool,
                 system_gain: float = 1.0, mic_gain: float = 1.0):
        if not (capture_system or capture_mic):
            raise AudioError("both capture_system and capture_mic are disabled")
        self.capture_system = capture_system
        self.capture_mic = capture_mic
        self.system_gain = system_gain
        self.mic_gain = mic_gain
        self._pa: pyaudio.PyAudio | None = None
        self._system: _Track | None = None
        self._mic: _Track | None = None

    def level(self) -> float:
        """Loudest of the live tracks, 0..1, for the recording overlay meter."""
        return max(
            (t.level for t in (self._system, self._mic) if t is not None),
            default=0.0,
        )

    def start(self) -> None:
        self._pa = pyaudio.PyAudio()
        try:
            if self.capture_system:
                self._system = _Track(self._pa, _default_loopback(self._pa), "system")
            if self.capture_mic:
                try:
                    mic = self._pa.get_default_input_device_info()
                    self._mic = _Track(self._pa, mic, "mic")
                except (OSError, AudioError):
                    # A missing mic should not kill a meeting capture.
                    log.warning("no usable microphone; continuing with system audio only")
        except Exception:
            self._teardown()
            raise

    def stop(self) -> Recording:
        system = self._system.mono_16k() if self._system else np.zeros(0, np.float32)
        mic = self._mic.mono_16k() if self._mic else np.zeros(0, np.float32)
        self._teardown()

        # The two devices run off independent clocks, so their lengths drift
        # slightly over a long meeting. Pad to the longer one and mix: a small
        # relative offset between the two speakers is irrelevant once both are
        # summed into a single mono track for transcription.
        n = max(len(system), len(mic))
        mixed = np.zeros(n, dtype=np.float32)
        if len(system):
            mixed[: len(system)] += system * self.system_gain
        if len(mic):
            mixed[: len(mic)] += mic * self.mic_gain

        peak = float(np.abs(mixed).max()) if n else 0.0
        if peak > 1.0:
            mixed /= peak

        return Recording(
            audio=mixed,
            seconds=n / TARGET_RATE,
            system_peak=float(np.abs(system).max()) if len(system) else 0.0,
            mic_peak=float(np.abs(mic).max()) if len(mic) else 0.0,
        )

    def _teardown(self) -> None:
        for track in (self._system, self._mic):
            if track:
                track.close()
        self._system = self._mic = None
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                log.warning("PyAudio terminate failed", exc_info=True)
            self._pa = None


def write_wav(path, audio: np.ndarray, rate: int = TARGET_RATE) -> None:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
