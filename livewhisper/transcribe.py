"""Transcription backends: Groq, local faster-whisper, and auto-fallback.

`auto` sends to Groq first and falls back to the local model when Groq is out of
credit, rate-limited, misconfigured, or unreachable. After a refusal Groq is put
on a cooldown so every subsequent recording is not made to wait for the same
failure.
"""

from __future__ import annotations

import io
import logging
import os
import threading
import time

import numpy as np
import requests
import soundfile as sf

from .audio import TARGET_RATE

log = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


class TranscriptionError(RuntimeError):
    """Transcription failed in a way the user needs to know about."""


class GroqUnavailable(TranscriptionError):
    """Groq cannot serve this request; falling back to local is appropriate."""

    def __init__(self, message: str, cooldown: bool = True):
        super().__init__(message)
        # Out-of-credit and bad-key are persistent; a network blip is not.
        self.cooldown = cooldown


def _repo_id(model: str) -> str:
    """faster-whisper resolves bare names to the Systran conversions."""
    return model if "/" in model else f"Systran/faster-whisper-{model}"


class LocalBackend:
    name = "local"

    def __init__(self, cfg: dict, vocabulary: str = ""):
        self.last_language: str | None = None   # what Whisper heard, e.g. "ta"
        self.cfg = cfg
        self.vocabulary = vocabulary.strip()
        self._model = None
        self._batched = None
        self._lock = threading.Lock()

    # -- model availability -------------------------------------------------

    def is_downloaded(self) -> bool:
        """True if the weights are already in the HuggingFace cache."""
        try:
            from huggingface_hub import try_to_load_from_cache
        except ImportError:
            return False
        repo = _repo_id(self.cfg.get("model", "large-v3"))
        try:
            return try_to_load_from_cache(repo, "model.bin") is not None
        except Exception:
            return False

    def download(self, progress=None) -> None:
        """Fetch the weights without loading them onto the GPU."""
        from huggingface_hub import snapshot_download

        repo = _repo_id(self.cfg.get("model", "large-v3"))
        log.info("downloading %s", repo)
        if progress:
            progress(f"Downloading {repo} (~3 GB, one time only)...")
        snapshot_download(repo)
        if progress:
            progress("Local model ready.")

    # -- inference ----------------------------------------------------------

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            from faster_whisper import BatchedInferencePipeline, WhisperModel

            model = self.cfg.get("model", "large-v3")
            device = self.cfg.get("device", "cuda")
            compute_type = self.cfg.get("compute_type", "int8_float16")
            log.info("loading %s on %s (%s)", model, device, compute_type)
            try:
                self._model = WhisperModel(model, device=device, compute_type=compute_type)
            except Exception as e:
                if device == "cuda":
                    log.warning("CUDA load failed (%s); falling back to CPU", e)
                    self._model = WhisperModel(model, device="cpu", compute_type="int8")
                else:
                    raise TranscriptionError(f"could not load model {model!r}: {e}") from e

            # Batched decoding is a large win on meeting-length audio: VAD splits
            # the recording into speech chunks that decode in parallel.
            if self._batch_size() > 1:
                try:
                    self._batched = BatchedInferencePipeline(model=self._model)
                except Exception:
                    log.warning("batched pipeline unavailable; sequential decode",
                                exc_info=True)

    def _batch_size(self) -> int:
        return int(self.cfg.get("batch_size", 8))

    def transcribe(self, audio: np.ndarray) -> str:
        self.load()
        common = dict(
            language=self.cfg.get("language") or None,
            beam_size=int(self.cfg.get("beam_size", 5)),
            initial_prompt=self.vocabulary or None,
        )
        if self._batched is not None:
            # Batched mode always applies VAD and never conditions across
            # segments - which is what we want for code-switching anyway.
            segments, info = self._batched.transcribe(
                audio, batch_size=self._batch_size(), **common
            )
        else:
            segments, info = self._model.transcribe(
                audio,
                vad_filter=bool(self.cfg.get("vad_filter", True)),
                condition_on_previous_text=bool(
                    self.cfg.get("condition_on_previous_text", False)
                ),
                **common,
            )
        text = " ".join(s.text.strip() for s in segments).strip()
        self.last_language = info.language
        self.language_probability = float(info.language_probability or 0)
        log.info("detected language %s (p=%.2f)", info.language,
                 info.language_probability)
        return text


class GroqBackend:
    name = "groq"

    def __init__(self, cfg: dict, vocabulary: str = ""):
        self.last_language: str | None = None
        self.language_probability = 0.0
        self.cfg = cfg
        self.vocabulary = vocabulary.strip()

    def api_key(self) -> str | None:
        return os.environ.get(self.cfg.get("api_key_env", "GROQ_API_KEY"))

    def is_configured(self) -> bool:
        return bool(self.api_key())

    def load(self) -> None:
        if not self.is_configured():
            raise GroqUnavailable(
                f"{self.cfg.get('api_key_env', 'GROQ_API_KEY')} is not set"
            )

    def transcribe(self, audio: np.ndarray) -> str:
        key = self.api_key()
        if not key:
            raise GroqUnavailable(
                f"{self.cfg.get('api_key_env', 'GROQ_API_KEY')} is not set"
            )
        chunk = int(self.cfg.get("chunk_seconds", 600)) * TARGET_RATE
        parts = [self._post(c, key) for c in _split_on_silence(audio, chunk)]
        return " ".join(p for p in parts if p).strip()

    def _post(self, audio: np.ndarray, key: str) -> str:
        # FLAC keeps us well under the upload cap without losing anything.
        buf = io.BytesIO()
        sf.write(buf, audio, TARGET_RATE, format="FLAC", subtype="PCM_16")
        buf.seek(0)

        data = {"model": self.cfg.get("model", "whisper-large-v3"),
                "response_format": "verbose_json"}
        if self.cfg.get("language"):
            data["language"] = self.cfg["language"]
        if self.vocabulary:
            data["prompt"] = self.vocabulary

        try:
            r = requests.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {key}"},
                files={"file": ("audio.flac", buf, "audio/flac")},
                data=data,
                timeout=300,
            )
        except requests.RequestException as e:
            # Offline or DNS failure - transient, so do not blacklist Groq.
            raise GroqUnavailable(f"network error: {e}", cooldown=False) from e

        if r.status_code == 200:
            payload = r.json()
            if payload.get("language"):
                self.last_language = _iso_code(payload["language"])
            return payload.get("text", "").strip()

        detail = r.text[:300]
        if r.status_code in (401, 403):
            raise GroqUnavailable(f"API key rejected ({r.status_code})")
        if r.status_code in (402, 429):
            raise GroqUnavailable("out of credit or rate-limited")
        if r.status_code == 413:
            raise TranscriptionError(f"audio chunk too large for Groq: {detail}")
        if r.status_code >= 500:
            raise GroqUnavailable(f"Groq server error {r.status_code}", cooldown=False)
        raise TranscriptionError(f"Groq returned {r.status_code}: {detail}")


class AutoBackend:
    """Groq first, local when Groq will not serve us."""

    name = "auto"

    @property
    def last_language(self) -> str | None:
        """Whichever backend actually ran most recently."""
        return self._last_language

    def __init__(self, groq: GroqBackend, local: LocalBackend, cooldown_minutes: int = 60):
        self._last_language = None
        self.groq = groq
        self.local = local
        self.cooldown = cooldown_minutes * 60
        self._blocked_until = 0.0
        self.notify = lambda msg: None  # set by the app to surface fallback events

    @property
    def groq_available(self) -> bool:
        return self.groq.is_configured() and time.monotonic() >= self._blocked_until

    def load(self) -> None:
        # Warm-up must not drag in a 3 GB download; only prepare what is ready.
        if self.groq.is_configured():
            return
        if self.local.is_downloaded():
            self.local.load()

    def _block_groq(self) -> None:
        self._blocked_until = time.monotonic() + self.cooldown
        log.info("groq benched for %d minutes", self.cooldown // 60)

    def transcribe(self, audio: np.ndarray) -> str:
        if self.groq_available:
            try:
                out = self.groq.transcribe(audio)
                self._last_language = self.groq.last_language
                return out
            except GroqUnavailable as e:
                if e.cooldown:
                    self._block_groq()
                log.warning("groq unavailable (%s); falling back to local", e)
                self.notify(f"Groq unavailable ({e}). Using local model.")
        elif not self.groq.is_configured():
            log.debug("no groq key; using local")
        else:
            log.debug("groq on cooldown; using local")

        if not self.local.is_downloaded():
            self.notify("Downloading local model (~3 GB). This happens once.")
            self.local.download()
            self.notify("Local model ready.")
        out = self.local.transcribe(audio)
        self._last_language = self.local.last_language
        return out


def build_backend(name: str, cfg: dict):
    """Construct the backend named in `transcription.backend`."""
    vocabulary = cfg.get("vocabulary", "")
    groq = GroqBackend(cfg.get("groq", {}), vocabulary=vocabulary)
    local = LocalBackend(cfg.get("local", {}), vocabulary=vocabulary)

    if name == "groq":
        return groq
    if name == "local":
        return local
    if name == "auto":
        return AutoBackend(
            groq, local, int(cfg.get("fallback_cooldown_minutes", 60))
        )
    raise TranscriptionError(f"unknown backend {name!r}; expected auto, groq or local")


_LANG_NAMES = {
    "hindi": "hi", "bengali": "bn", "urdu": "ur", "punjabi": "pa",
    "marathi": "mr", "telugu": "te", "tamil": "ta", "gujarati": "gu",
    "kannada": "kn", "malayalam": "ml", "sinhala": "si", "sindhi": "sd",
    "english": "en", "nepali": "ne",
}


def _iso_code(value: str) -> str:
    """Groq reports language names; faster-whisper reports ISO codes."""
    v = (value or "").strip().lower()
    if len(v) == 2:
        return v
    return _LANG_NAMES.get(v, v[:2])


def _split_on_silence(audio: np.ndarray, target: int) -> list[np.ndarray]:
    """Cut `audio` into <= `target`-sample pieces, biased toward quiet moments.

    A blind fixed-length cut lands mid-word and costs you that word. Searching a
    window around the target for the quietest 100 ms is cheap and avoids it.
    """
    if len(audio) <= target:
        return [audio]

    window = int(0.1 * TARGET_RATE)
    search = int(15 * TARGET_RATE)
    pieces, start = [], 0

    while len(audio) - start > target:
        ideal = start + target
        lo = max(start + window, ideal - search)
        hi = min(len(audio) - window, ideal + search)
        if hi <= lo:
            cut = ideal
        else:
            region = np.abs(audio[lo:hi])
            csum = np.concatenate(([0.0], np.cumsum(region, dtype=np.float64)))
            energies = csum[window:] - csum[:-window]
            cut = lo + int(np.argmin(energies)) + window // 2
        pieces.append(audio[start:cut])
        start = cut

    pieces.append(audio[start:])
    return pieces
