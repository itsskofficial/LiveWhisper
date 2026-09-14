#!/usr/bin/env python
"""Convert a HuggingFace Whisper fine-tune into the format faster-whisper runs.

Most Indic fine-tunes are published as PyTorch weights. faster-whisper needs a
CTranslate2 conversion, which is also half the size in float16 and several times
faster to decode.

Two details the stock converter leaves to you, both of which break loading
silently or loudly:

  tokenizer.json         older fine-tunes ship only vocab.json + merges.txt;
                         faster-whisper requires the fast tokenizer file
  preprocessor_config    large-v3 derivatives use 128 mel bins, and without
                         this file faster-whisper assumes 80 and emits garbage

    python scripts/convert_ct2.py Oriserve/Whisper-Hindi2Hinglish-Prime D:/models/ct2/hinglish-prime
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


# Converting loads the whole checkpoint before writing the half-size copy. When
# Windows cannot commit that much memory, torch's native loader does not raise
# MemoryError - it dies with an access violation and no traceback. That is how
# the Kannada conversion failed seven times with an intact, hash-verified
# download, and how a plain torch.load of the Tamil checkpoint crashed while
# benchmarks ran alongside it: Windows logged "low virtual memory condition"
# (Resource-Exhaustion-Detector, event 2004) in the same minutes.
#
# Calibration, and two design mistakes it took to get here:
#
# - 2x the checkpoint plus 3 GB assumed benchmarks growing alongside every
#   conversion. With a 16 GB machine's everyday applications open, that bar was
#   never reached: a Kannada conversion waited indefinitely for 9.1 GB.
# - It waited while holding the conversion lock, so every conversion queued
#   behind it waited too. Memory is now awaited before the lock is taken, and
#   re-checked once it is held.
# - Waiting processes had already imported torch and transformers, holding
#   ~1.2 GB each for nothing. Those imports now happen after the gate.
#
# 1.5x covers the full-precision load plus the float16 copy being written; the
# margin is for everything else. Each run prints its real peak commit, which is
# what this number should eventually be set from.
MEMORY_FACTOR = 1.5
MEMORY_MARGIN_GB = 1.5


def _available_commit_gb() -> float | None:
    """How much more memory Windows can commit right now, in GB."""
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return status.ullAvailPageFile / 1e9      # commit limit minus committed
    except Exception:
        return None


def _wait_for_memory(need_gb: float) -> None:
    """Block until the machine can commit need_gb more, rather than crash."""
    import time
    said = False
    while True:
        have = _available_commit_gb()
        if have is None or have >= need_gb:
            return
        if not said:
            print(f"waiting for {need_gb:.1f} GB of committable memory "
                  f"(have {have:.1f})...", flush=True)
            said = True
        time.sleep(30)


def _acquire_slot(folder: Path, need_gb: float):
    """Wait for memory, take the machine-wide lock, confirm memory still fits.

    Returns the open lock handle; keep it alive while converting. A process that
    is short of memory never holds the lock, so it cannot block a conversion
    that would fit. The OS releases the lock if the holder dies.
    """
    import time
    folder.mkdir(parents=True, exist_ok=True)
    handle = open(folder / ".convert.lock", "a+b")
    try:
        import msvcrt
    except ImportError:                       # not Windows
        import fcntl
        _wait_for_memory(need_gb)
        fcntl.flock(handle, fcntl.LOCK_EX)
        return handle
    said_lock = False
    while True:
        _wait_for_memory(need_gb)
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            if not said_lock:
                print("waiting for another conversion to finish...", flush=True)
                said_lock = True
            time.sleep(10)
            continue
        have = _available_commit_gb()
        if have is None or have >= need_gb:
            return handle
        handle.seek(0)                        # memory went while we waited
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _peak_commit_gb() -> float | None:
    """This process's peak committed memory - the number to calibrate from."""
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Without these declarations ctypes passes the process handle as a
        # 32-bit int; on 64-bit Windows the handle is truncated, the call fails,
        # and the peak silently reads as unavailable.
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        get_info = getattr(kernel32, "K32GetProcessMemoryInfo", None)
        if get_info is None:
            get_info = ctypes.WinDLL("psapi").GetProcessMemoryInfo
        get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        get_info.restype = wintypes.BOOL

        counters = PMC()
        counters.cb = ctypes.sizeof(PMC)
        ok = get_info(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return counters.PeakPagefileUsage / 1e9 if ok else None
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("out", type=Path)
    ap.add_argument("--quantization", default="float16")
    args = ap.parse_args()

    from huggingface_hub import snapshot_download

    # A plain folder, not the shared cache: the cache builds its snapshots out of
    # symlinks, and Windows refuses to create those without Developer Mode
    # ("WinError 1314: A required privilege is not held by the client").
    if Path(args.repo).is_dir():
        # A local folder, e.g. a checkpoint re-saved as clean safetensors after
        # the original would not load through transformers.
        src = Path(args.repo)
    else:
        src_dir = args.out.with_name(args.out.name + ".src")
        src = Path(snapshot_download(args.repo, local_dir=str(src_dir), allow_patterns=[
            "*.json", "*.safetensors", "pytorch_model.bin", "*.txt", "*.model"]))
    print(f"source {src}")

    # One conversion at a time, machine-wide. Downloads can run in parallel, but
    # converting loads the whole model into RAM - 3-6 GB for large-v2/v3 - and
    # four overlapping ones pushed a 15 GB machine to 1 GB free with the commit
    # limit nearly exhausted. The OS releases the lock if this process dies.
    weights_gb = sum(f.stat().st_size for f in list(src.glob("*.bin")) +
                     list(src.glob("*.safetensors"))) / 1e9
    lock = _acquire_slot(args.out.parent, weights_gb * MEMORY_FACTOR + MEMORY_MARGIN_GB)

    # Only now, with room to use them: torch and transformers alone commit over
    # a gigabyte, which waiting processes used to hold for nothing.
    import ctranslate2
    from transformers import WhisperProcessor, WhisperTokenizerFast

    # Normalise the tokenizer and preprocessor next to the weights first, so the
    # converter can copy them across.
    work = args.out.with_name(args.out.name + ".hf")
    work.mkdir(parents=True, exist_ok=True)
    tok = WhisperTokenizerFast.from_pretrained(src)
    tok.save_pretrained(work)
    try:
        proc = WhisperProcessor.from_pretrained(src)
        proc.feature_extractor.save_pretrained(work)
    except Exception as exc:
        print(f"no processor config in repo ({exc}); inferring from model config")
        cfg = json.loads((src / "config.json").read_text())
        (work / "preprocessor_config.json").write_text(json.dumps({
            "feature_extractor_type": "WhisperFeatureExtractor",
            "feature_size": cfg.get("num_mel_bins", 80), "sampling_rate": 16000,
            "hop_length": 160, "chunk_length": 30, "n_fft": 400,
            "padding_value": 0.0, "return_attention_mask": False}))

    for name in ("config.json", "generation_config.json", "model.safetensors",
                 "model.safetensors.index.json", "pytorch_model.bin"):
        if (src / name).exists():
            target = work / name
            if not target.exists():
                try:
                    target.symlink_to(src / name)
                except OSError:
                    shutil.copy2(src / name, target)
    for shard in src.glob("model-*.safetensors"):
        target = work / shard.name
        if not target.exists():
            try:
                target.symlink_to(shard)
            except OSError:
                shutil.copy2(shard, target)

    conv = ctranslate2.converters.TransformersConverter(
        str(work), copy_files=["tokenizer.json", "preprocessor_config.json"],
        load_as_float16=True)
    conv.convert(str(args.out), quantization=args.quantization, force=True)
    shutil.rmtree(work, ignore_errors=True)

    mels = json.loads((args.out / "preprocessor_config.json").read_text()).get("feature_size")
    size = sum(f.stat().st_size for f in args.out.iterdir()) / 1e9
    peak = _peak_commit_gb()
    peak_txt = f", peak commit {peak:.1f} GB for {weights_gb:.1f} GB weights" if peak else ""
    print(f"converted -> {args.out}  ({size:.2f} GB, {mels} mel bins{peak_txt})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
