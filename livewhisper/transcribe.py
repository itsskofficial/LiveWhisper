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


# faster-whisper packs the speech it finds into windows as long as the model
# allows, 30 seconds, and Whisper stops early on a full one - nothing reports
# it, the transcript just ends sooner than the recording did. On paragraphs of
# three FLEURS sentences, 30-second windows kept 74% of the Hindi words and 77%
# of the English. 15-second windows kept 96% and 93%, and cost nothing on single
# sentences (27.6% -> 27.5% Hindi WER, 5.3% English either way). Shorter still
# starts cutting sentences mid-speech: 10 seconds raised single-sentence Hindi
# to 31.2%. Deciding by recording length was tried and lost too - recordings
# just under the cut-off still lost words. Measured in tests/bench_windows.py.
DECODE_WINDOW_S = 15


def window_for(seconds: float, configured: int | None = None) -> int:
    """Seconds of speech per decoded window. `seconds` is kept for callers that
    want to vary it; the measurements say a fixed window is best."""
    return int(configured) if configured else DECODE_WINDOW_S


def _join_segments(segments, gap_s: float = 1.6) -> str:
    """Join the decoded segments, breaking a paragraph where the speaker did.

    The recording already knows where the paragraphs are: a speaker who stops
    for a second and a half has finished a thought. Whisper reports the silence
    it skipped as a gap between segment timestamps, so the structure costs
    nothing to recover - and recovering it here, rather than in the formatter,
    means romanization and every later pass see the text already laid out.

    `gap_s` of 0 turns it off and joins with spaces, as before.
    """
    parts: list = []
    previous_end = None
    for s in segments:
        piece = (getattr(s, "text", "") or "").strip()
        if not piece:
            continue
        # Timestamps are optional: a backend that does not report them, or a
        # test stub, simply gets the spaces it would have had before.
        start, end = getattr(s, "start", None), getattr(s, "end", None)
        if parts:
            gap = (start - previous_end) if (start is not None
                                             and previous_end is not None) else 0.0
            parts.append("\n\n" if gap_s and gap >= gap_s else " ")
        parts.append(piece)
        previous_end = end
    return "".join(parts).strip()


class LocalBackend:
    name = "local"

    def __init__(self, cfg: dict, vocabulary: str = "", languages: list | None = None):
        self.last_language: str | None = None   # what Whisper heard, e.g. "ta"
        self.languages = [c for c in (languages or []) if c]
        self._routed: dict = {}                 # path -> (model, batched), LRU order
        self.last_latin_output = False          # last text came from a Hinglish model
        self.notify = lambda msg: None          # set by the app to reach the tray
        self.cfg = cfg
        self.vocabulary = vocabulary.strip()
        self._model = None
        self._batched = None
        self._primed: str | None = None     # language settled while recording
        self._primed_seconds = 0.0          # how much audio that guess heard
        self._generation = 0                # the recording that priming is for
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

        from .hub import plain_http

        plain_http()             # the xet backend stalls silently on big files
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

        # Load the specialists for the user's languages now rather than on the
        # first dictation in each, which would otherwise stall for seconds while
        # 1.5-6 GB reach the GPU - and, with only one allowed, swap them on every
        # change of language. Outside the lock: _model_for takes it too.
        budget = max(0, int(self.cfg.get("max_extra_models", 1)))
        routed = [lang for lang in self.languages if self._route(lang).get("path")]
        for lang in routed[:budget]:
            self._model_for(lang)

    def _batch_size(self) -> int:
        return int(self.cfg.get("batch_size", 8))

    def _pick_language(self, audio: np.ndarray) -> str | None:
        """Detect the language, but only among the ones this user speaks.

        Whisper's own detection weighs all 99 languages and, on dictation-length
        clips, picks the wrong one often enough to matter. Taking its
        probabilities and choosing the best of the user's languages costs one
        extra encoder pass on at most 30 seconds of audio.

        None means "let Whisper decide" - no restriction configured, or
        detection failed, in which case the old behaviour is the safe one.
        """
        if not self.languages:
            return None
        if len(self.languages) == 1:
            return self.languages[0]
        try:
            _lang, _p, probs = self._model.detect_language(
                audio[: 30 * TARGET_RATE], vad_filter=True)
        except Exception:
            log.debug("constrained language detection failed", exc_info=True)
            return None
        pool = [(code, p) for code, p in probs if code in self.languages]
        if not pool:
            return None
        best = max(pool, key=lambda x: x[1])[0]
        return self._second_guess_english(best, pool)

    # Measured on FLEURS: Marathi recordings that detection called English had
    # English at 0.54-0.89 once renormalised over {mr, en}; real English speech
    # scored at least 0.9998 against Hindi and 1.0 against Marathi and Sindhi.
    # 0.99 sits between the two on a log-odds scale.
    ENGLISH_MIN = 0.99

    def _second_guess_english(self, best: str, pool: list) -> str:
        """Refuse a borderline "English" when the user also speaks another language.

        Detection choosing English for Indic speech is the worst failure in the
        app: large-v3 then writes fluent English that was never said - on 7 of
        40 Marathi recordings, "May God bless you with the best of luck" for a
        sentence about organisational resources. The opposite mistake, decoding
        mostly-English speech as Hindi, degrades into romanizable text instead.
        So English has to be clearly ahead, not merely ahead.
        """
        others = [(code, p) for code, p in pool if code != "en"]
        if best != "en" or not others:
            return best
        total = sum(p for _, p in pool) or 1.0
        p_en = dict(pool).get("en", 0.0) / total
        if p_en >= self.ENGLISH_MIN:
            return best
        fallback = max(others, key=lambda x: x[1])[0]
        log.info("english only %.2f likely; decoding as %s instead", p_en, fallback)
        return fallback

    def _route(self, language: str | None) -> dict:
        """The configured specialist for a language, normalised to a dict.

        `models: {ta: D:/models/ct2/ta-medium}` is the short form. The long form
        carries what the app must know about the model's output:

            hi: {path: D:/models/ct2/hinglish-prime, latin_output: true,
                 language: en}

        latin_output means it writes romanized text itself; language is the
        token to decode with, when the model was trained on a different one.
        """
        route = (self.cfg.get("models") or {}).get(language) if language else None
        if isinstance(route, str):
            return {"path": route}
        return dict(route) if isinstance(route, dict) else {}

    def _model_for(self, language: str | None) -> tuple:
        """The model that should decode this language: a specialist, or the main one.

        `transcription.local.models` maps a language to a model directory, e.g.
        {ta: D:/models/ct2/ta-large-v2}. Detection always runs on the main model;
        only decoding moves. Specialists load on first use and at most
        `max_extra_models` stay in VRAM (default 1), least recently used out
        first - two large models already fill an 8 GB card.

        A specialist that fails to load is logged and skipped, never fatal: a
        dictation that falls back to large-v3 beats one that does not happen.
        """
        path = self._route(language).get("path")
        if not path:
            return self._model, self._batched
        with self._lock:
            if path in self._routed:
                pair = self._routed.pop(path)
                self._routed[path] = pair           # mark most recently used
                return pair
            limit = max(0, int(self.cfg.get("max_extra_models", 1)))
            while self._routed and len(self._routed) >= limit:
                evicted = next(iter(self._routed))
                del self._routed[evicted]
                log.info("unloaded specialist %s", evicted)
            if limit == 0:
                return self._model, self._batched
            try:
                from .script.languages import LANGUAGES
                name = (LANGUAGES[language].name if language in LANGUAGES
                        else {"en": "English"}.get(language, language))
            except Exception:
                name = language
            self.notify(f"Loading the {name} speech model - only slow the first time.")
            try:
                from faster_whisper import BatchedInferencePipeline, WhisperModel
                device = self.cfg.get("device", "cuda")
                m = WhisperModel(path, device=device,
                                 compute_type=self.cfg.get("compute_type", "int8_float16"))
                b = BatchedInferencePipeline(model=m) if self._batch_size() > 1 else None
            except Exception:
                log.warning("could not load specialist %s for %s; using main model",
                            path, language, exc_info=True)
                return self._model, self._batched
            log.info("loaded specialist %s for %s", path, language)
            self._routed[path] = (m, b)
            return m, b

    def new_recording(self) -> int:
        """A recording has started: forget any language settled for another."""
        self._generation += 1
        self._primed = None
        self._primed_seconds = 0.0
        return self._generation

    # A settled language is used only if it was decided on most of what was
    # said: at least 70% of the recording, or 8 s of it, whichever is less.
    PRIME_TRUST = (0.7, 8.0)

    def _trusted_prime(self, audio: np.ndarray) -> str | None:
        primed, seconds = self._primed, self._primed_seconds
        self._primed, self._primed_seconds = None, 0.0
        if not primed:
            return None
        total = len(audio) / TARGET_RATE
        share, enough = self.PRIME_TRUST
        if seconds >= min(enough, share * total):
            return primed
        log.info("language guessed on %.1f of %.1f s; detecting again", seconds, total)
        return None

    def prime(self, audio: np.ndarray, generation: int | None = None) -> str | None:
        """Settle the language now, on the audio captured so far.

        Detection is a whole extra encoder pass - measured at ~300 ms of the
        ~900 ms a four-second dictation takes on this machine, a third of the
        wait, and it is spent *after* the speaker has stopped. It only ever
        looks at the opening of the recording, so it can just as well run while
        they are still talking. `transcribe` then uses the answer and the
        critical path is decoding alone.

        Nothing here is required: any failure, and detection happens as before.
        """
        if self.cfg.get("language") or len(self.languages) < 2:
            return None                    # nothing to detect
        try:
            self.load()
            language = self._pick_language(audio)
        except Exception:
            log.debug("could not settle the language early", exc_info=True)
            return None
        # Detection takes a while. If the recording it was for has already been
        # transcribed or cancelled, the answer belongs to nobody - storing it
        # would force the NEXT dictation into this one's language.
        if language and (generation is None or generation == self._generation):
            self._primed = language
            self._primed_seconds = len(audio) / TARGET_RATE
            log.info("language settled during recording: %s", language)
        return language

    def _on_disk(self) -> bool:
        from pathlib import Path
        model = str(self.cfg.get("model", "large-v3"))
        return Path(model).exists() or self.is_downloaded()

    def warm(self) -> None:
        """Run one throwaway decode, so the first real dictation is not the slow one.

        Loading puts the weights on the GPU but compiles nothing: the first
        decode afterwards pays for CUDA kernel selection and allocator warm-up,
        which the latency benchmark once measured as a 2.8 s wait for a
        4-second clip that takes about a second every time after. Paying it at
        launch, where nobody is waiting, moves it off the first dictation.

        Silence would be dropped by VAD before reaching the decoder, so the
        warm-up turns VAD off and decodes one second of it directly, with the
        beam size real dictations use.

        Never downloads: a 3 GB download at launch, unannounced, would leave the
        first dictation waiting minutes. Download is an explicit step.
        """
        if not self._on_disk():
            log.info("speech model not downloaded yet; not warming")
            return
        self.load()
        try:
            segments, _ = self._model.transcribe(
                np.zeros(TARGET_RATE, dtype=np.float32), language="en",
                beam_size=int(self.cfg.get("beam_size", 5)), vad_filter=False,
                without_timestamps=True)
            list(segments)
        except Exception:
            log.debug("warm-up decode failed; the first dictation will be slower",
                      exc_info=True)

    def forget_priming(self) -> None:
        """Drop a primed language - the recording it belonged to is gone."""
        self._primed = None
        self._generation += 1

    def transcribe(self, audio: np.ndarray, hotwords: str = "",
                   native: bool = False) -> str:
        """`hotwords` are names worth expecting - see livewhisper/bias.py.

        `native`: the user wants the language's own script. A specialist that
        writes romanized text itself (Hinglish-Prime) cannot give them that, so
        it is skipped and the main model - or a native-script specialist -
        decodes instead. Without this, asking for Devanagari with the Hinglish
        model installed produced Latin text.
        """
        self.load()
        primed = self._trusted_prime(audio)
        self._generation += 1               # late priming for this one is ignored
        common = dict(
            language=self.cfg.get("language") or primed or self._pick_language(audio),
            beam_size=int(self.cfg.get("beam_size", 5)),
            initial_prompt=self.vocabulary or None,
            hotwords=hotwords or None,
        )
        route = self._route(common["language"])
        if native and route.get("latin_output"):
            model, batched, route = self._model, self._batched, {}
        else:
            model, batched = self._model_for(common["language"])
        self.last_latin_output = model is not self._model and route.get("latin_output", False)
        if model is not self._model and route.get("language"):
            # e.g. Oriserve's Hinglish models are driven with the "en" token,
            # while the rest of the app still needs to know the audio was Hindi.
            heard_as = common["language"]
            common["language"] = route["language"]
        else:
            heard_as = None
        if batched is not None:
            # Batched mode applies VAD and never conditions across segments -
            # what we want for code-switching anyway - but it then merges the
            # speech it found into windows as long as the model allows, 30
            # seconds, and asks for all of it in one go. Whisper answers a long
            # window by stopping early: on a 40-second Hindi recording it
            # returned 62 of the 92 words spoken, silently. Asking for shorter
            # windows returns the missing third and is faster as well, because
            # more of them decode in parallel (measured in
            # tests/results/decode_windows.md).
            segments, info = batched.transcribe(
                audio, batch_size=self._batch_size(),
                chunk_length=window_for(len(audio) / TARGET_RATE,
                                        self.cfg.get("chunk_length")),
                **common
            )
        else:
            segments, info = model.transcribe(
                audio,
                vad_filter=bool(self.cfg.get("vad_filter", True)),
                condition_on_previous_text=bool(
                    self.cfg.get("condition_on_previous_text", False)
                ),
                **common,
            )
        text = _join_segments(segments, float(self.cfg.get("paragraph_gap_seconds", 1.6)))
        self.last_language = heard_as or info.language
        self.language_probability = float(info.language_probability or 0)
        log.info("detected language %s (p=%.2f)", info.language,
                 info.language_probability)
        return text


class GroqBackend:
    name = "groq"

    def __init__(self, cfg: dict, vocabulary: str = "", languages: list | None = None):
        self.last_language: str | None = None
        self.language_probability = 0.0
        self.cfg = cfg
        self.vocabulary = vocabulary.strip()
        self.languages = [c for c in (languages or []) if c]

    def api_key(self) -> str | None:
        return os.environ.get(self.cfg.get("api_key_env", "GROQ_API_KEY"))

    def is_configured(self) -> bool:
        return bool(self.api_key())

    def load(self) -> None:
        if not self.is_configured():
            raise GroqUnavailable(
                f"{self.cfg.get('api_key_env', 'GROQ_API_KEY')} is not set"
            )

    def transcribe(self, audio: np.ndarray, hotwords: str = "",
                   native: bool = False) -> str:
        key = self.api_key()
        if not key:
            raise GroqUnavailable(
                f"{self.cfg.get('api_key_env', 'GROQ_API_KEY')} is not set"
            )
        # Whisper takes one prompt, so the names on screen join the user's own
        # vocabulary rather than replacing it.
        # Names read off the screen are deliberately not sent: the promise in
        # Settings is that screen text never leaves this machine.
        self._bias = self.vocabulary
        chunk = int(self.cfg.get("chunk_seconds", 600)) * TARGET_RATE
        parts = [self._chunk(c, key) for c in _split_on_silence(audio, chunk)]
        return " ".join(p for p in parts if p).strip()

    def _chunk(self, audio: np.ndarray, key: str) -> str:
        """Transcribe one chunk, keeping the language within the user's set.

        Groq cannot be told "choose between Hindi and English", only "use Hindi".
        So detection runs as normal, and only when it lands outside the user's
        languages is the chunk re-sent once per allowed language, keeping the
        answer the model was most confident in. Costs extra requests only on the
        misdetections, which are the clips that were wrong anyway.
        """
        forced = self.cfg.get("language") or None
        text, lang, _score = self._post(audio, key, forced)
        if forced or not self.languages or lang in self.languages:
            return text
        log.info("groq heard %s, outside %s; retrying within them",
                 lang, self.languages)
        best = None
        for code in self.languages:
            try:
                t, _l, s = self._post(audio, key, code)
            except TranscriptionError:
                continue
            if best is None or s > best[0]:
                best = (s, t, code)
        if best is None:
            return text
        self.last_language = best[2]
        return best[1]

    def _post(self, audio: np.ndarray, key: str,
              language: str | None = None) -> tuple:
        """-> (text, language heard, mean segment log-probability)."""
        # FLAC keeps us well under the upload cap without losing anything.
        buf = io.BytesIO()
        sf.write(buf, audio, TARGET_RATE, format="FLAC", subtype="PCM_16")
        buf.seek(0)

        data = {"model": self.cfg.get("model", "whisper-large-v3"),
                "response_format": "verbose_json"}
        if language:
            data["language"] = language
        prompt = getattr(self, "_bias", "") or self.vocabulary
        if prompt:
            data["prompt"] = prompt

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
            heard = _iso_code(payload["language"]) if payload.get("language") else language
            self.last_language = heard
            segs = [s.get("avg_logprob") for s in payload.get("segments") or []
                    if isinstance(s.get("avg_logprob"), (int, float))]
            score = sum(segs) / len(segs) if segs else float("-inf")
            return payload.get("text", "").strip(), heard, score

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
        self._groq_served = False
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

    def warm(self) -> None:
        if self.groq.is_configured():
            return
        if self.local.is_downloaded():
            self.local.warm()

    # Early language detection runs on the local model, and only matters when
    # the local model will be the one transcribing.
    def new_recording(self) -> int:
        return self.local.new_recording()

    def prime(self, audio, generation: int | None = None):
        if self.groq_available:
            return None
        return self.local.prime(audio, generation=generation)

    def forget_priming(self) -> None:
        self.local.forget_priming()

    def _block_groq(self) -> None:
        self._blocked_until = time.monotonic() + self.cooldown
        log.info("groq benched for %d minutes", self.cooldown // 60)

    @property
    def last_latin_output(self) -> bool:
        """True only when the local Hinglish specialist wrote the last text."""
        return (not self._groq_served
                and bool(getattr(self.local, "last_latin_output", False)))

    def transcribe(self, audio: np.ndarray, hotwords: str = "",
                   native: bool = False) -> str:
        self._groq_served = False
        if self.groq_available:
            try:
                out = self.groq.transcribe(audio, hotwords=hotwords)
                self._last_language = self.groq.last_language
                self._groq_served = True
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
        out = self.local.transcribe(audio, hotwords=hotwords, native=native)
        self._last_language = self.local.last_language
        return out


def build_backend(name: str, cfg: dict, languages: list | None = None):
    """Construct the backend named in `transcription.backend`.

    `languages` restricts detection to what the user speaks; see
    script.languages.speaker_languages. None leaves Whisper unrestricted.
    """
    vocabulary = cfg.get("vocabulary", "")
    groq = GroqBackend(cfg.get("groq", {}), vocabulary=vocabulary, languages=languages)
    local = LocalBackend(cfg.get("local", {}), vocabulary=vocabulary, languages=languages)

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
