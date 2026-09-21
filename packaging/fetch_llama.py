#!/usr/bin/env python
"""Put llama.cpp's server in vendor/llama, for the built-in language models.

The Vulkan build: it runs on NVIDIA, AMD and Intel GPUs and falls back to the
CPU, in 30 MB. Pinned to one release so every build ships the same runner; the
app was tested against this one (livewhisper/llm.py). MIT licensed; the
licence is copied beside it.

    python packaging/fetch_llama.py
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import requests

RELEASE = "b11065"
ASSET = f"llama-{RELEASE}-bin-win-vulkan-x64.zip"
URL = f"https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE}/{ASSET}"
LICENSE = f"https://raw.githubusercontent.com/ggml-org/llama.cpp/{RELEASE}/LICENSE"
OUT = Path(__file__).resolve().parent.parent / "vendor" / "llama"
# The server and what it loads. Not the other tools, nor the RPC backend.
KEEP = ("ggml", "llama.dll", "libomp", "llama-common", "llama-server", "mtmd", "LICENSE")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"downloading {ASSET}...", flush=True)
    r = requests.get(URL, timeout=120)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = [n for n in z.namelist()
             if n.startswith(KEEP) and not n.startswith("ggml-rpc")]
    for n in names:
        z.extract(n, OUT)
    (OUT / "LICENSE-llama.cpp").write_bytes(requests.get(LICENSE, timeout=60).content)
    (OUT / "VERSION").write_text(RELEASE + "\n")
    print(f"{len(names)} files in {OUT}")
    return 0 if (OUT / "llama-server.exe").exists() else 1


if __name__ == "__main__":
    sys.exit(main())
