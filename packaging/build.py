#!/usr/bin/env python
"""Build LiveWhisper-Setup-<version>.exe: app folder, then installer.

    .venv\\Scripts\\python packaging\\build.py

Needs PyInstaller in the venv and Inno Setup 6 (ISCC.exe). The version comes
from livewhisper/__init__.py, so there is one place to change it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "packaging"


def version() -> str:
    text = (ROOT / "livewhisper" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


def iscc() -> Path:
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles(x86)", ""),
                 os.environ.get("ProgramFiles", "")):
        exe = Path(base) / ("Programs/Inno Setup 6" if "Local" in base else "Inno Setup 6") / "ISCC.exe"
        if exe.exists():
            return exe
    sys.exit("Inno Setup 6 not found - install it from https://jrsoftware.org/isdl.php")


def main() -> int:
    v = version()
    parts = (v.split(".") + ["0", "0", "0"])[:4]
    tup = ", ".join(str(int(re.sub(r"\D.*", "", x) or 0)) for x in parts)
    info = (PACK / "version.txt").read_text(encoding="utf-8")
    info = re.sub(r"filevers=\([^)]*\), prodvers=\([^)]*\)",
                  f"filevers=({tup}), prodvers=({tup})", info)
    info = re.sub(r"(StringStruct\('(?:File|Product)Version', ')[^']*'", rf"\g<1>{v}'", info)
    (PACK / "version.txt").write_text(info, encoding="utf-8")

    if not (ROOT / "vendor" / "llama" / "llama-server.exe").exists():
        subprocess.run([sys.executable, str(PACK / "fetch_llama.py")], check=True)
    for needed in ("vendor/llama/llama-server.exe", "data/translit.npz"):
        if not (ROOT / needed).exists():
            sys.exit(f"missing {needed}")

    print(f"== LiveWhisper {v}: app folder", flush=True)
    dist = ROOT / "build" / "dist"
    shutil.rmtree(dist / "LiveWhisper", ignore_errors=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", str(PACK / "LiveWhisper.spec"),
                    "--noconfirm", "--distpath", str(dist),
                    "--workpath", str(ROOT / "build" / "pyi")], check=True)

    print("== installer", flush=True)
    subprocess.run([str(iscc()), f"/DAppVersion={v}", str(PACK / "installer.iss")], check=True)
    out = ROOT / "build" / "installer" / f"LiveWhisper-Setup-{v}.exe"
    print(f"\n{out}  ({out.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
