"""LiveWhisper - hotkey-driven meeting transcription for Windows.

Ctrl+Alt+Space captures system audio plus your mic. Press it again and the audio
is transcribed, the active profile's prompt is prepended, and the result lands
wherever your cursor is.

Threading: Tk owns the main thread (settings window and overlay live there),
pystray runs its message loop in a daemon thread, and hotkey handlers run in
their own short-lived threads. Anything touching Tk marshals back with
root.after().
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from enum import Enum
from pathlib import Path

import keyboard
import pystray

from . import config as cfgio
from . import icons, output
from .audio import AudioError, Recorder, write_wav
from .overlay import RecordingOverlay
from .theme import palette
from .transcribe import AutoBackend, TranscriptionError, build_backend

log = logging.getLogger("livewhisper")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"


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
        self.root: tk.Tk | None = None
        self._settings = None
        self._overlay: RecordingOverlay | None = None
        self._started_at = 0.0
        self._backend = None
        self._hotkeys: list = []
        self._lock = threading.Lock()

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
            self._backend = build_backend(self.backend_name, self.cfg["transcription"])
            if isinstance(self._backend, AutoBackend):
                self._backend.notify = self.notify
        return self._backend

    def apply_config(self, cfg: dict) -> None:
        """Called by the settings window after a save."""
        self.cfg = cfg
        self._backend = None            # rebuild with the new settings
        self.profile_index = 0
        self._bind_hotkeys()
        if self.icon:
            self.icon.menu = self._menu()
        self._set_state(self.state)
        threading.Thread(target=self._warm_up, daemon=True).start()

    # -------------------------------------------------------------------- ui

    def notify(self, message: str, title: str = "LiveWhisper") -> None:
        log.info("%s: %s", title, message)
        if self.icon:
            try:
                self.icon.notify(message, title)
            except Exception:
                log.debug("tray notification failed", exc_info=True)

    def _colour(self, key: str) -> str:
        c = palette(self.cfg.get("ui", {}).get("theme", "dark-amber"))
        return {"idle": c["muted"], "recording": c["rec"],
                "transcribing": c["accent"]}[key]

    def _set_state(self, state: State) -> None:
        self.state = state
        if self.icon:
            self.icon.icon = icons.tray_image(self._colour(state.colour_key))
            self.icon.title = (f"LiveWhisper - {state.label} "
                               f"({self.profile['name']} / {self.backend_name})")

    # --------------------------------------------------------------- actions

    def toggle_record(self) -> None:
        with self._lock:
            if self.state is State.TRANSCRIBING:
                self.notify("Still transcribing the last recording.")
                return
            self._start() if self.state is State.IDLE else self._stop()

    def _start(self) -> None:
        a = self.cfg["audio"]
        self.recorder = Recorder(
            capture_system=a.get("capture_system", True),
            capture_mic=a.get("capture_mic", True),
            system_gain=float(a.get("system_gain", 1.0)),
            mic_gain=float(a.get("mic_gain", 1.0)),
        )
        try:
            self.recorder.start()
        except AudioError as e:
            self.recorder = None
            self.notify(f"Could not start recording: {e}")
            return
        self._started_at = time.monotonic()
        self._set_state(State.RECORDING)
        if self.cfg.get("ui", {}).get("overlay", True) and self.root:
            self.root.after(0, self._show_overlay)

    def _stop(self) -> None:
        recorder, self.recorder = self.recorder, None
        if self.root:
            self.root.after(0, self._hide_overlay)
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
        if self.cfg["audio"].get("capture_system", True) and recording.system_peak < silent:
            self.notify("Warning: system audio was silent - captured your mic only.")
        elif self.cfg["audio"].get("capture_mic", True) and recording.mic_peak < silent:
            self.notify("Warning: microphone was silent - captured system audio only.")

        self._set_state(State.TRANSCRIBING)
        threading.Thread(target=self._transcribe, args=(recording,), daemon=True).start()

    def cancel(self) -> None:
        with self._lock:
            if self.state is not State.RECORDING:
                return
            recorder, self.recorder = self.recorder, None
            if self.root:
                self.root.after(0, self._hide_overlay)
            if recorder:
                recorder.stop()
            self._set_state(State.IDLE)
            self.notify("Recording discarded.")

    def _transcribe(self, recording) -> None:
        try:
            mins, secs = divmod(int(recording.seconds), 60)
            log.info("transcribing %dm%02ds via %s", mins, secs, self.backend_name)
            transcript = self.backend().transcribe(recording.audio)
            if not transcript:
                self.notify("No speech detected in the recording.")
                return

            text = output.compose(self.profile.get("prompt", ""), transcript)
            self._save(text)

            o = self.cfg["output"]
            pasted, kept = output.deliver(
                text,
                auto_paste=o.get("auto_paste", True),
                copy_to_clipboard=o.get("copy_to_clipboard", True),
                restore_clipboard=o.get("restore_clipboard", False),
            )
            words = len(transcript.split())
            if pasted:
                where = "pasted"
            elif kept:
                where = "copied to clipboard"
            else:
                where = "saved"
            self.notify(f"{words} words {where}.")
        except TranscriptionError as e:
            self.notify(f"Transcription failed: {e}")
            self._save_audio_on_failure(recording)
        except Exception as e:
            log.exception("unexpected failure during transcription")
            self.notify(f"Transcription failed: {e}")
            self._save_audio_on_failure(recording)
        finally:
            self._set_state(State.IDLE)

    def _transcript_dir(self) -> Path:
        d = ROOT / self.cfg["output"].get("transcript_dir", "transcripts")
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

    def _show_overlay(self) -> None:
        u = self.cfg.get("ui", {})
        if self._overlay is None:
            self._overlay = RecordingOverlay(
                self.root,
                on_stop=lambda: threading.Thread(target=self.toggle_record,
                                                 daemon=True).start(),
                on_cancel=lambda: threading.Thread(target=self.cancel,
                                                   daemon=True).start(),
                theme=u.get("theme", "dark-amber"),
                position=u.get("overlay_position"),
                on_move=self._remember_overlay_position,
                show_meter=u.get("overlay_meter", True),
            )
        self._overlay.show_meter = u.get("overlay_meter", True)
        self._overlay.show()
        self._pump_overlay()

    def _pump_overlay(self) -> None:
        if self.state is not State.RECORDING or self._overlay is None:
            return
        level = self.recorder.level() if self.recorder else 0.0
        self._overlay.update(time.monotonic() - self._started_at, level)
        self.root.after(80, self._pump_overlay)

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

    def open_settings(self) -> None:
        if self.root:
            self.root.after(0, self._open_settings)

    def _open_settings(self) -> None:
        from .gui import SettingsWindow

        if self._settings is not None:
            try:
                self._settings.deiconify()
                self._settings.lift()
                self._settings.focus_force()
                return
            except tk.TclError:
                self._settings = None
        self._settings = SettingsWindow(self)

    def settings_closed(self) -> None:
        self._settings = None

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
        return pystray.Menu(
            pystray.MenuItem(lambda item: f"Status: {self.state.label}", None,
                             enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda item: ("Stop and transcribe" if self.state is State.RECORDING
                              else "Start recording"),
                lambda icon, item: threading.Thread(target=self.toggle_record,
                                                    daemon=True).start(),
                default=True),
            pystray.MenuItem("Discard recording",
                             lambda icon, item: threading.Thread(target=self.cancel,
                                                                 daemon=True).start()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Prompt profile", pystray.Menu(*profiles)),
            pystray.MenuItem(lambda item: f"Engine: {self.backend_name}",
                             lambda icon, item: self.toggle_backend()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Settings...", lambda icon, item: self.open_settings()),
            pystray.MenuItem("Open transcripts",
                             lambda icon, item: self.open_transcripts()),
            pystray.MenuItem("Quit", lambda icon, item: self.quit()),
        )

    def _warm_up(self) -> None:
        """Prepare what is ready. Must never trigger a 3 GB download by itself."""
        try:
            self.backend().load()
            log.info("%s backend ready", self.backend_name)
        except Exception as e:
            log.warning("backend warm-up: %s", e)

    def quit(self) -> None:
        self._unbind_hotkeys()
        if self.recorder:
            self.recorder.stop()
        if self.icon:
            self.icon.stop()
        if self.root:
            self.root.after(0, self.root.quit)

    def run(self) -> None:
        icons.set_app_id()  # must precede any window, or the taskbar shows Python
        self.root = tk.Tk()
        self.root.withdraw()  # hidden parent; the tray icon is the real entry point
        self.root.title("LiveWhisper")
        icons.apply(self.root)

        self.icon = pystray.Icon("livewhisper", icons.tray_image(self._colour("idle")),
                                 "LiveWhisper", self._menu())
        self._set_state(State.IDLE)
        self._bind_hotkeys()
        threading.Thread(target=self.icon.run, daemon=True).start()
        threading.Thread(target=self._warm_up, daemon=True).start()

        hk = self.cfg["hotkeys"].get("record", "ctrl+alt+space")
        print(f"LiveWhisper running. Press {hk} to start/stop recording.", flush=True)
        self.root.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Hotkey meeting transcription.")
    parser.add_argument("-c", "--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--settings", action="store_true",
                        help="open the settings window on launch")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # -v is for debugging LiveWhisper, not PIL's plugin scan or httpcore's frames.
    for noisy in ("PIL", "httpx", "httpcore", "urllib3", "filelock", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if not args.config.exists():
        print(f"config not found: {args.config}", file=sys.stderr)
        return 1

    app = App(args.config)
    if args.settings:
        threading.Timer(0.6, app.open_settings).start()
    try:
        app.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
