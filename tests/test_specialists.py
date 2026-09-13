#!/usr/bin/env python
"""Installing a specialist model writes a route the app can use, and nothing else.

Download and conversion are stubbed: this checks the part that can silently
break a user's setup - editing their config.yaml - without touching the network
or the real config.

    python tests/test_specialists.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import huggingface_hub  # noqa: E402

from livewhisper import config as cfgio  # noqa: E402
from livewhisper import specialists as sp  # noqa: E402
from livewhisper.console import setup as _console  # noqa: E402
from livewhisper.transcribe import LocalBackend  # noqa: E402

_console()
ROOT = Path(__file__).resolve().parent.parent
fails = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global fails
    fails += not ok
    print(f"[{'  ok  ' if ok else ' FAIL '}] {name}" + (f"  {detail}" if detail else ""))


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    try:
        cfg_path = tmp / "config.yaml"
        shutil.copy(ROOT / "config.yaml", cfg_path)
        cfg = cfgio.load(cfg_path)
        cfg["transcription"]["local"]["models_dir"] = str(tmp / "models")
        cfgio.save(cfg_path, cfg)

        downloads = []

        def fake_snapshot(repo, local_dir=None, allow_patterns=None):
            downloads.append((repo, local_dir))
            Path(local_dir).mkdir(parents=True, exist_ok=True)
            return local_dir

        huggingface_hub.snapshot_download = fake_snapshot
        sp.convert = lambda src, out, quantization="float16": (
            Path(out).mkdir(parents=True, exist_ok=True), out)[1]
        quiet = lambda m: None                                    # noqa: E731

        bn = sp.Specialist("bn", "org/bn", "bn-medium", 3.06, "apache-2.0",
                           measured={"delivered": 0.3})
        hi = sp.Specialist("hi", "org/hi", "hinglish", 6.17, "apache-2.0",
                           latin_output=True, language="en",
                           measured={"delivered": 0.2})
        sp.install(bn, cfg_path, progress=quiet)
        sp.install(hi, cfg_path, progress=quiet)

        models = cfgio.load(cfg_path)["transcription"]["local"]["models"]
        check("plain route written as a path", str(models["bn"]).endswith("bn-medium"))
        check("latin route carries its flags",
              dict(models["hi"]) == {"path": str(tmp / "models" / "hinglish"),
                                     "latin_output": True, "language": "en"},
              str(dict(models["hi"])))
        check("downloads go to plain folders, never the symlink cache",
              all(ld and "hub" not in ld for _, ld in downloads))
        text = cfg_path.read_text(encoding="utf-8")
        check("config comments survive", "# The languages you dictate in" in text
              and "# Specialist models per language" in text)
        check("conversion source cleaned up",
              not (tmp / "models" / "bn-medium.src").exists())

        local = cfgio.load(cfg_path)["transcription"]["local"]
        lb = LocalBackend(local)
        check("the backend reads both routes",
              lb._route("bn").get("path", "").endswith("bn-medium")
              and lb._route("hi").get("latin_output") is True)

        sp.remove("bn", cfg_path, progress=quiet)
        models = cfgio.load(cfg_path)["transcription"]["local"]["models"]
        check("remove drops the route", "bn" not in models)
        check("remove deletes its files", not (tmp / "models" / "bn-medium").exists())
        messages = []
        sp.remove("zz", cfg_path, progress=messages.append)
        check("removing an absent specialist is a message, not an error",
              messages and "No specialist" in messages[0])

        saved = list(sp.CATALOGUE)
        sp.CATALOGUE[:] = [sp.Specialist("ta", "org/ta", "ta-medium", 3.06, "apache-2.0")]
        check("unmeasured candidate refused without --force",
              sp.main(["--config", str(cfg_path), "install", "ta"]) == 1)
        sp.CATALOGUE[:] = saved
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{'all passed' if not fails else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
