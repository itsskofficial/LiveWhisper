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


def _conversion_lock(folder: Path):
    """Block until no other conversion holds the lock; return the open handle.

    Keep the returned object alive for as long as the lock should be held.
    """
    import time
    folder.mkdir(parents=True, exist_ok=True)
    handle = open(folder / ".convert.lock", "a+b")
    try:
        import msvcrt
    except ImportError:                       # not Windows
        import fcntl
        fcntl.flock(handle, fcntl.LOCK_EX)
        return handle
    waited = False
    while True:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return handle
        except OSError:
            if not waited:
                print("waiting for another conversion to finish...", flush=True)
                waited = True
            time.sleep(10)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("out", type=Path)
    ap.add_argument("--quantization", default="float16")
    args = ap.parse_args()

    from huggingface_hub import snapshot_download
    import ctranslate2
    from transformers import WhisperProcessor, WhisperTokenizerFast

    # A plain folder, not the shared cache: the cache builds its snapshots out of
    # symlinks, and Windows refuses to create those without Developer Mode
    # ("WinError 1314: A required privilege is not held by the client").
    src_dir = args.out.with_name(args.out.name + ".src")
    src = Path(snapshot_download(args.repo, local_dir=str(src_dir), allow_patterns=[
        "*.json", "*.safetensors", "pytorch_model.bin", "*.txt", "*.model"]))
    print(f"source {src}")

    # One conversion at a time, machine-wide. Downloads can run in parallel, but
    # converting loads the whole model into RAM - 3-6 GB for large-v2/v3 - and
    # four overlapping ones pushed a 15 GB machine to 1 GB free with the commit
    # limit nearly exhausted. The OS releases the lock if this process dies.
    lock = _conversion_lock(args.out.parent)

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
    print(f"converted -> {args.out}  ({size:.2f} GB, {mels} mel bins)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
