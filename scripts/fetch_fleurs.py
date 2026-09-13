#!/usr/bin/env python
"""Fetch real human speech for evaluation from Google's FLEURS dataset.

The synthetic TTS clips in scripts/make_test_audio.py are clean, short and
spoken by a voice engine - useful for checking wiring, useless for judging
accuracy. FLEURS is people reading sentences aloud, with the reference
transcript, for 12 of our 13 target languages (no Sinhala). CC BY 4.0.

Each test archive is 250-720 MB. Nothing here downloads a whole one: the
tarball is streamed and reading stops once enough clips have been pulled out.

    python scripts/fetch_fleurs.py build/fleurs --n 40
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import tarfile
from pathlib import Path

import requests

BASE = "https://huggingface.co/datasets/google/fleurs/resolve/main/data"

# our code -> FLEURS config
LANGS = {
    "hi": "hi_in", "bn": "bn_in", "ur": "ur_pk", "pa": "pa_in", "mr": "mr_in",
    "te": "te_in", "ta": "ta_in", "gu": "gu_in", "kn": "kn_in", "ml": "ml_in",
    "sd": "sd_in", "en": "en_us",
}


def transcripts(cfg: str, split: str) -> dict:
    """file name -> raw transcription."""
    r = requests.get(f"{BASE}/{cfg}/{split}.tsv", timeout=60)
    r.raise_for_status()
    out = {}
    for row in csv.reader(io.StringIO(r.content.decode("utf-8")),
                          delimiter="\t", quoting=csv.QUOTE_NONE):
        # id, file_name, raw_transcription, transcription, phonemes, samples, gender
        if len(row) >= 3 and row[1].endswith(".wav"):
            out.setdefault(row[1], row[2])
    return out


def fetch(code: str, out: Path, n: int, split: str) -> list:
    cfg = LANGS[code]
    refs = transcripts(cfg, split)
    dest = out / code
    dest.mkdir(parents=True, exist_ok=True)
    got = []
    with requests.get(f"{BASE}/{cfg}/audio/{split}.tar.gz", stream=True,
                      timeout=60) as r:
        r.raise_for_status()
        r.raw.decode_content = True
        with tarfile.open(fileobj=r.raw, mode="r|gz") as tar:
            for member in tar:
                name = Path(member.name).name
                if not member.isfile() or name not in refs:
                    continue
                data = tar.extractfile(member).read()
                (dest / name).write_bytes(data)
                got.append({"name": f"{code}/{name}", "lang": code,
                            "reference": refs[name]})
                if len(got) >= n:
                    break
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--n", type=int, default=40, help="clips per language")
    ap.add_argument("--split", default="test")
    ap.add_argument("--langs", default=",".join(LANGS))
    args = ap.parse_args()

    manifest_path = args.out / "manifest.json"
    manifest = (json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest_path.exists() else [])
    have = {m["lang"] for m in manifest}

    for code in args.langs.split(","):
        if code in have:
            print(f"{code}: already fetched")
            continue
        try:
            clips = fetch(code, args.out, args.n, args.split)
        except Exception as exc:
            print(f"{code}: FAILED {type(exc).__name__}: {exc}")
            continue
        manifest += clips
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False,
                                            indent=1), encoding="utf-8")
        print(f"{code}: {len(clips)} clips", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
