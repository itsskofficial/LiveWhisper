"""Install-time helpers, driven by install.ps1.

Keeping these in Python rather than PowerShell means the installer and the
settings window share exactly one implementation of "apply the recommended
model" and "store the API key".

    python -m livewhisper.bootstrap recommend
    python -m livewhisper.bootstrap apply-recommended
    python -m livewhisper.bootstrap set-key <key>
    python -m livewhisper.bootstrap download-model
    python -m livewhisper.bootstrap model-status
    python -m livewhisper.bootstrap make-icon
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import config as cfgio
from . import hardware, icons

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.yaml"
ENV = ROOT / ".env"


def _local_backend(cfg: dict):
    from .transcribe import LocalBackend
    return LocalBackend(cfg["transcription"].get("local", {}))


def cmd_recommend(_) -> int:
    return hardware.main()


def cmd_apply_recommended(_) -> int:
    rec = hardware.recommend()
    cfg = cfgio.load(CONFIG)
    loc = cfg["transcription"]["local"]
    loc["model"] = rec.model
    loc["device"] = rec.device
    loc["compute_type"] = rec.compute_type
    loc["batch_size"] = rec.batch_size
    cfgio.save(CONFIG, cfg)
    print(f"local model set to {rec.model} / {rec.compute_type} / batch {rec.batch_size}")
    return 0


def cmd_set_key(args) -> int:
    key = (args.key or "").strip()
    if not key:
        print("no key given; skipping")
        return 0
    cfgio.write_env(ENV, "GROQ_API_KEY", key)
    os.environ["GROQ_API_KEY"] = key
    print("GROQ_API_KEY written to .env")
    return 0


def cmd_model_status(_) -> int:
    cfg = cfgio.load(CONFIG)
    backend = _local_backend(cfg)
    ready = backend.is_downloaded()
    print("downloaded" if ready else "missing")
    return 0 if ready else 1


def cmd_download_model(_) -> int:
    cfg = cfgio.load(CONFIG)
    backend = _local_backend(cfg)
    if backend.is_downloaded():
        print("already downloaded")
        return 0
    try:
        backend.download(progress=print)
    except Exception as e:
        print(f"download failed: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_make_icon(_) -> int:
    print(f"wrote {icons.write_ico()}")
    return 0


COMMANDS = {
    "recommend": cmd_recommend,
    "apply-recommended": cmd_apply_recommended,
    "set-key": cmd_set_key,
    "download-model": cmd_download_model,
    "model-status": cmd_model_status,
    "make-icon": cmd_make_icon,
}


def main() -> int:
    p = argparse.ArgumentParser(description="LiveWhisper install helpers")
    p.add_argument("command", choices=sorted(COMMANDS))
    p.add_argument("key", nargs="?", help="API key, for set-key")
    args = p.parse_args()
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
