"""The setup wizard: type five sentences, get a personalised speller.

Shown once on first run, and available any time from Settings. Skippable - the
app works without it, it just starts from defaults and learns more slowly.
"""

from __future__ import annotations

import logging

import customtkinter as ctk

from . import icons
from .onboarding import Onboarding
from .theme import appearance_mode, palette

log = logging.getLogger(__name__)


class Wizard(ctk.CTkToplevel):
    def __init__(self, app, on_done=None):
        super().__init__(app.root)
        self.app = app
        self.on_done = on_done
        theme = app.cfg.get("ui", {}).get("theme", "dark-amber")
        self.c = palette(theme)
        ctk.set_appearance_mode(appearance_mode(theme))

        self.title("LiveWhisper setup")
        self.configure(fg_color=self.c["bg"])
        self.minsize(680, 460)
        self._centre(760, 560)

        self.onboarding = Onboarding(
            app.cfg.get("script", {}).get("language", "hi"))
        self.prompts = self.onboarding.prompts()
        self.index = 0
        self.answers: list = []

        self._build()
        self.after(250, lambda: icons.apply(self))
        self.after(120, self.lift)
        self.protocol("WM_DELETE_WINDOW", self._skip_all)

    def _centre(self, w, h) -> None:
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        try:
            scale = ctk.ScalingTracker.get_window_scaling(self)
        except Exception:
            scale = 1.0
        w = min(w, int((sw - 80) / scale))
        h = min(h, int((sh - 120) / scale))
        self.geometry(f"{w}x{h}+{int((sw - w * scale) / 2)}+{int((sh - h * scale) / 2)}")

    # ----------------------------------------------------------------- build

    def _build(self) -> None:
        c = self.c
        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=34, pady=28)

        ctk.CTkLabel(wrap, text="Teach it how you write",
                     font=("Archivo", 24, "bold"), text_color=c["text"],
                     anchor="w").pack(fill="x")
        ctk.CTkLabel(
            wrap,
            text="Type each sentence the way you would actually send it. "
                 "Spelling, capitals and punctuation exactly as you normally "
                 "write - that is the whole point.",
            font=("Segoe UI", 13), text_color=c["muted"], anchor="w",
            justify="left", wraplength=620).pack(fill="x", pady=(6, 20))

        self.progress = ctk.CTkLabel(wrap, text="", font=("Segoe UI", 11),
                                     text_color=c["accent"], anchor="w")
        self.progress.pack(fill="x", pady=(0, 6))

        card = ctk.CTkFrame(wrap, fg_color=c["surface"], corner_radius=12)
        card.pack(fill="x")

        self.deva = ctk.CTkLabel(card, text="", font=("Nirmala UI", 22),
                                 text_color=c["text"], anchor="w",
                                 justify="left", wraplength=600)
        self.deva.pack(fill="x", padx=22, pady=(20, 4))

        self.gloss = ctk.CTkLabel(card, text="", font=("Segoe UI", 12),
                                  text_color=c["muted"], anchor="w",
                                  justify="left", wraplength=600)
        self.gloss.pack(fill="x", padx=22, pady=(0, 16))

        self.entry = ctk.CTkEntry(card, height=46, font=("Consolas", 15),
                                  fg_color=c["bg"], border_color=c["border"],
                                  text_color=c["text"],
                                  placeholder_text="type it your way...")
        self.entry.pack(fill="x", padx=22, pady=(0, 20))
        self.entry.bind("<Return>", lambda e: self._next())

        row = ctk.CTkFrame(wrap, fg_color="transparent")
        row.pack(fill="x", pady=(18, 0))
        ctk.CTkButton(row, text="Skip setup", width=110, height=38,
                      corner_radius=8, fg_color="transparent",
                      hover_color=c["surface_hi"], text_color=c["muted"],
                      command=self._skip_all).pack(side="left")
        ctk.CTkButton(row, text="Skip this one", width=120, height=38,
                      corner_radius=8, fg_color=c["surface_hi"],
                      hover_color=c["border"], text_color=c["text"],
                      command=lambda: self._next(skip=True)).pack(side="right",
                                                                  padx=(8, 0))
        self.next_btn = ctk.CTkButton(row, text="Next", width=130, height=38,
                                      corner_radius=8, fg_color=c["accent"],
                                      hover_color=c["accent_hi"],
                                      text_color=c["accent_text"],
                                      font=("Segoe UI", 13, "bold"),
                                      command=self._next)
        self.next_btn.pack(side="right")

        self.result = ctk.CTkTextbox(wrap, height=132, fg_color=c["surface"],
                                     border_color=c["border"], border_width=1,
                                     text_color=c["text"], wrap="word",
                                     font=("Consolas", 12))

        self._show()

    def _show(self) -> None:
        p = self.prompts[self.index]
        self.progress.configure(
            text=f"SENTENCE {self.index + 1} OF {len(self.prompts)}")
        self.deva.configure(text=p.devanagari)
        self.gloss.configure(text=p.gloss)
        self.entry.delete(0, "end")
        self.entry.focus_set()
        self.next_btn.configure(
            text="Finish" if self.index == len(self.prompts) - 1 else "Next")

    # ------------------------------------------------------------------ flow

    def _next(self, skip: bool = False) -> None:
        typed = "" if skip else self.entry.get().strip()
        self.answers.append((self.prompts[self.index].devanagari, typed))
        self.index += 1
        if self.index < len(self.prompts):
            self._show()
        else:
            self._finish()

    def _finish(self) -> None:
        try:
            result = self.onboarding.process(self.answers)
            self.onboarding.apply(result, self.app.styles)
        except Exception as e:
            log.exception("onboarding failed")
            self._done_screen(f"Setup could not be applied: {e}", [])
            return

        lines = []
        if result.conventions.rules:
            lines.append("Spelling habits learned:")
            for a, b in result.conventions.rules.items():
                lines.append(f"   {a} -> {b}   (applies to every word)")
        if result.conventions.overrides:
            lines.append(f"\nExact spellings remembered: "
                         f"{len(result.conventions.overrides)}")
        try:
            _src, before, after = self.onboarding.preview(result.conventions)
            if before != after:
                lines.append("\nExample of the difference:")
                lines.append(f"   was:  {before}")
                lines.append(f"   now:  {after}")
        except Exception:
            pass
        if not lines:
            lines = ["Nothing to change - your spelling already matches the "
                     "defaults.\nThe app will keep learning as you correct it."]

        self._done_screen("Done", lines)

    def _done_screen(self, heading: str, lines: list) -> None:
        for w in self.winfo_children():
            w.destroy()
        c = self.c
        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=34, pady=28)

        ctk.CTkLabel(wrap, text=heading, font=("Archivo", 24, "bold"),
                     text_color=c["text"], anchor="w").pack(fill="x")
        ctk.CTkLabel(wrap, text="You can redo this any time from Settings, and "
                                "it keeps learning whenever you correct it.",
                     font=("Segoe UI", 13), text_color=c["muted"], anchor="w",
                     justify="left", wraplength=620).pack(fill="x", pady=(6, 18))

        box = ctk.CTkTextbox(wrap, fg_color=c["surface"], border_width=1,
                             border_color=c["border"], text_color=c["text"],
                             wrap="word", font=("Consolas", 12))
        box.pack(fill="both", expand=True)
        box.insert("1.0", "\n".join(lines))
        box.configure(state="disabled")

        ctk.CTkButton(wrap, text="Start using LiveWhisper", height=40,
                      corner_radius=8, fg_color=c["accent"],
                      hover_color=c["accent_hi"], text_color=c["accent_text"],
                      font=("Segoe UI", 13, "bold"),
                      command=self._close).pack(pady=(18, 0))

    def _skip_all(self) -> None:
        self._close()

    def _close(self) -> None:
        try:
            if self.on_done:
                self.on_done()
        finally:
            self.destroy()
