"""LiveWhisper - voice dictation for Windows.

Ctrl+Alt+Space records your microphone. Press it again and the words are
transcribed, formatted, written the way you type them, and pasted wherever your
cursor was when you started. Notes mode (Ctrl+Alt+N) records a meeting - your
mic and the other people - into a note instead.

Threading: the app window (pywebview) owns the main thread, the recording
pill has its own thread and message loop, pystray runs its message loop in a
daemon thread, and hotkey handlers run in their own short-lived threads.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from datetime import datetime
from enum import Enum
from pathlib import Path

import keyboard
import pystray

from . import __version__
from . import config as cfgio
from . import bias, context, guard, icons, output, paths
from .actions import Actions
from .history import History
from .notes import NoteBook
from .pipeline import Pipeline
from .profile import ProfileStore
from .audio import TARGET_RATE, AudioError, Recorder, write_wav
from .overlay import RecordingOverlay
from .script.languages import speaker_languages
from .transcribe import AutoBackend, TranscriptionError, build_backend

log = logging.getLogger("livewhisper")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = paths.CONFIG


class State(Enum):
    IDLE = ("Idle", "idle")
    RECORDING = ("Recording", "recording")
    TRANSCRIBING = ("Transcribing", "transcribing")

    def __init__(self, label: str, colour_key: str):
        self.label = label
        self.colour_key = colour_key


class App:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.cfg = cfgio.load(config_path)
        self.state = State.IDLE
        self.profile_index = 0
        self.recorder: Recorder | None = None
        self.icon: pystray.Icon | None = None
        self.window = None              # the app window, once running
        self._overlay: RecordingOverlay | None = None
        self._started_at = 0.0
        self._backend = None
        self._hotkeys: list = []
        self._lock = threading.Lock()

        # personalisation + actions
        self.styles = ProfileStore()
        self.pipeline = Pipeline(self.cfg, self.styles)
        self.actions = Actions(self.cfg.get("actions", {}))
        self.notebook = NoteBook()
        self.history = History()
        self.note_mode = False
        self._force_script: str | None = None
        self._prime_stop = threading.Event()
        self._screen_at_start = None
        self._mode = "dictate"          # what the current recording is for
        self._window_at_start = 0       # where the text is meant to go
        self._generation = 0            # which recording a primed language is for

    # ---------------------------------------------------------------- config

    @property
    def profiles(self) -> list:
        return self.cfg.get("profiles") or [{"name": "Raw", "prompt": ""}]

    @property
    def profile(self) -> dict:
        return self.profiles[self.profile_index % len(self.profiles)]

    @property
    def backend_name(self) -> str:
        return self.cfg["transcription"].get("backend", "auto")

    def backend(self):
        if self._backend is None:
            self._backend = build_backend(self.backend_name, self.cfg["transcription"],
                                          languages=speaker_languages(self.cfg))
            # Both the combined backend and the local one it wraps talk to the
            # tray: fallback events come from one, specialist loading from the other.
            for b in (self._backend, getattr(self._backend, "local", None)):
                if b is not None and hasattr(b, "notify"):
                    b.notify = self.notify
        return self._backend

    def apply_config(self, cfg: dict) -> None:
        """Called by the settings window after a save."""
        self.cfg = cfg
        self._backend = None            # rebuild with the new settings
        self.pipeline = Pipeline(cfg, self.styles)
        self.actions = Actions(cfg.get("actions", {}))
        self.profile_index = 0
        self._bind_hotkeys()
        if self.icon:
            self.icon.menu = self._menu()
        self._set_state(self.state)
        threading.Thread(target=self._warm_up, daemon=True).start()

    # -------------------------------------------------------------------- ui

    def notify(self, message: str, title: str = "LiveWhisper") -> None:
        log.info("%s: %s", title, message)
        # A short note belongs in the pill, where the user is already looking;
        # a toast in the corner is for anything that needs more words.
        if (len(message) <= 60 and self.cfg.get("ui", {}).get("overlay", True)
                and title == "LiveWhisper"):
            if self._ensure_overlay() is not None:
                self._overlay.message(message.rstrip("."))
                return
        if self.icon:
            try:
                self.icon.notify(message, title)
            except Exception:
                log.debug("tray notification failed", exc_info=True)

    def _colour(self, key: str) -> str:
        return {"idle": icons.IDLE, "recording": icons.RECORDING,
                "transcribing": icons.WORKING}[key]

    def _set_state(self, state: State) -> None:
        self.state = state
        if self._overlay is not None:
            if state is State.TRANSCRIBING:
                self._overlay.working()
            elif state is State.IDLE:
                self._overlay.hide()
        if self.icon:
            self.icon.icon = icons.tray_image(self._colour(state.colour_key))
            self.icon.title = (f"LiveWhisper - {state.label} "
                               f"({self.profile['name']} / {self.backend_name})")

    # --------------------------------------------------------------- actions

    def toggle_record(self) -> None:
        with self._lock:
            if self.state is State.TRANSCRIBING:
                self.notify("Still working on the last one.")
                return
            if self.state is State.RECORDING:
                self._stop()
            else:
                self._start("dictate")

    def toggle_command(self) -> None:
        """Ctrl+Alt+W: press, say what to write, press again.

        It used to listen for a fixed 8 seconds, so every instruction - even
        "say yes" - waited the full 8, and a long one was cut off. Now it works
        like dictation. The writing model is checked before listening, so a
        missing model is reported before the user has spoken, not after.
        """
        with self._lock:
            if self.state is State.TRANSCRIBING:
                self.notify("Still working on the last one.")
                return
            if self.state is State.RECORDING:
                if self._mode == "command":
                    self._stop()
                else:
                    self.notify("Finish the dictation first.")
                return
            problem = self.actions.unavailable()
            if problem:
                self.notify(problem)
                return
            self._start("command")
            if self.state is State.RECORDING:
                key = self.cfg["hotkeys"].get("write", "ctrl+alt+w").title()
                self.notify(f"Say what to write, then press {key} again.")

    def _sources(self, mode: str) -> tuple:
        """(system audio, microphone) for this kind of recording.

        Dictation is your voice, so it is the microphone alone: recording the
        speakers as well put whatever was playing - a video, music, a call -
        into the text, and flagged "system audio was silent" on every quiet
        dictation. System audio is for notes (meetings), where the other
        people are the point. audio.dictation_includes_system opts back in.
        """
        a = self.cfg["audio"]
        mic = bool(a.get("capture_mic", True))
        if mode == "command":
            return False, True
        if self.note_mode or a.get("dictation_includes_system", False):
            return bool(a.get("capture_system", True)), mic
        return False, True

    def _start(self, mode: str = "dictate") -> None:
        a = self.cfg["audio"]
        system, mic = self._sources(mode)
        self.recorder = Recorder(
            capture_system=system,
            capture_mic=mic,
            system_gain=float(a.get("system_gain", 1.0)),
            mic_gain=float(a.get("mic_gain", 1.0)),
        )
        try:
            self.recorder.start()
        except AudioError as e:
            self.recorder = None
            self.notify(f"Could not start recording: {e}")
            return
        self._mode = mode
        self._window_at_start = context.foreground_window()
        try:
            self._screen_at_start = context.capture()
        except Exception:
            self._screen_at_start = None
        self._started_at = time.monotonic()
        self._prime_stop = threading.Event()
        begin = getattr(self.backend(), "new_recording", None)
        self._generation = begin() if begin else self._generation + 1
        threading.Thread(target=self._settle_language,
                         args=(self.recorder, self._generation), daemon=True).start()
        self._set_state(State.RECORDING)
        if self.cfg.get("ui", {}).get("overlay", True):
            self._show_overlay(command=mode == "command")

    # When to look at the audio so far and settle the language. Early enough
    # to be off the critical path even for a short dictation, late enough to
    # have real speech to judge from; the second look costs nothing anybody
    # waits for and gives a long dictation more audio to work with.
    # Look again every couple of seconds while the speaker talks, so the last
    # guess before they stop was made on nearly all of it. One look at 2.5 s -
    # the first version - heard Punjabi, Marathi, Kannada and Sindhi as English
    # in the end-to-end run: two seconds of speech is not enough to tell.
    # Detection only reads the first 30 s, so there is no point after that.
    SETTLE_EVERY_S = 2.0
    SETTLE_UNTIL_S = 30.0

    def _settle_language(self, recorder, generation: int = 0) -> None:
        """Detect the language while the speaker is still talking.

        Detection is an entire encoder pass, and it only ever reads the start
        of the recording, so doing it after the hotkey is released adds to the
        wait for nothing. Transcription uses the latest guess only if it was
        made on most of the recording (LocalBackend.PRIME_TRUST); otherwise it
        detects again. Best effort throughout.
        """
        try:
            # The formatting model may have been unloaded while idle; bring it
            # back while the user is talking, not after.
            self.pipeline.warm_formatter()
        except Exception:
            log.debug("formatter warm-up failed", exc_info=True)
        settle = getattr(self.backend(), "prime", None)
        if settle is None:
            return
        interval = self.SETTLE_EVERY_S
        elapsed = 0.0
        while elapsed < self.SETTLE_UNTIL_S:
            if self._prime_stop.wait(interval):
                return                          # recording already ended
            elapsed += interval
            if self.recorder is not recorder:
                return
            try:
                audio = recorder.snapshot()
            except Exception:
                log.debug("could not read the recording so far", exc_info=True)
                return
            if len(audio) < 1.5 * TARGET_RATE:
                continue
            t0 = time.perf_counter()
            try:
                settle(audio, generation=generation)
            except TypeError:                   # a backend without generations
                settle(audio)
            # On a CPU one detection can take a second or two; never spend more
            # than about a third of the machine on it.
            interval = max(self.SETTLE_EVERY_S, 3 * (time.perf_counter() - t0))

    def _stop(self) -> None:
        self._prime_stop.set()
        recorder, self.recorder = self.recorder, None
        if self._overlay is not None:
            self._overlay.working()
        if recorder is None:
            self._set_state(State.IDLE)
            return
        recording = recorder.stop()
        if recording.seconds < 0.5:
            self._set_state(State.IDLE)
            self.notify("Nothing captured - recording was too short.")
            return

        # Loopback keeps delivering buffers with nothing playing, so a silent
        # track means nothing was audible rather than nothing was recorded.
        silent = 1e-4
        system, mic = self._sources(self._mode)
        if mic and recording.mic_peak < silent:
            self.notify("The microphone recorded silence - is it muted, or is "
                        "another app holding it?")
        elif system and self.note_mode and recording.system_peak < silent:
            self.notify("System audio was silent - only your microphone was captured.")

        self._set_state(State.TRANSCRIBING)
        work = self._transcribe if self._mode == "dictate" else self._write_from
        threading.Thread(target=work, args=(recording,), daemon=True).start()

    # ------------------------------------------------- personalised pipeline

    def _apply_pipeline(self, transcript: str) -> str:
        """Romanize, apply this app's habits, and learn from the last edit."""
        try:
            screen = self._screen_at_start or context.capture()
            # Learn before writing: whatever is in the field now reflects any
            # corrections made to what we pasted last time.
            if (self.cfg.get("learning") or {}).get("enabled", True):
                for note in self.pipeline.learn_from_screen(screen):
                    log.info("learned: %s", note)
                    self.notify(note)
            heard = getattr(self.backend(), "last_language", None)
            delivery = self.pipeline.process(
                transcript, screen, force_script=self._force_script,
                heard_language=heard,
                latin_output=bool(getattr(self.backend(), "last_latin_output", False)))
            self._force_script = None
            log.info("app=%s script=%s romanized=%s lang=%s",
                     delivery.app, delivery.script, delivery.romanized,
                     delivery.language)
            return delivery.text
        except Exception:
            log.warning("pipeline failed, delivering raw transcript", exc_info=True)
            return transcript

    # ------------------------------------------------------------- actions

    def fix_field(self) -> None:
        """Ctrl+Alt+F: correct the grammar of the text in the focused field."""
        with self._lock:
            if self.state is not State.IDLE:
                self.notify("Finish the dictation first.")
                return
            problem = self.actions.unavailable()
            if problem:
                self.notify(problem)
                return
            self._set_state(State.TRANSCRIBING)
        try:
            screen = context.capture(
                use_ocr=self.cfg.get("context", {}).get("ocr_fallback", False))
            target = (screen.focused_text or "").strip()
            if not target:
                self.notify("Nothing to fix - no text found in this field.")
                return
            fixed = self.actions.fix(target)
            if fixed.strip() == target.strip():
                self.notify("Already looks correct.")
                return
            output.deliver(fixed, auto_paste=False, copy_to_clipboard=True)
            self.notify(f"Corrected - {len(fixed.split())} words on the clipboard. "
                        f"Select the text and paste to replace it.")
        except Exception as e:
            log.exception("fix failed")
            self.notify(f"Could not fix the text: {e}")
        finally:
            self._set_state(State.IDLE)

    def _write_from(self, recording) -> None:
        """The second half of Ctrl+Alt+W: instruction -> finished text -> paste."""
        try:
            t0 = time.perf_counter()
            instruction = self.backend().transcribe(recording.audio)
            if not instruction.strip() or guard.invented(instruction, recording.audio):
                self.notify("Did not catch what to write.")
                return
            log.info("command: %s", instruction)
            screen = self._screen_at_start or context.capture()
            profile = self.styles.get(screen.app if screen else "")
            result = self.actions.compose(instruction, profile, screen)
            # The model wrote finished text: spoken-punctuation rules would
            # turn "a new line before the signature" into a line break.
            result = self.pipeline.process(result, screen, composed=True).text
            o = self.cfg["output"]
            moved = self._window_moved()
            output.deliver(result,
                           auto_paste=o.get("auto_paste", True) and not moved,
                           copy_to_clipboard=o.get("copy_to_clipboard", True) or moved)
            self._record_history(result, recording.seconds,
                                 "copied" if moved else "pasted", mode="command")
            if moved:
                self.notify("You switched windows, so nothing was pasted - the "
                            "text is on your clipboard.")
                return
            log.info("timing: wrote %d words in %.0f ms", len(result.split()),
                     (time.perf_counter() - t0) * 1000)
        except output.ClipboardBusy:
            self.notify("The clipboard is busy in another app - try again.")
        except Exception as e:
            log.exception("write failed")
            self.notify(f"Could not write that: {e}")
        finally:
            self._set_state(State.IDLE)

    def toggle_notes(self) -> None:
        self.note_mode = not self.note_mode
        if self.note_mode:
            note = self.notebook.start()
            self.notify(f"Notes on - {note.path.name}")
        else:
            note = self.notebook.stop()
            if note:
                self.notify(f"Note saved ({note.word_count} words).")

    def force_devanagari(self) -> None:
        self._force_script = "native"
        self.notify("Next dictation will stay in the original script.")

    def cancel(self) -> None:
        with self._lock:
            if self.state is not State.RECORDING:
                return
            self._prime_stop.set()
            forget = getattr(self.backend(), "forget_priming", None)
            if forget:
                forget()                    # it belonged to a recording we threw away
            recorder, self.recorder = self.recorder, None
            self._hide_overlay()
            if recorder:
                recorder.stop()
            self._set_state(State.IDLE)
            self.notify("Recording discarded.")

    def _transcribe(self, recording) -> None:
        try:
            mins, secs = divmod(int(recording.seconds), 60)
            log.info("transcribing %dm%02ds via %s", mins, secs, self.backend_name)
            t0 = time.perf_counter()
            transcript = self.backend().transcribe(
                recording.audio, hotwords=self._names_in_front_of_me(),
                native=self._wants_native())
            t_asr = time.perf_counter()
            if not transcript:
                self.notify("No speech detected in the recording.")
                return
            if guard.invented(transcript, recording.audio):
                log.info("dropped a transcript that looks made up: %r", transcript[:80])
                self.notify("Nothing was heard - is the right microphone on?")
                return

            # Notes mode diverts the transcript into the open note instead.
            if self.note_mode:
                note = self.notebook.append(transcript)
                self.notify(f"Added to note ({note.word_count} words).")
                return

            text = self._apply_pipeline(transcript)
            text = output.compose(self.profile.get("prompt", ""), text)
            t_pipe = time.perf_counter()
            self._save(text)

            o = self.cfg["output"]
            moved = self._window_moved()
            pasted, kept = output.deliver(
                text,
                auto_paste=o.get("auto_paste", True) and not moved,
                copy_to_clipboard=o.get("copy_to_clipboard", True) or moved,
                restore_clipboard=o.get("restore_clipboard", False) and not moved,
            )
            self._record_history(text, recording.seconds,
                                 "copied" if moved or not pasted else "pasted")
            if moved:
                self.notify("You switched windows while dictating, so nothing was "
                            "pasted - the text is on your clipboard.")
                return
            t_done = time.perf_counter()
            # One line per dictation with where the wait went, so a slow one in
            # a user's log says which stage to look at.
            log.info("timing: speech %.0f ms, text %.0f ms, paste %.0f ms (%s)",
                     (t_asr - t0) * 1000, (t_pipe - t_asr) * 1000,
                     (t_done - t_pipe) * 1000,
                     getattr(self.pipeline._last, "formatted_by", "?"))
            # The words appearing are the confirmation; the pill only speaks up
            # when they did not.
            if not pasted:
                self.notify("Copied - press Ctrl+V to paste" if kept
                            else "Saved to History")
        except output.ClipboardBusy:
            # The transcript is already saved; only the paste could not happen.
            self.notify("The clipboard is busy in another app - your text is "
                        "saved in Transcripts.")
        except TranscriptionError as e:
            self.notify(f"Transcription failed: {e}")
            self._save_audio_on_failure(recording)
        except Exception as e:
            log.exception("unexpected failure during transcription")
            self.notify(f"Transcription failed: {e}")
            self._save_audio_on_failure(recording)
        finally:
            self._set_state(State.IDLE)

    def _record_history(self, text: str, seconds: float, delivered: str,
                        mode: str = "dictate") -> None:
        try:
            screen = self._screen_at_start
            self.history.add(text, seconds, app=(screen.app if screen else "") or "",
                             language=getattr(self.backend(), "last_language", "") or "",
                             mode=mode, delivered=delivered)
        except Exception:
            log.debug("could not record history", exc_info=True)

    def _wants_native(self) -> bool:
        """Will this dictation be pasted in the language's own script?

        Decided before transcribing, because it decides which model may decode:
        the same rule the pipeline applies afterwards (a forced script, the
        app's setting, or the script already in the field).
        """
        if self._force_script:
            return self._force_script == "native"
        screen = self._screen_at_start
        try:
            return self.pipeline.choose_script(screen.app if screen else "",
                                               screen) == "native"
        except Exception:
            return False

    def _window_moved(self) -> bool:
        """Is focus somewhere other than the window the dictation started in?

        Text goes wherever the cursor is when it is pasted. In testing, a
        dictation started in Notepad and finished while the user was in a Google
        Doc and was pasted into the doc. Dictation into one place must not land
        in another - a chat, a document, a password box - so if focus has moved
        the text is left on the clipboard instead.
        """
        if not self._window_at_start:
            return False
        now = context.foreground_window()
        return bool(now) and now != self._window_at_start

    def _names_in_front_of_me(self) -> str:
        """Names on screen worth expecting, for the decoder to lean on.

        Off by default for nobody: this is the app already reading the window
        for its other features, so it costs one string and never leaves the
        machine. Set context.bias to false to stop it.
        """
        if not (self.cfg.get("context") or {}).get("bias", True):
            return ""
        screen = self._screen_at_start
        try:
            return bias.phrases(
                screen_text=(screen.text if screen else ""),
                focused_text=(screen.focused_text if screen else ""),
                extra=(self.cfg.get("transcription") or {}).get("vocabulary", ""))
        except Exception:
            log.debug("could not read names off the screen", exc_info=True)
            return ""

    def _transcript_dir(self) -> Path:
        d = paths.HOME / self.cfg["output"].get("transcript_dir", "transcripts")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _save(self, text: str) -> None:
        if not self.cfg["output"].get("save_transcripts", True):
            return
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        path = self._transcript_dir() / f"{stamp}_{self.profile['name']}.txt"
        path.write_text(text, encoding="utf-8")
        log.info("saved transcript to %s", path)

    def _save_audio_on_failure(self, recording) -> None:
        """Losing a 40-minute meeting to a transient error is unacceptable."""
        try:
            stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            path = self._transcript_dir() / f"{stamp}_FAILED.wav"
            write_wav(path, recording.audio)
            self.notify(f"Audio kept at {path.name} - you can retry it.")
        except Exception:
            log.exception("could not preserve audio after failure")

    def cycle_profile(self) -> None:
        self.profile_index = (self.profile_index + 1) % len(self.profiles)
        self._set_state(self.state)
        self.notify(f"Profile: {self.profile['name']}")

    def toggle_backend(self) -> None:
        order = ["auto", "groq", "local"]
        current = self.backend_name
        nxt = order[(order.index(current) + 1) % len(order)] if current in order else "auto"
        self.cfg["transcription"]["backend"] = nxt
        self._backend = None
        self._set_state(self.state)
        self.notify(f"Engine: {nxt}")

    def open_transcripts(self) -> None:
        os.startfile(self._transcript_dir())  # noqa: S606 - Windows-only by design

    # -------------------------------------------------------------- overlay

    def _ensure_overlay(self):
        if self._overlay is None:
            try:
                self._overlay = RecordingOverlay(
                    on_stop=self._finish_from_overlay,
                    on_cancel=self.cancel,
                    position=self.cfg.get("ui", {}).get("overlay_position"),
                    on_move=self._remember_overlay_position,
                )
            except Exception:
                log.exception("recording overlay unavailable")
        return self._overlay

    def _show_overlay(self, command: bool = False) -> None:
        if self._ensure_overlay() is None:
            return

        def level() -> float:
            rec = self.recorder
            return rec.level() if rec is not None else 0.0

        self._overlay.show(level_fn=level, command=command)

    def _finish_from_overlay(self) -> None:
        """The pill's ✓: the same as pressing the hotkey that started it."""
        if self._mode == "command":
            self.toggle_command()
        else:
            self.toggle_record()

    def _hide_overlay(self) -> None:
        if self._overlay is not None:
            self._overlay.hide()

    def _remember_overlay_position(self, x: int, y: int) -> None:
        self.cfg.setdefault("ui", {})["overlay_position"] = [x, y]
        try:
            cfgio.save(self.config_path, self.cfg)
        except Exception:
            log.debug("could not persist overlay position", exc_info=True)

    # ------------------------------------------------------------- settings

    def open_window(self, page: str | None = None) -> None:
        if self.window is not None:
            self.window.show(page)

    def open_settings(self) -> None:
        self.open_window("settings")

    def open_wizard(self) -> None:
        self.open_window("dictionary")

    def component_installed(self, cid: str) -> None:
        """A download finished: pick up the route it wrote and use it."""
        if cid in ("formatter", "writer"):
            # Text models: the speech model is untouched, so do not reload it.
            self.pipeline = Pipeline(self.cfg, self.styles)
            threading.Thread(target=self.pipeline.warm_formatter, daemon=True).start()
            return
        try:
            cfg = cfgio.load(self.config_path)
        except Exception:
            log.exception("could not reload the config after installing %s", cid)
            return
        self.apply_config(cfg)

    # --------------------------------------------------------------- wiring

    def _unbind_hotkeys(self) -> None:
        # keyboard.unhook_all_hotkeys() raises AttributeError when its listener
        # has not been created yet, so remove our own handles instead.
        for handle in self._hotkeys:
            try:
                keyboard.remove_hotkey(handle)
            except (KeyError, ValueError):
                pass
        self._hotkeys.clear()

    def _bind_hotkeys(self) -> None:
        self._unbind_hotkeys()
        hk = self.cfg["hotkeys"]
        bindings = {
            hk.get("record", "ctrl+alt+space"): self.toggle_record,
            hk.get("cycle_profile", "ctrl+alt+p"): self.cycle_profile,
            hk.get("toggle_backend", "ctrl+alt+g"): self.toggle_backend,
            hk.get("cancel", "ctrl+alt+x"): self.cancel,
            hk.get("write", "ctrl+alt+w"): self.toggle_command,
            hk.get("fix", "ctrl+alt+f"): self.fix_field,
            hk.get("notes", "ctrl+alt+n"): self.toggle_notes,
            hk.get("devanagari", "ctrl+alt+h"): self.force_devanagari,
        }
        for combo, fn in bindings.items():
            # Run off the hook thread so a slow handler cannot wedge the keyboard.
            try:
                self._hotkeys.append(keyboard.add_hotkey(
                    combo, lambda f=fn: threading.Thread(target=f, daemon=True).start()))
            except ValueError as e:
                self.notify(f"Invalid hotkey {combo!r}: {e}")
        log.info("hotkeys: %s", ", ".join(bindings))

    def _menu(self) -> pystray.Menu:
        def select(i):
            def handler(icon, item):
                self.profile_index = i
                self._set_state(self.state)
            return handler

        profiles = [
            pystray.MenuItem(p["name"], select(i),
                             checked=lambda item, i=i: self.profile_index == i,
                             radio=True)
            for i, p in enumerate(self.profiles)
        ]
        status = {State.IDLE: "Ready", State.RECORDING: "Listening...",
                  State.TRANSCRIBING: "Writing..."}
        return pystray.Menu(
            pystray.MenuItem(lambda item: f"LiveWhisper - {status[self.state]}", None,
                             enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open LiveWhisper", lambda icon, item: self.open_window(),
                             default=True),
            pystray.MenuItem(
                lambda item: ("Stop and transcribe" if self.state is State.RECORDING
                              else "Start recording"),
                lambda icon, item: threading.Thread(target=self.toggle_record,
                                                    daemon=True).start()),
            pystray.MenuItem("Discard recording",
                             lambda icon, item: threading.Thread(target=self.cancel,
                                                                 daemon=True).start()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Prompt profile", pystray.Menu(*profiles),
                             visible=len(profiles) > 1),
            pystray.MenuItem("Settings", lambda icon, item: self.open_settings()),
            pystray.MenuItem("History", lambda icon, item: self.open_window("history")),
            pystray.MenuItem("Open log (for bug reports)",
                             lambda icon, item: self.open_log()),
            pystray.MenuItem("Quit", lambda icon, item: self.quit()),
        )

    def open_log(self) -> None:
        from .logs import log_path
        path = log_path()
        if path.exists():
            os.startfile(str(path))
        else:
            self.notify(f"No log yet - it will appear at {path}")

    def _warm_up(self) -> None:
        """Prepare what is ready. Must never trigger a 3 GB download by itself."""
        try:
            backend = self.backend()
            warm = getattr(backend, "warm", None)
            # "Loading the ... model" is for someone waiting on a dictation,
            # not for a warm-up nobody asked for.
            parts = [b for b in (backend, getattr(backend, "local", None)) if b is not None]
            saved = [getattr(b, "notify", None) for b in parts]
            for b in parts:
                b.notify = lambda msg: log.info("%s", msg)
            try:
                (warm or backend.load)()
            finally:
                for b, n in zip(parts, saved):
                    if n is not None:
                        b.notify = n
            log.info("%s backend ready", self.backend_name)
            self.pipeline.warm_formatter()
        except Exception as e:
            log.warning("backend warm-up: %s", e)

    def quit(self) -> None:
        self._unbind_hotkeys()
        if self.recorder:
            self.recorder.stop()
        if self.icon:
            self.icon.stop()
        if self._overlay is not None:
            self._overlay.close()
        try:
            from . import llm
            llm.shutdown()
        except Exception:
            log.debug("model runner shutdown failed", exc_info=True)
        if self.window is not None:
            self.window.destroy()

    def run(self, show: str | None = None) -> None:
        import webview

        from . import instance
        from .window import AppWindow

        icons.set_app_id()  # must precede any window, or the taskbar shows Python
        self.icon = pystray.Icon("livewhisper", icons.tray_image(self._colour("idle")),
                                 "LiveWhisper", self._menu())
        self._set_state(State.IDLE)
        self._bind_hotkeys()
        threading.Thread(target=self.icon.run, daemon=True).start()
        threading.Thread(target=self._warm_up, daemon=True).start()
        instance.serve(lambda: self.open_window())

        self.window = AppWindow(self)
        first_run = not self.cfg.get("ui", {}).get("onboarded", False)
        if show or first_run:
            threading.Timer(0.8, lambda: self.open_window(show)).start()

        hk = self.cfg["hotkeys"].get("record", "ctrl+alt+space")
        print(f"LiveWhisper running. Press {hk} to start/stop recording.", flush=True)
        webview.start(gui="edgechromium", private_mode=False,
                      storage_path=str(paths.CACHE / "webview"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Voice dictation for Windows.")
    parser.add_argument("-c", "--config", type=Path, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--settings", action="store_true",
                        help="open the settings window on launch")
    parser.add_argument("--background", action="store_true",
                        help="start in the tray without opening the window")
    args = parser.parse_args()

    from . import instance
    from .logs import setup as setup_logging

    # A second launch - the Start menu entry clicked again - opens the running
    # app's window instead of starting another copy that fights it for the
    # hotkeys.
    if instance.signal_running():
        return 0

    log_file = setup_logging(args.verbose)
    log.info("LiveWhisper %s starting; log at %s", __version__, log_file)

    config = args.config or paths.ensure_config()
    if not config.exists():
        print(f"config not found: {config}", file=sys.stderr)
        return 1

    app = App(config)
    show = "settings" if args.settings else (None if args.background else "home")
    try:
        app.run(show=show)
    except KeyboardInterrupt:
        pass
    finally:
        app.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
