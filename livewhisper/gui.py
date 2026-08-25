"""Settings window: sidebar navigation with a content panel on the right.

Owned by the Tk main thread. The tray menu marshals here via root.after().
"""

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from pathlib import Path

import customtkinter as ctk

from . import config as cfgio
from . import hardware, icons, startup
from .theme import appearance_mode, palette

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SECTIONS = ["Prompts", "Writing", "Engine", "Audio", "Hotkeys", "General"]

MODELS = ["large-v3", "large-v3-turbo", "medium", "small", "base", "tiny"]
COMPUTE = ["int8_float16", "float16", "int8", "float32"]


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.cfg = app.cfg
        self.c = palette(self.cfg.get("ui", {}).get("theme", "dark-amber"))
        ctk.set_appearance_mode(appearance_mode(self.cfg.get("ui", {}).get("theme")))

        self.title("LiveWhisper")
        self.minsize(780, 480)
        self.configure(fg_color=self.c["bg"])
        self._size_to_screen()

        self._vars: dict = {}
        self._profiles = [dict(p) for p in self.cfg.get("profiles", [])]
        self._selected = 0
        self._panels: dict = {}

        self._build()
        self._show("Prompts")
        self.protocol("WM_DELETE_WINDOW", self._close)
        # customtkinter recreates the window handle just after __init__, which
        # discards an icon set now - hence the delay.
        self.after(250, lambda: icons.apply(self))
        self.after(120, self.lift)

    def _size_to_screen(self) -> None:
        """Fit and centre the window.

        customtkinter multiplies geometry by the display's DPI scaling, so a
        fixed height silently pushes the Save bar off the bottom of a scaled
        screen. Clamp against the real screen size instead.
        """
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        try:
            scale = ctk.ScalingTracker.get_window_scaling(self)
        except Exception:
            scale = 1.0
        w = min(880, int((sw - 80) / scale))
        h = min(640, int((sh - 120) / scale))
        x = int((sw - w * scale) / 2)
        y = int((sh - h * scale) / 2)
        self.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")

    # ------------------------------------------------------------------ shell

    def _build(self) -> None:
        c = self.c
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        rail = ctk.CTkFrame(self, fg_color=c["surface"], corner_radius=0, width=190)
        rail.grid(row=0, column=0, rowspan=2, sticky="nsew")
        rail.grid_propagate(False)

        ctk.CTkLabel(rail, text="  LiveWhisper", font=("Segoe UI", 17, "bold"),
                     text_color=c["accent"]).pack(pady=(22, 26), anchor="w", padx=14)

        self._nav = {}
        for name in SECTIONS:
            b = ctk.CTkButton(
                rail, text=name, anchor="w", height=38, corner_radius=8,
                fg_color="transparent", text_color=c["muted"],
                hover_color=c["surface_hi"], font=("Segoe UI", 13),
                command=lambda n=name: self._show(n),
            )
            b.pack(fill="x", padx=10, pady=2)
            self._nav[name] = b

        # Live engine status, so the sidebar always answers "what will run?"
        self._status = ctk.CTkLabel(rail, text="", justify="left", anchor="w",
                                    font=("Segoe UI", 11), text_color=c["muted"])
        self._status.pack(side="bottom", fill="x", padx=16, pady=16)

        self._body = ctk.CTkFrame(self, fg_color=c["bg"], corner_radius=0)
        self._body.grid(row=0, column=1, sticky="nsew", padx=(0, 0))
        self._body.grid_columnconfigure(0, weight=1)
        self._body.grid_rowconfigure(0, weight=1)

        bar = ctk.CTkFrame(self, fg_color=c["bg"], corner_radius=0, height=62)
        bar.grid(row=1, column=1, sticky="ew")
        self._saved = ctk.CTkLabel(bar, text="", text_color=c["ok"],
                                   font=("Segoe UI", 12))
        self._saved.pack(side="left", padx=22)
        ctk.CTkButton(bar, text="Save", width=110, height=36, corner_radius=8,
                      fg_color=c["accent"], hover_color=c["accent_hi"],
                      text_color=c["accent_text"], font=("Segoe UI", 13, "bold"),
                      command=self._save).pack(side="right", padx=22, pady=12)

        for name in SECTIONS:
            panel = ctk.CTkScrollableFrame(self._body, fg_color=c["bg"],
                                           scrollbar_button_color=c["border"])
            panel.grid(row=0, column=0, sticky="nsew", padx=18, pady=8)
            panel.grid_columnconfigure(0, weight=1)
            self._panels[name] = panel
            getattr(self, f"_build_{name.lower()}")(panel)

        self._refresh_status()

    def _show(self, name: str) -> None:
        for n, b in self._nav.items():
            active = n == name
            b.configure(fg_color=self.c["surface_hi"] if active else "transparent",
                        text_color=self.c["accent"] if active else self.c["muted"])
        for n, p in self._panels.items():
            p.grid() if n == name else p.grid_remove()

    # ----------------------------------------------------------- small pieces

    def _heading(self, parent, text, sub=None):
        ctk.CTkLabel(parent, text=text, font=("Segoe UI", 20, "bold"),
                     text_color=self.c["text"], anchor="w").pack(
            fill="x", pady=(14, 2))
        if sub:
            ctk.CTkLabel(parent, text=sub, font=("Segoe UI", 12),
                         text_color=self.c["muted"], anchor="w",
                         justify="left", wraplength=560).pack(fill="x", pady=(0, 14))
        else:
            ctk.CTkLabel(parent, text="").pack(pady=2)

    def _card(self, parent):
        f = ctk.CTkFrame(parent, fg_color=self.c["surface"], corner_radius=10)
        f.pack(fill="x", pady=6)
        return f

    def _row(self, card, label, hint=None):
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(10, 10))
        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(left, text=label, font=("Segoe UI", 13),
                     text_color=self.c["text"], anchor="w").pack(fill="x")
        if hint:
            ctk.CTkLabel(left, text=hint, font=("Segoe UI", 11),
                         text_color=self.c["muted"], anchor="w", justify="left",
                         wraplength=430).pack(fill="x")
        return row

    def _switch(self, card, label, key, value, hint=None):
        row = self._row(card, label, hint)
        var = tk.BooleanVar(value=bool(value))
        self._vars[key] = var
        ctk.CTkSwitch(row, text="", variable=var, width=46,
                      progress_color=self.c["accent"],
                      button_color=self.c["text"]).pack(side="right")

    def _entry(self, card, label, key, value, hint=None, width=230, show=None):
        row = self._row(card, label, hint)
        var = tk.StringVar(value="" if value is None else str(value))
        self._vars[key] = var
        e = ctk.CTkEntry(row, textvariable=var, width=width, height=34,
                         fg_color=self.c["bg"], border_color=self.c["border"],
                         text_color=self.c["text"], show=show)
        e.pack(side="right")
        return e

    def _menu(self, card, label, key, value, options, hint=None, width=180):
        row = self._row(card, label, hint)
        var = tk.StringVar(value=str(value))
        self._vars[key] = var
        ctk.CTkOptionMenu(row, variable=var, values=options, width=width, height=34,
                          fg_color=self.c["bg"], button_color=self.c["border"],
                          button_hover_color=self.c["surface_hi"],
                          text_color=self.c["text"],
                          dropdown_fg_color=self.c["surface"],
                          dropdown_text_color=self.c["text"]).pack(side="right")

    # -------------------------------------------------------------- Prompts

    def _build_prompts(self, p) -> None:
        self._heading(p, "Prompt Profiles",
                      "The active profile's prompt is prepended to the transcript "
                      "before it is pasted. Ctrl+Alt+P cycles between them.")
        wrap = ctk.CTkFrame(p, fg_color="transparent")
        wrap.pack(fill="both", expand=True)

        left = ctk.CTkFrame(wrap, fg_color=self.c["surface"], corner_radius=10, width=210)
        left.pack(side="left", fill="y", padx=(0, 12))
        left.pack_propagate(False)

        self._plist = ctk.CTkScrollableFrame(left, fg_color="transparent", width=190)
        self._plist.pack(fill="both", expand=True, padx=6, pady=6)

        btns = ctk.CTkFrame(left, fg_color="transparent")
        btns.pack(fill="x", padx=6, pady=(0, 8))
        ctk.CTkButton(btns, text="+ Add", height=32, corner_radius=8,
                      fg_color=self.c["surface_hi"], hover_color=self.c["border"],
                      text_color=self.c["text"],
                      command=self._add_profile).pack(side="left", expand=True,
                                                      fill="x", padx=2)
        ctk.CTkButton(btns, text="Delete", height=32, corner_radius=8,
                      fg_color="transparent", hover_color=self.c["rec"],
                      text_color=self.c["muted"],
                      command=self._del_profile).pack(side="left", expand=True,
                                                      fill="x", padx=2)

        right = ctk.CTkFrame(wrap, fg_color=self.c["surface"], corner_radius=10)
        right.pack(side="left", fill="both", expand=True)

        ctk.CTkLabel(right, text="Name", font=("Segoe UI", 12),
                     text_color=self.c["muted"], anchor="w").pack(
            fill="x", padx=16, pady=(14, 2))
        self._pname = ctk.CTkEntry(right, height=34, fg_color=self.c["bg"],
                                   border_color=self.c["border"],
                                   text_color=self.c["text"])
        self._pname.pack(fill="x", padx=16)
        self._pname.bind("<KeyRelease>", lambda e: self._stash())

        ctk.CTkLabel(right, text="Prompt", font=("Segoe UI", 12),
                     text_color=self.c["muted"], anchor="w").pack(
            fill="x", padx=16, pady=(14, 2))
        self._ptext = ctk.CTkTextbox(right, fg_color=self.c["bg"],
                                     border_color=self.c["border"], border_width=1,
                                     text_color=self.c["text"],
                                     font=("Consolas", 12), wrap="word")
        self._ptext.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self._ptext.bind("<KeyRelease>", lambda e: self._stash())

        self._render_profiles()

    def _render_profiles(self) -> None:
        for w in self._plist.winfo_children():
            w.destroy()
        for i, prof in enumerate(self._profiles):
            active = i == self._selected
            ctk.CTkButton(
                self._plist, text=prof.get("name", "?"), anchor="w", height=34,
                corner_radius=6,
                fg_color=self.c["surface_hi"] if active else "transparent",
                text_color=self.c["accent"] if active else self.c["text"],
                hover_color=self.c["border"],
                command=lambda i=i: self._select_profile(i),
            ).pack(fill="x", pady=1)
        self._load_profile()

    def _select_profile(self, i: int) -> None:
        self._stash()
        self._selected = i
        self._render_profiles()

    def _load_profile(self) -> None:
        if not self._profiles:
            return
        prof = self._profiles[min(self._selected, len(self._profiles) - 1)]
        self._pname.delete(0, "end")
        self._pname.insert(0, prof.get("name", ""))
        self._ptext.delete("1.0", "end")
        self._ptext.insert("1.0", prof.get("prompt", "") or "")

    def _stash(self) -> None:
        """Copy the editor back into the in-memory profile as you type."""
        if not self._profiles:
            return
        i = min(self._selected, len(self._profiles) - 1)
        self._profiles[i]["name"] = self._pname.get().strip() or "Untitled"
        self._profiles[i]["prompt"] = self._ptext.get("1.0", "end-1c")

    def _add_profile(self) -> None:
        self._stash()
        self._profiles.append({"name": "New profile", "prompt": ""})
        self._selected = len(self._profiles) - 1
        self._render_profiles()

    def _del_profile(self) -> None:
        if len(self._profiles) <= 1:
            self._flash("Keep at least one profile.", self.c["rec"])
            return
        self._profiles.pop(self._selected)
        self._selected = max(0, self._selected - 1)
        self._render_profiles()


    # -------------------------------------------------------------- Writing

    def _build_writing(self, p) -> None:
        t = self.cfg.get("script", {}) or {}
        self._heading(p, "Writing style",
                      "Hindi and Marathi are transcribed in Devanagari, but "
                      "almost nobody types Devanagari in chat. LiveWhisper "
                      "converts it to the Latin spelling you actually use, and "
                      "learns that spelling from your corrections.")

        card = self._card(p)
        self._menu(card, "Default script", "script.default",
                   t.get("default", "latin"), ["latin", "devanagari"],
                   "Latin = kya kar rahe ho. Devanagari = the original script. "
                   "This is overridden when the field you are typing in already "
                   "contains one or the other.")
        self._menu(card, "Language", "script.language", t.get("language", "hi"),
                   ["hi", "mr"],
                   "hi = Hindi, mr = Marathi. Both use Devanagari, so this "
                   "selects which spelling dictionary to load.")

        ctk.CTkLabel(p, text="What it has learned about you",
                     font=("Segoe UI", 15, "bold"), text_color=self.c["text"],
                     anchor="w").pack(fill="x", pady=(18, 4))
        card = self._card(p)

        box = ctk.CTkFrame(card, fg_color=self.c["bg"], corner_radius=8)
        box.pack(fill="x", padx=16, pady=14)
        self._learned = ctk.CTkTextbox(box, height=150, fg_color=self.c["bg"],
                                       border_width=0, text_color=self.c["text"],
                                       wrap="word", font=("Consolas", 12))
        self._learned.pack(fill="x", padx=10, pady=10)
        self._refresh_learned()

        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkButton(row, text="Teach it how you write", height=34,
                      corner_radius=8, fg_color=self.c["accent"],
                      hover_color=self.c["accent_hi"],
                      text_color=self.c["accent_text"],
                      command=self._run_wizard).pack(side="left")
        ctk.CTkButton(row, text="Refresh", width=90, height=34, corner_radius=8,
                      fg_color=self.c["surface_hi"], hover_color=self.c["border"],
                      text_color=self.c["text"],
                      command=self._refresh_learned).pack(side="left", padx=8)
        ctk.CTkButton(row, text="Forget everything", width=150, height=34,
                      corner_radius=8, fg_color="transparent",
                      hover_color=self.c["rec"], text_color=self.c["muted"],
                      command=self._forget).pack(side="right")

        card = self._card(p)
        self._switch(card, "Learn from my corrections", "learning.enabled",
                     (self.cfg.get("learning") or {}).get("enabled", True),
                     "When you edit what was pasted, the change is read back at "
                     "the start of your next dictation. Nothing runs in the "
                     "background and keystrokes are never recorded.")

    def _refresh_learned(self) -> None:
        from .profile import ProfileStore
        store = self.app.styles
        g = store.get(ProfileStore.GLOBAL).conventions
        lines = []
        if g.rules:
            lines.append("Spelling conventions (applied to every word):")
            for a, b in g.rules.items():
                lines.append("   " + a + " -> " + b)
        else:
            lines.append("No spelling conventions learned yet.")
        if g.overrides:
            lines.append("")
            lines.append("Exact words remembered: " + str(len(g.overrides)))
            for w, v in list(g.overrides.items())[:8]:
                lines.append("   " + w + " -> " + v)
            if len(g.overrides) > 8:
                lines.append("   ... and " + str(len(g.overrides) - 8) + " more")

        apps = [(k, v) for k, v in store.profiles.items()
                if k != ProfileStore.GLOBAL and v.habits.samples]
        if apps:
            lines.append("")
            lines.append("Per-app habits:")
            for name, prof in apps:
                h = prof.habits
                lines.append(f"   {name}: capitals {h.capitalize:.0%}, "
                             f"full stops {h.terminal_period:.0%} "
                             f"({h.samples} samples)")
        self._learned.configure(state="normal")
        self._learned.delete("1.0", "end")
        self._learned.insert("1.0", "\n".join(lines))
        self._learned.configure(state="disabled")

    def _run_wizard(self) -> None:
        self.app.open_wizard()
        self.after(1500, self._refresh_learned)

    def _forget(self) -> None:
        from .profile import Habits, ProfileStore
        store = self.app.styles
        g = store.get(ProfileStore.GLOBAL).conventions
        g.rules.clear()
        g.overrides.clear()
        g.evidence.clear()
        for prof in store.profiles.values():
            prof.habits = Habits()
        store.save()
        self._refresh_learned()
        self._flash("Forgot everything it had learned.", self.c["rec"])

    # --------------------------------------------------------------- Engine

    def _build_engine(self, p) -> None:
        t = self.cfg["transcription"]
        self._heading(p, "Engine",
                      "auto sends to Groq first and falls back to the local model "
                      "when Groq is out of credit, rate-limited or unreachable.")

        card = self._card(p)
        self._menu(card, "Backend", "transcription.backend", t.get("backend", "auto"),
                   ["auto", "groq", "local"],
                   "auto = Groq, then local. groq = cloud only. local = nothing leaves this PC.")
        self._entry(card, "Fallback cooldown (minutes)",
                    "transcription.fallback_cooldown_minutes",
                    t.get("fallback_cooldown_minutes", 60),
                    "After Groq refuses, skip it for this long instead of retrying "
                    "and stalling every recording.", width=90)

        # --- Groq ---
        ctk.CTkLabel(p, text="Groq", font=("Segoe UI", 15, "bold"),
                     text_color=self.c["text"], anchor="w").pack(fill="x", pady=(18, 4))
        card = self._card(p)
        key_env = t.get("groq", {}).get("api_key_env", "GROQ_API_KEY")
        self._keyentry = self._entry(
            card, "API key", "_groq_key", os.environ.get(key_env, ""),
            "Free tier at console.groq.com. Saved to the .env file beside the app.",
            width=280, show="*")
        row = self._row(card, "")
        self._showkey = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(row, text="Show key", variable=self._showkey,
                        font=("Segoe UI", 11), text_color=self.c["muted"],
                        fg_color=self.c["accent"], hover_color=self.c["accent_hi"],
                        checkbox_width=18, checkbox_height=18,
                        command=lambda: self._keyentry.configure(
                            show="" if self._showkey.get() else "*")).pack(side="right")
        self._menu(card, "Groq model", "transcription.groq.model",
                   t.get("groq", {}).get("model", "whisper-large-v3"),
                   ["whisper-large-v3", "whisper-large-v3-turbo"])
        self._entry(card, "Groq language", "transcription.groq.language",
                    t.get("groq", {}).get("language") or "",
                    "Blank = auto-detect. For Hindi/English meetings set 'en': "
                    "Groq otherwise transliterates English into Devanagari. "
                    "The local engine handles code-switching correctly either way.",
                    width=90)

        # --- Local ---
        ctk.CTkLabel(p, text="Local model", font=("Segoe UI", 15, "bold"),
                     text_color=self.c["text"], anchor="w").pack(fill="x", pady=(18, 4))

        rec = hardware.recommend()
        m = hardware.detect()
        detected = (f"Detected: {m.gpu or 'no CUDA GPU'}"
                    + (f" · {round(m.vram_mb/1024)} GB VRAM" if m.vram_mb else "")
                    + f" · {m.cpus} cores")
        card = self._card(p)
        box = ctk.CTkFrame(card, fg_color=self.c["bg"], corner_radius=8)
        box.pack(fill="x", padx=16, pady=14)
        ctk.CTkLabel(box, text=detected, font=("Segoe UI", 12, "bold"),
                     text_color=self.c["accent"], anchor="w").pack(
            fill="x", padx=14, pady=(12, 2))
        ctk.CTkLabel(box, text=f"{rec.reason}\nExpect {rec.speed}.",
                     font=("Segoe UI", 11), text_color=self.c["muted"], anchor="w",
                     justify="left", wraplength=500).pack(fill="x", padx=14, pady=(0, 8))
        ctk.CTkButton(box, text=f"Use recommended  ({rec.model} · {rec.compute_type} "
                                f"· batch {rec.batch_size})",
                      height=32, corner_radius=8, font=("Segoe UI", 12),
                      fg_color=self.c["surface_hi"], hover_color=self.c["border"],
                      text_color=self.c["text"],
                      command=self._apply_recommended).pack(padx=14, pady=(0, 12),
                                                            anchor="w")

        loc = t.get("local", {})
        self._menu(card, "Model", "transcription.local.model",
                   loc.get("model", "large-v3"), MODELS)
        self._menu(card, "Device", "transcription.local.device",
                   loc.get("device", "cuda"), ["cuda", "cpu"], width=120)
        self._menu(card, "Precision", "transcription.local.compute_type",
                   loc.get("compute_type", "int8_float16"), COMPUTE)
        self._entry(card, "Batch size", "transcription.local.batch_size",
                    loc.get("batch_size", 8),
                    "Higher decodes long meetings faster and uses more VRAM. "
                    "1 disables batching.", width=90)
        self._entry(card, "Language", "transcription.local.language",
                    loc.get("language") or "",
                    "Blank = auto-detect across 99 languages. Or force en, hi, mr...",
                    width=90)

        self._dlrow = self._row(card, "Model files", self._model_status_text())
        self._dlbtn = ctk.CTkButton(self._dlrow, text="Download", width=120, height=32,
                                    corner_radius=8, fg_color=self.c["surface_hi"],
                                    hover_color=self.c["border"],
                                    text_color=self.c["text"],
                                    command=self._download_model)
        self._dlbtn.pack(side="right")
        self._sync_download_button()

        ctk.CTkLabel(p, text="Writing assistant", font=("Segoe UI", 15, "bold"),
                     text_color=self.c["text"], anchor="w").pack(fill="x", pady=(18, 4))
        a = self.cfg.get("actions", {}) or {}
        m = a.get("models", {}) or {}
        card = self._card(p)
        self._menu(card, "Provider", "actions.models.provider",
                   m.get("provider", "ollama"),
                   ["ollama", "groq", "openai", "anthropic"],
                   "Used by the write and fix hotkeys. Ollama runs on your "
                   "machine and nothing leaves it. Local models are fine for "
                   "grammar and short rewrites; for longer writing a cloud "
                   "model is noticeably better.")
        self._entry(card, "Model", "actions.models.model",
                    m.get("model", "qwen2.5:7b"), width=200)
        self._entry(card, "Command listens for (seconds)",
                    "actions.command_seconds", a.get("command_seconds", 8),
                    width=70)
        self._switch(card, "Screenshot fallback for reading the screen",
                     "context.ocr_fallback",
                     (self.cfg.get("context") or {}).get("ocr_fallback", False),
                     "Some Chrome and Electron apps hide their text from the "
                     "accessibility layer. This reads the screen as an image "
                     "instead. Needs: pip install rapidocr_onnxruntime")

        ctk.CTkLabel(p, text="Vocabulary", font=("Segoe UI", 15, "bold"),
                     text_color=self.c["text"], anchor="w").pack(fill="x", pady=(18, 4))
        card = self._card(p)
        ctk.CTkLabel(card, text="Names, acronyms and jargon the model keeps "
                               "mishearing. This is the single most effective "
                               "accuracy fix for recurring meetings.",
                     font=("Segoe UI", 11), text_color=self.c["muted"],
                     anchor="w", justify="left", wraplength=560).pack(
            fill="x", padx=16, pady=(12, 6))
        self._vocab = ctk.CTkTextbox(card, height=70, fg_color=self.c["bg"],
                                     border_color=self.c["border"], border_width=1,
                                     text_color=self.c["text"], wrap="word",
                                     font=("Consolas", 12))
        self._vocab.pack(fill="x", padx=16, pady=(0, 14))
        self._vocab.insert("1.0", t.get("vocabulary", "") or "")

    def _model_status_text(self) -> str:
        from .transcribe import LocalBackend
        loc = dict(self.cfg["transcription"].get("local", {}))
        loc["model"] = self._vars.get("transcription.local.model",
                                      tk.StringVar(value=loc.get("model", "large-v3"))).get()
        return ("Downloaded and ready." if LocalBackend(loc).is_downloaded()
                else "Not downloaded (~3 GB). Fetched automatically on first use.")

    def _sync_download_button(self) -> None:
        from .transcribe import LocalBackend
        loc = dict(self.cfg["transcription"].get("local", {}))
        loc["model"] = self._vars["transcription.local.model"].get()
        ready = LocalBackend(loc).is_downloaded()
        self._dlbtn.configure(text="Re-download" if ready else "Download")

    def _download_model(self) -> None:
        from .transcribe import LocalBackend
        loc = dict(self.cfg["transcription"].get("local", {}))
        loc["model"] = self._vars["transcription.local.model"].get()
        self._dlbtn.configure(state="disabled", text="Downloading...")

        def work():
            try:
                LocalBackend(loc).download()
                self.after(0, lambda: self._flash(f"{loc['model']} downloaded.",
                                                  self.c["ok"]))
            except Exception as e:
                self.after(0, lambda: self._flash(f"Download failed: {e}", self.c["rec"]))
            finally:
                self.after(0, lambda: self._dlbtn.configure(state="normal"))
                self.after(0, self._sync_download_button)

        threading.Thread(target=work, daemon=True).start()

    def _apply_recommended(self) -> None:
        rec = hardware.recommend()
        self._vars["transcription.local.model"].set(rec.model)
        self._vars["transcription.local.device"].set(rec.device)
        self._vars["transcription.local.compute_type"].set(rec.compute_type)
        self._vars["transcription.local.batch_size"].set(str(rec.batch_size))
        self._sync_download_button()
        self._flash(f"Applied: {rec.model} · {rec.compute_type} · batch {rec.batch_size}",
                    self.c["ok"])

    # ---------------------------------------------------------------- Audio

    def _build_audio(self, p) -> None:
        a = self.cfg["audio"]
        self._heading(p, "Audio",
                      "System audio is captured through WASAPI loopback, so no "
                      "virtual cable is needed and your speakers keep working.")
        card = self._card(p)
        self._switch(card, "Capture system audio", "audio.capture_system",
                     a.get("capture_system", True),
                     "What the other participants say.")
        self._switch(card, "Capture microphone", "audio.capture_mic",
                     a.get("capture_mic", True), "What you say.")
        card = self._card(p)
        self._entry(card, "System gain", "audio.system_gain",
                    a.get("system_gain", 1.0), width=90)
        self._entry(card, "Mic gain", "audio.mic_gain", a.get("mic_gain", 1.0),
                    "Lower this if you use speakers and your mic echoes the call back.",
                    width=90)

    # -------------------------------------------------------------- Hotkeys

    def _build_hotkeys(self, p) -> None:
        h = self.cfg["hotkeys"]
        self._heading(p, "Hotkeys",
                      "Combinations like ctrl+alt+space, ctrl+shift+;, f9. "
                      "Changes apply on save without restarting.")
        card = self._card(p)
        self._entry(card, "Start / stop recording", "hotkeys.record",
                    h.get("record", "ctrl+alt+space"))
        self._entry(card, "Discard recording", "hotkeys.cancel",
                    h.get("cancel", "ctrl+alt+x"))
        self._entry(card, "Next prompt profile", "hotkeys.cycle_profile",
                    h.get("cycle_profile", "ctrl+alt+p"))
        self._entry(card, "Switch engine", "hotkeys.toggle_backend",
                    h.get("toggle_backend", "ctrl+alt+g"))
        card = self._card(p)
        self._entry(card, "Write this for me", "hotkeys.write",
                    h.get("write", "ctrl+alt+w"),
                    "Speak an instruction. Reads what is on screen for context.")
        self._entry(card, "Fix grammar", "hotkeys.fix", h.get("fix", "ctrl+alt+f"),
                    "Corrects the text in the field you are in, keeping your "
                    "lowercase, slang and Hinglish spellings.")
        self._entry(card, "Notes mode", "hotkeys.notes",
                    h.get("notes", "ctrl+alt+n"),
                    "Transcripts append to a note file instead of pasting.")
        self._entry(card, "Keep next dictation in Devanagari",
                    "hotkeys.devanagari", h.get("devanagari", "ctrl+alt+h"))

    # -------------------------------------------------------------- General

    def _build_general(self, p) -> None:
        o = self.cfg["output"]
        u = self.cfg.get("ui", {})
        self._heading(p, "General")

        ctk.CTkLabel(p, text="While recording", font=("Segoe UI", 15, "bold"),
                     text_color=self.c["text"], anchor="w").pack(fill="x", pady=(6, 4))
        card = self._card(p)
        self._switch(card, "Show floating pill", "ui.overlay", u.get("overlay", True),
                     "Elapsed time and a live level meter. Click the square to stop, "
                     "the x to discard. Drag to reposition.")
        self._switch(card, "Show level meter", "ui.overlay_meter",
                     u.get("overlay_meter", True),
                     "A flat meter means the meeting audio is not reaching you.")

        ctk.CTkLabel(p, text="Output", font=("Segoe UI", 15, "bold"),
                     text_color=self.c["text"], anchor="w").pack(fill="x", pady=(18, 4))
        card = self._card(p)
        self._switch(card, "Copy to clipboard", "output.copy_to_clipboard",
                     o.get("copy_to_clipboard", True))
        self._switch(card, "Paste automatically", "output.auto_paste",
                     o.get("auto_paste", True),
                     "Sends Ctrl+V to whatever field has focus.")
        self._switch(card, "Restore previous clipboard", "output.restore_clipboard",
                     o.get("restore_clipboard", False),
                     "Off is safer: the transcript stays on the clipboard so a "
                     "failed paste is recoverable with a manual Ctrl+V.")
        self._switch(card, "Save transcripts to disk", "output.save_transcripts",
                     o.get("save_transcripts", True))
        row = self._row(card, "Transcripts folder", str(ROOT / o.get("transcript_dir",
                                                                    "transcripts")))
        ctk.CTkButton(row, text="Open", width=90, height=32, corner_radius=8,
                      fg_color=self.c["surface_hi"], hover_color=self.c["border"],
                      text_color=self.c["text"],
                      command=self.app.open_transcripts).pack(side="right")

        ctk.CTkLabel(p, text="Application", font=("Segoe UI", 15, "bold"),
                     text_color=self.c["text"], anchor="w").pack(fill="x", pady=(18, 4))
        card = self._card(p)
        self._menu(card, "Theme", "ui.theme", u.get("theme", "dark-amber"),
                   ["dark-amber", "dark-indigo", "system"],
                   "Takes effect next launch.")
        self._switch(card, "Start when I sign in", "_startup", startup.is_enabled(),
                     "Runs in the background from sign-in, ready for the hotkey.")

    # ----------------------------------------------------------------- save

    def _flash(self, msg: str, colour: str) -> None:
        self._saved.configure(text=msg, text_color=colour)
        self.after(4000, lambda: self._saved.configure(text=""))

    def _refresh_status(self) -> None:
        mode = self._vars.get("transcription.backend")
        mode = mode.get() if mode else self.cfg["transcription"].get("backend", "auto")
        key = bool(os.environ.get(
            self.cfg["transcription"].get("groq", {}).get("api_key_env", "GROQ_API_KEY")))
        lines = [f"Engine: {mode}"]
        if mode in ("auto", "groq"):
            lines.append("Groq key: " + ("set" if key else "missing"))
        self._status.configure(text="\n".join(lines))

    def _get(self, key, cast=str, default=None):
        var = self._vars.get(key)
        if var is None:
            return default
        raw = var.get()
        if cast is bool:
            return bool(raw)
        if raw == "":
            return default
        try:
            return cast(raw)
        except (TypeError, ValueError):
            return default

    def _save(self) -> None:
        self._stash()
        cfg = self.cfg

        cfg["hotkeys"]["record"] = self._get("hotkeys.record", str, "ctrl+alt+space")
        cfg["hotkeys"]["cancel"] = self._get("hotkeys.cancel", str, "ctrl+alt+x")
        cfg["hotkeys"]["cycle_profile"] = self._get("hotkeys.cycle_profile", str,
                                                    "ctrl+alt+p")
        cfg["hotkeys"]["toggle_backend"] = self._get("hotkeys.toggle_backend", str,
                                                     "ctrl+alt+g")
        for _k, _d in (("write", "ctrl+alt+w"), ("fix", "ctrl+alt+f"),
                       ("notes", "ctrl+alt+n"), ("devanagari", "ctrl+alt+h")):
            cfg["hotkeys"][_k] = self._get("hotkeys." + _k, str, _d)

        cfg["audio"]["capture_system"] = self._get("audio.capture_system", bool)
        cfg["audio"]["capture_mic"] = self._get("audio.capture_mic", bool)
        cfg["audio"]["system_gain"] = self._get("audio.system_gain", float, 1.0)
        cfg["audio"]["mic_gain"] = self._get("audio.mic_gain", float, 1.0)

        t = cfg["transcription"]
        t["backend"] = self._get("transcription.backend", str, "auto")
        t["fallback_cooldown_minutes"] = self._get(
            "transcription.fallback_cooldown_minutes", int, 60)
        t["groq"]["model"] = self._get("transcription.groq.model", str,
                                       "whisper-large-v3")
        t["groq"]["language"] = self._get("transcription.groq.language", str, None)
        t["local"]["model"] = self._get("transcription.local.model", str, "large-v3")
        t["local"]["device"] = self._get("transcription.local.device", str, "cuda")
        t["local"]["compute_type"] = self._get("transcription.local.compute_type", str,
                                               "int8_float16")
        t["local"]["batch_size"] = self._get("transcription.local.batch_size", int, 8)
        t["local"]["language"] = self._get("transcription.local.language", str, None)
        t["vocabulary"] = self._vocab.get("1.0", "end-1c").strip()

        o = cfg["output"]
        o["copy_to_clipboard"] = self._get("output.copy_to_clipboard", bool)
        o["auto_paste"] = self._get("output.auto_paste", bool)
        o["restore_clipboard"] = self._get("output.restore_clipboard", bool)
        o["save_transcripts"] = self._get("output.save_transcripts", bool)

        sc = cfg.setdefault("script", {})
        sc["default"] = self._get("script.default", str, "latin")
        sc["language"] = self._get("script.language", str, "hi")

        act = cfg.setdefault("actions", {})
        mdl = act.setdefault("models", {})
        mdl["provider"] = self._get("actions.models.provider", str, "ollama")
        mdl["model"] = self._get("actions.models.model", str, "qwen2.5:7b")
        act["command_seconds"] = self._get("actions.command_seconds", int, 8)

        cfg.setdefault("context", {})["ocr_fallback"] = self._get(
            "context.ocr_fallback", bool)
        cfg.setdefault("learning", {})["enabled"] = self._get(
            "learning.enabled", bool)

        u = cfg.setdefault("ui", {})
        u["overlay"] = self._get("ui.overlay", bool)
        u["overlay_meter"] = self._get("ui.overlay_meter", bool)
        u["theme"] = self._get("ui.theme", str, "dark-amber")

        cfg["profiles"] = [
            {"name": p["name"], "prompt": cfgio.literal_block(p.get("prompt", ""))}
            for p in self._profiles
        ]

        # The API key lives in .env, not config.yaml, so the config stays safe to
        # share and commit.
        key = self._get("_groq_key", str, "") or ""
        env_name = t.get("groq", {}).get("api_key_env", "GROQ_API_KEY")
        if key != (os.environ.get(env_name) or ""):
            cfgio.write_env(ROOT / ".env", env_name, key)
            os.environ[env_name] = key

        try:
            startup.set_enabled(self._get("_startup", bool))
        except OSError as e:
            log.warning("could not update start-up entry: %s", e)

        try:
            cfgio.save(self.app.config_path, cfg)
        except Exception as e:
            self._flash(f"Save failed: {e}", self.c["rec"])
            return

        self.app.apply_config(cfg)
        self._refresh_status()
        self._flash("Saved.", self.c["ok"])

    def _close(self) -> None:
        self.app.settings_closed()
        self.destroy()
