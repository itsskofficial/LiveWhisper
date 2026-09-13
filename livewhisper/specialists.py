"""Per-language specialist speech models: list, install, remove.

large-v3 is one model for 99 languages, and for several South Asian languages
it is simply weak - on real Bengali speech it gets 73% of words wrong while
detecting the language perfectly. Community fine-tunes trained on one language
often do far better. This module makes using one a single command:

    python -m livewhisper.specialists list
    python -m livewhisper.specialists install bn
    python -m livewhisper.specialists remove bn

`install` downloads the fine-tune, converts it to the CTranslate2 format
faster-whisper runs (half the size in float16, several times faster), and writes
the route into config.yaml. The app switches to it whenever it detects that
language; see LocalBackend._model_for. Detection itself stays on the main model.

The catalogue only lists models that were measured against large-v3 on the same
FLEURS clips with tests/bench_asr.py. Numbers are delivered word error rate: the
text the user receives, after romanization, against every accepted spelling.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Specialist:
    lang: str
    repo: str
    name: str
    size_gb: float
    licence: str
    kind: str = "convert"          # convert: HF weights | ct2: already converted
    latin_output: bool = False     # writes romanized text itself
    language: str | None = None    # token to decode with, if not the language
    measured: dict = field(default_factory=dict)   # metric -> value, bench_asr
    note: str = ""


# Filled from tests/bench_asr.py runs. An entry without measurements is a
# candidate under evaluation and is not offered by `install` without --force.
CATALOGUE: list = [
    Specialist(
        "bn", "bengaliAI/tugstugi_bengaliai-asr_whisper-medium", "bn-medium",
        3.06, "apache-2.0",
        measured={"FLEURS word error": "20.9% (large-v3 73.3%)",
                  "delivered Banglish": "31.7% (large-v3 66.5%)"},
        note="Winner of the Bengali.AI speech recognition competition. Half "
             "the size of large-v3 and faster, 1.5 GB once converted."),
]


def models_dir(cfg: dict | None = None) -> Path:
    local = ((cfg or {}).get("transcription") or {}).get("local") or {}
    return Path(local.get("models_dir") or ROOT / "models")


def candidates(lang: str) -> list:
    return [s for s in CATALOGUE if s.lang == lang]


def recommended(lang: str) -> Specialist | None:
    """The measured specialist for a language, if one beat large-v3."""
    return next((s for s in candidates(lang) if s.measured), None)


# ------------------------------------------------------------------ convert

def convert(src: Path, out: Path, quantization: str = "float16") -> Path:
    """HF Whisper weights -> CTranslate2, fixing the two things that break loading.

    Older fine-tunes ship no tokenizer.json, which faster-whisper requires, and
    large-v3 derivatives need their 128-mel preprocessor config or faster-whisper
    assumes 80 and transcribes garbage.
    """
    import ctranslate2
    from transformers import WhisperProcessor, WhisperTokenizerFast

    work = out.with_name(out.name + ".hf")
    work.mkdir(parents=True, exist_ok=True)
    WhisperTokenizerFast.from_pretrained(src).save_pretrained(work)
    try:
        WhisperProcessor.from_pretrained(src).feature_extractor.save_pretrained(work)
    except Exception:
        mels = json.loads((src / "config.json").read_text()).get("num_mel_bins", 80)
        (work / "preprocessor_config.json").write_text(json.dumps({
            "feature_extractor_type": "WhisperFeatureExtractor", "feature_size": mels,
            "sampling_rate": 16000, "hop_length": 160, "chunk_length": 30,
            "n_fft": 400, "padding_value": 0.0, "return_attention_mask": False}))
    for f in list(src.glob("*.json")) + list(src.glob("*.safetensors")) + \
            list(src.glob("pytorch_model.bin")):
        target = work / f.name
        if not target.exists():
            shutil.copy2(f, target)
    ctranslate2.converters.TransformersConverter(
        str(work), copy_files=["tokenizer.json", "preprocessor_config.json"],
        load_as_float16=True).convert(str(out), quantization=quantization, force=True)
    shutil.rmtree(work, ignore_errors=True)
    return out


# ------------------------------------------------------------------ install

def install(spec: Specialist, config_path: Path, progress=print) -> Path:
    from huggingface_hub import snapshot_download

    from . import config as cfgio
    from .hub import plain_http

    plain_http()
    cfg = cfgio.load(config_path)
    base = models_dir(cfg)
    out = base / spec.name
    progress(f"Downloading {spec.repo} (~{spec.size_gb:.1f} GB)...")
    if spec.kind == "ct2":
        # A plain folder, never the shared cache: the cache is built from
        # symlinks, which Windows refuses without Developer Mode.
        snapshot_download(spec.repo, local_dir=str(out))
    else:
        src = base / f"{spec.name}.src"
        snapshot_download(spec.repo, local_dir=str(src), allow_patterns=[
            "*.json", "*.safetensors", "pytorch_model.bin", "*.txt", "*.model"])
        progress("Converting for faster-whisper...")
        convert(src, out)
        shutil.rmtree(src, ignore_errors=True)

    route: dict | str = str(out)
    if spec.latin_output or spec.language:
        route = {"path": str(out)}
        if spec.latin_output:
            route["latin_output"] = True
        if spec.language:
            route["language"] = spec.language
    local = cfg.setdefault("transcription", {}).setdefault("local", {})
    if not local.get("models"):
        local["models"] = {}
    local["models"][spec.lang] = route
    cfgio.save(config_path, cfg)
    progress(f"Installed. {spec.lang} now decodes with {spec.name}; restart the app.")
    return out


def remove(lang: str, config_path: Path, delete_files: bool = True, progress=print) -> None:
    from . import config as cfgio

    cfg = cfgio.load(config_path)
    models = (((cfg.get("transcription") or {}).get("local") or {}).get("models") or {})
    route = models.pop(lang, None)
    if route is None:
        progress(f"No specialist configured for {lang}.")
        return
    cfgio.save(config_path, cfg)
    path = Path(route["path"] if isinstance(route, dict) else route)
    if delete_files and path.is_dir() and path.parent == models_dir(cfg):
        shutil.rmtree(path, ignore_errors=True)
    progress(f"Removed the {lang} specialist; {lang} decodes with the main model again.")


# ---------------------------------------------------------------------- cli

def main(argv: list | None = None) -> int:
    from .console import setup as _console
    _console()

    ap = argparse.ArgumentParser(prog="python -m livewhisper.specialists")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("install")
    p.add_argument("lang")
    p.add_argument("--force", action="store_true",
                   help="install an unmeasured candidate anyway")
    p = sub.add_parser("remove")
    p.add_argument("lang")
    p.add_argument("--keep-files", action="store_true")
    ap.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    args = ap.parse_args(argv)

    if args.cmd == "list":
        if not CATALOGUE:
            print("No specialists catalogued yet.")
        for s in CATALOGUE:
            status = ", ".join(f"{k} {v}" for k, v in s.measured.items()) or "not yet measured"
            print(f"{s.lang}  {s.name:<18} {s.size_gb:>4.1f} GB  {s.licence:<11} {status}")
            if s.note:
                print(f"      {s.note}")
        return 0

    if args.cmd == "install":
        spec = recommended(args.lang)
        if spec is None and args.force and candidates(args.lang):
            spec = candidates(args.lang)[0]
        if spec is None:
            print(f"No measured specialist beats large-v3 for {args.lang}. "
                  f"Candidates: {[s.name for s in candidates(args.lang)] or 'none'}")
            return 1
        install(spec, args.config)
        return 0

    remove(args.lang, args.config, delete_files=not args.keep_files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
