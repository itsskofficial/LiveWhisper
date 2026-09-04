#!/usr/bin/env python
"""Seed a profile with realistic history, for demo prep.

Some behaviour only appears once the app has watched you for a while: it needs
at least three samples before it trusts a habit, so a freshly installed copy
cannot show the per-app contrast on camera.

This does exactly what normal use would do - it feeds the same observations the
app would have collected from you writing in each app - just without spending
ten minutes of recording time doing it live. The resulting behaviour is real,
not mocked.

    python demo_seed.py            # seed
    python demo_seed.py --show     # print what is currently learned
    python demo_seed.py --clear    # wipe, so the wizard runs fresh

Run --clear before demoing the setup wizard.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from livewhisper.profile import ProfileStore  # noqa: E402

# What a chat app looks like after a week: lowercase, no full stops.
CHAT_SAMPLES = [
    "haan bhai kal milte hain",
    "nahi yaar mujhe nahi pata",
    "ok done, kal subah bhej dunga",
    "kya kar raha hai tu",
    "theek hai, phir baad me baat karte hain",
]

# What an email client looks like: sentence case, full stops.
EMAIL_SAMPLES = [
    "Thanks for the update, I will review it today.",
    "Apologies for the delay in getting back to you.",
    "Please find the revised timeline attached.",
    "I have shared the document with the wider team.",
    "Let me know if Thursday still works for you.",
]

CHAT_APPS = ["whatsapp.exe", "discord.exe", "telegram.exe"]
MAIL_APPS = ["outlook.exe", "thunderbird.exe"]


def show(store: ProfileStore) -> None:
    g = store.get(ProfileStore.GLOBAL)
    print("global spelling conventions:", g.conventions.rules or "(none)")
    print("exact words remembered:", len(g.conventions.overrides))
    print("\nper-app habits:")
    any_app = False
    for name, prof in sorted(store.profiles.items()):
        if name == ProfileStore.GLOBAL or not prof.habits.samples:
            continue
        any_app = True
        h = prof.habits
        print(f"   {name:<20} capitals {h.capitalize:5.0%}   "
              f"full stops {h.terminal_period:5.0%}   ({h.samples} samples)")
    if not any_app:
        print("   (none yet)")


def main() -> int:
    store = ProfileStore()

    if "--clear" in sys.argv:
        store.profiles.clear()
        store.save()
        if store.path.exists():
            store.path.unlink()
        print(f"cleared {store.path} - the setup wizard will run on next launch")
        return 0

    if "--show" in sys.argv:
        show(store)
        return 0

    for app in CHAT_APPS:
        for line in CHAT_SAMPLES:
            store.observe_text(app, line)
    for app in MAIL_APPS:
        for line in EMAIL_SAMPLES:
            store.observe_text(app, line)

    # The spelling conventions a Hinglish typist would have taught it.
    conv = store.get(ProfileStore.GLOBAL).conventions
    for native, default, mine in [("मुझे", "mujhe", "muze"),
                                  ("समझो", "samjho", "samzo"),
                                  ("वो", "vo", "wo"),
                                  ("वजह", "vajah", "wajah")]:
        conv.learn(native, default, mine)

    store.save()
    print(f"seeded {store.path}\n")
    show(store)

    print("\nverifying the contrast is real:")
    for app in ("whatsapp.exe", "outlook.exe"):
        prof = store.get(app)
        out = prof.habits.apply("Yes I will send it tomorrow. Thanks.")
        print(f"   {app:<16} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
