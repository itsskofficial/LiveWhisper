"""The app window: Home, History, Dictionary, Languages, AI and Settings.

An HTML page (livewhisper/ui/index.html) in the system's WebView2, which every
supported Windows already has, driven through pywebview. The page calls the
methods of `Api` and polls `state()` while it is open; nothing here pushes, so
a closed window costs nothing.

Closing the window hides it - the app keeps running in the tray, where
dictation lives. Quit is in the tray menu and in Settings.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from . import __version__, paths
from . import config as cfgio

log = logging.getLogger(__name__)

TITLE = "LiveWhisper"


def _set(cfg: dict, dotted: str, value) -> None:
    node = cfg
    keys = dotted.split(".")
    for k in keys[:-1]:
        if not isinstance(node.get(k), dict):
            node[k] = {}
        node = node[k]
    node[keys[-1]] = value


def _get(cfg: dict, dotted: str, default=None):
    node = cfg
    for k in dotted.split("."):
        if not isinstance(node, dict) or k not in node:
            return default
        node = node[k]
    return node


# Settings the page may change, with the type each must have. Anything else is
# refused: the page is trusted, but a typo there must not corrupt the config.
SETTINGS = {
    "processing": str,
    "ui.overlay": bool,
    "output.auto_paste": bool,
    "output.copy_to_clipboard": bool,
    "output.restore_clipboard": bool,
    "output.save_transcripts": bool,
    "output.format.enabled": bool,
    "output.format.engine": str,
    "context.bias": bool,
    "learning.enabled": bool,
    "script.default": str,
    "script.language": str,
    "transcription.backend": str,
    "transcription.local.model": str,
    "transcription.local.device": str,
    "transcription.vocabulary": str,
    "actions.models.provider": str,
    "audio.mic_gain": float,
    "hotkeys.record": str,
    "hotkeys.cancel": str,
    "hotkeys.write": str,
    "hotkeys.fix": str,
    "hotkeys.devanagari": str,
    "hotkeys.notes": str,
}


def processing_mode(cfg: dict) -> str:
    """online | local - read back from what the switch sets."""
    mode = _get(cfg, "processing")
    if mode in ("online", "local"):
        return mode
    key_set = os.environ.get(_get(cfg, "transcription.groq.api_key_env", "GROQ_API_KEY"))
    cloud = _get(cfg, "transcription.backend") in ("auto", "groq")
    return "online" if cloud and key_set else "local"


def processing_patch(cfg: dict, mode: str) -> dict:
    """Everything the one Online switch changes.

        online   speech on Groq, falling back to this PC, and staying on this
                 PC for a language whose own model is downloaded (see
                 transcribe.AutoBackend._local_is_better); formatting and
                 writing on Groq, falling back to this PC's models
        local    all three on this PC
    """
    formatting_on = (_get(cfg, "output.format.engine") or "auto") != "rules"
    if mode == "online":
        return {"transcription.backend": "auto",
                "output.format.engine": "groq" if formatting_on else "rules",
                "actions.models.provider": "groq",
                "actions.models.model": None}
    return {"transcription.backend": "local",
            "output.format.engine": "auto" if formatting_on else "rules",
            "actions.models.provider": "auto",
            "actions.models.model": None}


class Api:
    """Everything the page can ask for. Every method returns plain data."""

    def __init__(self, app):
        self._app = app
        self._components = None
        self._teach = None

    # -------------------------------------------------------------- shared

    @property
    def _comps(self):
        if self._components is None:
            from .components import Components
            self._components = Components(self._app)
        return self._components

    def state(self) -> dict:
        app = self._app
        cfg = app.cfg
        from .components import gpu_ready
        comps = self._comps.list()
        essentials = [c for c in comps if c["group"] == "essentials"
                      or (c["id"] == "formatter")]
        return {
            "version": __version__,
            "status": app.state.name.lower(),
            "mode": getattr(app, "_mode", "dictate"),
            "hotkeys": dict(cfg.get("hotkeys") or {}),
            "onboarded": bool(_get(cfg, "ui.onboarded", False)),
            "ready": all(c["installed"] for c in essentials if c["group"] == "essentials"),
            "downloading": [c for c in comps if c["state"] in ("queued", "downloading")],
            "gpu": self._comps.machine.gpu or "",
            "gpu_ready": gpu_ready(),
            "backend": cfg["transcription"].get("backend", "auto"),
            "processing": processing_mode(cfg),
            "stats": app.history.stats(),
            "recent": app.history.entries()[:6],
        }

    # ---------------------------------------------------------- components

    def list_components(self) -> list:
        return self._comps.list()

    def download(self, cid: str) -> None:
        self._comps.list()
        self._comps.start(cid)

    def cancel_download(self, cid: str) -> None:
        self._comps.cancel(cid)

    def download_essentials(self, include_writer: bool = False) -> None:
        for c in self._comps.list():
            if c["installed"]:
                continue
            # English on the turbo model: a third to half the wait after an
            # English dictation, at the same accuracy. The catalogue lists it
            # for GPU machines only, so a CPU machine is never offered it.
            if c["group"] == "essentials" or c["id"] in ("formatter", "lang:en") or \
                    (include_writer and c["id"] == "writer"):
                self._comps.start(c["id"])

    # ------------------------------------------------------------- history

    def history(self, query: str = "", limit: int = 200) -> list:
        q = (query or "").strip().lower()
        items = self._app.history.entries()
        if q:
            items = [e for e in items if q in e.get("text", "").lower()
                     or q in e.get("app", "").lower()]
        return items[:limit]

    def history_delete(self, entry_id: str) -> None:
        self._app.history.delete(entry_id)

    def history_clear(self) -> None:
        self._app.history.clear()

    def copy_text(self, text: str) -> bool:
        from . import output
        try:
            output._copy(text)
            return True
        except Exception:
            log.debug("copy failed", exc_info=True)
            return False

    # ---------------------------------------------------------- dictionary

    def dictionary(self) -> dict:
        from .profile import ProfileStore
        store = self._app.styles
        g = store.get(ProfileStore.GLOBAL).conventions
        vocab = _get(self._app.cfg, "transcription.vocabulary", "") or ""
        words = [w.strip() for w in vocab.replace("\n", ",").split(",") if w.strip()]
        habits = []
        for name, prof in store.profiles.items():
            if name != ProfileStore.GLOBAL and prof.habits.samples:
                h = prof.habits
                habits.append({"app": name, "capitals": round(h.capitalize * 100),
                               "stops": round(h.terminal_period * 100),
                               "samples": h.samples})
        return {"vocabulary": words,
                "spellings": [{"native": k, "spelling": v} for k, v in g.overrides.items()],
                "rules": [{"from": a, "to": b} for a, b in g.rules.items()],
                "habits": habits,
                "learning": bool(_get(self._app.cfg, "learning.enabled", True))}

    def set_vocabulary(self, words: list) -> None:
        clean = []
        for w in words:
            w = str(w).strip()
            if w and w.lower() not in {c.lower() for c in clean}:
                clean.append(w)
        self._save({"transcription.vocabulary": ", ".join(clean)})

    def forget_spelling(self, native: str) -> None:
        from .profile import ProfileStore
        store = self._app.styles
        g = store.get(ProfileStore.GLOBAL).conventions
        g.overrides.pop(native, None)
        store.save()

    def forget_rule(self, source: str) -> None:
        from .profile import ProfileStore
        store = self._app.styles
        g = store.get(ProfileStore.GLOBAL).conventions
        g.rules.pop(source, None)
        store.save()

    def forget_all(self) -> None:
        from .profile import Habits, ProfileStore
        store = self._app.styles
        g = store.get(ProfileStore.GLOBAL).conventions
        g.rules.clear()
        g.overrides.clear()
        g.evidence.clear()
        for prof in store.profiles.values():
            prof.habits = Habits()
        store.save()

    # ------------------------------------------------------------ teaching

    def teach_start(self, lang: str) -> dict:
        from .onboarding import Onboarding
        self._teach = Onboarding(lang)
        prompts = self._teach.prompts()
        return {"lang": self._teach.lang,
                "language": self._teach.language.name,
                "nickname": self._teach.language.nickname,
                "prompts": [{"native": p.devanagari, "gloss": p.gloss} for p in prompts]}

    def teach_finish(self, answers: list) -> dict:
        if self._teach is None:
            return {"learned": [], "preview": []}
        ob = self._teach
        pairs = [(a.get("native", ""), a.get("typed", "")) for a in answers]
        result = ob.process(pairs)
        notes = ob.apply(result, self._app.styles)
        preview = ob.preview(result.conventions)
        self._teach = None
        return {"learned": notes, "skipped": result.skipped, "preview": preview}

    # ----------------------------------------------------------- languages

    def languages(self) -> dict:
        from .script.languages import CODES, LANGUAGES, speaker_languages
        cfg = self._app.cfg
        spoken = speaker_languages(cfg)
        comps = {c["id"]: c for c in self._comps.list()}
        out = [{"code": "en", "name": "English", "native": "English", "nickname": "",
                "selected": True, "fixed": True,
                "models": [comps[k] for k in ("lang:en",) if k in comps]}]
        for code in CODES:
            lang = LANGUAGES[code]
            out.append({
                "code": code, "name": lang.name, "native": lang.endonym,
                "nickname": lang.nickname, "selected": code in spoken,
                "models": [c for k, c in comps.items()
                           if k == f"lang:{code}" or k == f"lang:{code}:native"],
            })
        return {"languages": out, "script": _get(cfg, "script.default", "latin")}

    def set_languages(self, codes: list) -> None:
        from .script.languages import supported
        picked = [c for c in codes if c != "en" and supported(c)]
        patch = {"transcription.languages": (picked + ["en"]) if picked else None,
                 "script.language": picked[0] if len(picked) == 1 else "auto"}
        self._save(patch)

    # ------------------------------------------------------------ settings

    def settings(self) -> dict:
        cfg = self._app.cfg
        out = {k: _get(cfg, k) for k in SETTINGS}
        out["processing"] = processing_mode(cfg)
        from . import startup
        out["startup"] = startup.is_enabled()
        env = _get(cfg, "transcription.groq.api_key_env", "GROQ_API_KEY")
        out["groq_key_set"] = bool(os.environ.get(env))
        from . import hardware, llm
        m = hardware.detect()
        out["machine"] = {"gpu": m.gpu or "", "vram_gb": round((m.vram_mb or 0) / 1024),
                          "cpus": m.cpus, "llm_device": llm.pick_device()[1]}
        out["paths"] = {"data": str(paths.HOME), "models": str(paths.CACHE)}
        return out

    def save_setting(self, key: str, value) -> dict:
        if key == "startup":
            from . import startup
            try:
                startup.set_enabled(bool(value))
            except OSError as e:
                return {"ok": False, "error": str(e)}
            return {"ok": True}
        return self._save({key: value})

    def set_groq_key(self, key: str) -> dict:
        key = (key or "").strip()
        env = _get(self._app.cfg, "transcription.groq.api_key_env", "GROQ_API_KEY")
        cfgio.write_env(paths.ENV, env, key)
        if key:
            os.environ[env] = key
        else:
            os.environ.pop(env, None)
        self._app.apply_config(self._app.cfg)
        return {"ok": True}

    def finish_onboarding(self) -> None:
        self._save({"ui.onboarded": True})

    def _save(self, patch: dict) -> dict:
        cfg = self._app.cfg
        if "processing" in patch:
            patch = {**patch, **processing_patch(cfg, patch["processing"])}
        for key, value in patch.items():
            want = SETTINGS.get(key)
            if want is not None and value is not None and not isinstance(value, want):
                try:
                    value = want(value)
                except (TypeError, ValueError):
                    return {"ok": False, "error": f"bad value for {key}"}
            _set(cfg, key, value)
        try:
            cfgio.save(self._app.config_path, cfg)
        except Exception as e:
            log.exception("could not save settings")
            return {"ok": False, "error": str(e)}
        self._app.apply_config(cfg)
        return {"ok": True}

    # --------------------------------------------------------------- misc

    def open_path(self, what: str) -> None:
        from .logs import log_path
        target = {"log": log_path(), "data": paths.HOME, "models": paths.CACHE,
                  "transcripts": self._app._transcript_dir()}.get(what)
        if target is not None and Path(target).exists():
            os.startfile(str(target))                      # noqa: S606

    def open_url(self, url: str) -> None:
        if url.startswith("https://"):
            import webbrowser
            webbrowser.open(url)

    def js_error(self, message: str) -> None:
        """The page reports its own errors here, so they reach the log."""
        log.warning("window: %s", str(message)[:500])

    def pause_hotkeys(self, paused: bool) -> None:
        """While a new shortcut is being recorded, the old ones must not fire."""
        if paused:
            self._app._unbind_hotkeys()
        else:
            self._app._bind_hotkeys()

    def hide(self) -> None:
        self._app.window.hide()

    def quit(self) -> None:
        threading.Thread(target=self._app.quit, daemon=True).start()


class AppWindow:
    """The one window, created hidden at start-up and shown on demand."""

    def __init__(self, app):
        import webview
        self.app = app
        self.api = Api(app)
        self._shown = False
        self.window = webview.create_window(
            # Passed as a string: loaded from a file path, the page renders but
            # pywebview's bridge is never injected and every call is lost. The
            # page is self-contained, so nothing else needs serving.
            TITLE, html=(paths.UI / "index.html").read_text(encoding="utf-8"),
            js_api=self.api,
            width=1080, height=720, min_size=(860, 560), hidden=True,
            background_color="#F7F7F5", text_select=True)
        self.window.events.closing += self._closing
        self._quitting = False

    def _closing(self):
        if self._quitting:
            return True
        self.hide()
        ui = self.app.cfg.setdefault("ui", {})
        if not ui.get("tray_hint_shown"):
            # Closing looks like quitting; say once that it is still there.
            key = self.app.cfg.get("hotkeys", {}).get("record", "ctrl+alt+space")
            self.app.notify(f"Still running in the tray - {key.title()} to dictate")
            ui["tray_hint_shown"] = True
            try:
                cfgio.save(self.app.config_path, self.app.cfg)
            except Exception:
                log.debug("could not save the tray hint flag", exc_info=True)
        return False                      # keep running in the tray

    def show(self, page: str | None = None) -> None:
        try:
            if page:
                self.window.evaluate_js(f"window.lw && window.lw.go({page!r})")
            self.window.show()
            self.window.restore()
            self._front()
        except Exception:
            log.debug("could not show the window", exc_info=True)

    def _front(self) -> None:
        try:
            import ctypes
            hwnd = ctypes.windll.user32.FindWindowW(None, TITLE)
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 9)          # SW_RESTORE
                ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def hide(self) -> None:
        try:
            self.window.hide()
        except Exception:
            log.debug("could not hide the window", exc_info=True)

    def destroy(self) -> None:
        self._quitting = True
        try:
            self.window.destroy()
        except Exception:
            pass
