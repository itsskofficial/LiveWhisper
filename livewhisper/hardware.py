"""Detect the machine and recommend local-model settings that will fit on it.

Deliberately dependency-free (stdlib + nvidia-smi) so the installer can run this
with the system Python before the virtualenv exists.

    python -m livewhisper.hardware          # human readable
    python -m livewhisper.hardware --json   # for the installer
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass


@dataclass
class Machine:
    gpu: str | None
    vram_mb: int
    ram_mb: int
    cpus: int

    @property
    def has_cuda(self) -> bool:
        return self.gpu is not None and self.vram_mb > 0


@dataclass
class Recommendation:
    model: str
    device: str
    compute_type: str
    batch_size: int
    reason: str
    speed: str  # rough expectation, so the number is not a surprise later


def detect() -> Machine:
    return Machine(
        gpu=_gpu_name(),
        vram_mb=_vram_mb(),
        ram_mb=_ram_mb(),
        cpus=os.cpu_count() or 1,
    )


def _nvidia_smi(query: str) -> str | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    first = out.stdout.strip().splitlines()
    return first[0].strip() if first else None


def _gpu_name() -> str | None:
    return _nvidia_smi("name")


def _vram_mb() -> int:
    raw = _nvidia_smi("memory.total")
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return 0


def _ram_mb() -> int:
    if sys.platform == "win32":
        class _Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        s = _Status()
        s.dwLength = ctypes.sizeof(_Status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
            return int(s.ullTotalPhys / (1024 * 1024))
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 / 1024)
    except (ValueError, AttributeError, OSError):
        return 0


def recommend(m: Machine | None = None) -> Recommendation:
    """Pick model / precision / batch size that fit, favouring accuracy.

    VRAM headroom matters more than raw model size: large-v3 at int8_float16 is
    both smaller and more accurate on non-English audio than a turbo or medium
    model at full precision, so we stay on large-v3 as far down as it will go.
    """
    m = m or detect()

    if not m.has_cuda:
        # CPU-only. large-v3 is unusably slow here; small is the honest ceiling.
        model = "small" if m.cpus >= 8 else "base"
        return Recommendation(
            model=model, device="cpu", compute_type="int8",
            batch_size=4 if m.cpus >= 8 else 1,
            reason=(f"No CUDA GPU detected, {m.cpus} CPU cores. "
                    f"'{model}' is the largest model that stays practical on CPU."),
            speed="roughly 1-3x realtime; a 30 min meeting takes 10-30 min",
        )

    vram = m.vram_mb
    gb = round(vram / 1024)  # 8188 MB is an 8 GB card, not a 7 GB one
    if vram >= 10_000:
        return Recommendation(
            "large-v3", "cuda", "float16", 16,
            f"{gb} GB VRAM is enough for full float16 precision.",
            "roughly 30-50x realtime; a 30 min meeting takes under a minute",
        )
    if vram >= 6_000:
        return Recommendation(
            "large-v3", "cuda", "int8_float16", 8,
            f"{gb} GB VRAM. int8_float16 keeps large-v3 accuracy at "
            f"about 3 GB, leaving room for your other apps.",
            "roughly 25-35x realtime; a 30 min meeting takes about a minute",
        )
    if vram >= 4_000:
        return Recommendation(
            "large-v3", "cuda", "int8", 4,
            f"{gb} GB VRAM is tight. int8 keeps large-v3 accuracy "
            f"with a smaller batch.",
            "roughly 15-25x realtime; a 30 min meeting takes 1-2 min",
        )
    if vram >= 2_000:
        return Recommendation(
            "large-v3-turbo", "cuda", "int8", 4,
            f"{gb} GB VRAM cannot hold large-v3. Turbo is faster and "
            f"smaller, at some cost to non-English accuracy.",
            "roughly 15-25x realtime; a 30 min meeting takes 1-2 min",
        )
    return Recommendation(
        "small", "cuda", "int8", 2,
        f"Only {vram} MB VRAM. 'small' is the largest model that will fit.",
        "roughly 10-20x realtime",
    )


def summary() -> dict:
    m = detect()
    r = recommend(m)
    return {"machine": asdict(m), "recommended": asdict(r),
            "gpu_label": m.gpu or "none",
            "vram_gb": round(m.vram_mb / 1024, 1) if m.vram_mb else 0,
            "ram_gb": round(m.ram_mb / 1024, 1) if m.ram_mb else 0}


def main() -> int:
    data = summary()
    if "--json" in sys.argv:
        print(json.dumps(data))
        return 0
    m, r = data["machine"], data["recommended"]
    print("Detected hardware")
    print(f"  GPU   {m['gpu'] or 'none detected'}")
    print(f"  VRAM  {data['vram_gb']} GB")
    print(f"  RAM   {data['ram_gb']} GB")
    print(f"  CPU   {m['cpus']} cores")
    print("\nRecommended local model")
    print(f"  model         {r['model']}")
    print(f"  device        {r['device']}")
    print(f"  compute_type  {r['compute_type']}")
    print(f"  batch_size    {r['batch_size']}")
    print(f"\n  {r['reason']}")
    print(f"  Expect {r['speed']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
