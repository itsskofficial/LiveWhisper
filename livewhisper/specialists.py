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
    device: str = "gpu"            # gpu | cpu: which kind of machine it is for


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
    Specialist(
        "ta", "vasista22/whisper-tamil-medium", "ta-medium", 3.06, "apache-2.0",
        measured={"FLEURS word error": "23.2% (large-v3 56.9%)",
                  "delivered Tanglish": "22.4% (large-v3 51.8%)"},
        note="Whisper-medium fine-tuned on Tamil by SPRING Lab, IIT Madras. "
             "1.5 GB once converted."),
    Specialist(
        "te", "vasista22/whisper-telugu-medium", "te-medium", 3.06, "apache-2.0",
        measured={"FLEURS word error": "37.1% (large-v3 74.4%)",
                  "delivered Telugu romanized": "36.2% (large-v3 71.6%)"},
        note="Whisper-medium fine-tuned on Telugu by SPRING Lab, IIT Madras. "
             "1.5 GB once converted."),
    Specialist(
        # Measured decoding with the "hi" token, so no language override: the
        # route decodes with whatever detection chose. Oriserve's card suggests
        # "en"; that setting has not been measured here.
        "hi", "Oriserve/Whisper-Hindi2Hinglish-Prime", "hinglish-prime", 6.17,
        "apache-2.0", latin_output=True,
        measured={"delivered Hinglish, held-out": "19.1% (large-v3 22.0%)",
                  "delivered Hinglish, test": "19.5% (large-v3 24.4%)"},
        note="Writes Hinglish straight from audio, so English words stay English. "
             "Large-v3 sized: with the main model loaded too, allow ~6 GB of VRAM."),
    Specialist(
        # For machines without a usable GPU. Measured on the batched path the
        # app decodes with, scored after respelling as the app delivers it
        # (tests/rescore_delivered.py). The CPU default before it, `small`,
        # delivered 52.9% on the same clips in 2.5 s.
        "hi", "Oriserve/Whisper-Hindi2Hinglish-Swift", "hinglish-swift", 0.28,
        "apache-2.0", latin_output=True, device="cpu",
        measured={"delivered Hinglish, CPU": "25.6% (small 52.9%, large-v3 23.9%)",
                  "4-second dictation on CPU": "0.84 s (small 2.4 s)"},
        note="Whisper-base sized, 144 MB converted: close to large-v3 on Hindi "
             "and fast on an ordinary CPU."),
    Specialist(
        "pa", "DrishtiSharma/whisper-large-v2-punjabi", "pa-large-v2", 6.17,
        "apache-2.0",
        measured={"FLEURS word error": "60.9% (large-v3 79.8%)",
                  "delivered Punglish": "56.3% (large-v3 68.6%)"},
        note="Better than large-v3, but still gets more than half of words wrong - "
             "trained on Common Voice's small Punjabi set. Large-v2 sized, "
             "allow ~6 GB of VRAM with the main model."),
    Specialist(
        "ml", "rontroy/whisper-large-v3-malayalam-ct2", "ml-large-v3", 3.09,
        "apache-2.0", kind="ct2",
        measured={"FLEURS word error": "61.3% (large-v3 114.9%)",
                  "delivered Manglish": "58.8% (large-v3 109.0%)"},
        note="large-v3 writes Malayalam in Gurmukhi, Devanagari or Telugu script; "
             "this model writes Malayalam every time. Still gets most words "
             "wrong. Already converted, so install is a download only."),
    Specialist(
        "kn", "vasista22/whisper-kannada-medium", "kn-medium", 3.06, "apache-2.0",
        measured={"FLEURS word error": "32.3% (large-v3 67.4%)",
                  "delivered Kanglish": "30.2% (large-v3 59.8%)"},
        note="Whisper-medium fine-tuned on Kannada by SPRING Lab, IIT Madras. "
             "1.5 GB once converted; converting peaks near 7 GB of memory."),
    Specialist(
        "gu", "vasista22/whisper-gujarati-medium", "gu-medium", 3.06, "apache-2.0",
        measured={"FLEURS word error": "49.8% (large-v3 67.7%)",
                  "delivered Gujlish": "48.5% (large-v3 63.3%)"},
        note="Clearly better than large-v3, but still misses about half the words. "
             "Whisper-medium fine-tuned by SPRING Lab, IIT Madras; 1.5 GB converted."),
    Specialist(
        "mr", "DrishtiSharma/whisper-large-v2-marathi", "mr-large-v2", 6.17,
        "apache-2.0",
        measured={"FLEURS word error": "47.2% (large-v3 78.7%)",
                  "delivered Minglish": "51.6% (large-v3 73.2%)"},
        note="Large-v2 sized: as fast as large-v3 on the same clips (2.5x "
             "realtime), allow ~6 GB of VRAM with the main model. Converting "
             "peaks near 11.5 GB of memory."),
]


def models_dir(cfg: dict | None = None) -> Path:
    local = ((cfg or {}).get("transcription") or {}).get("local") or {}
    return Path(local.get("models_dir") or ROOT / "models")


def candidates(lang: str) -> list:
    return [s for s in CATALOGUE if s.lang == lang]


def recommended(lang: str, cpu: bool = False) -> Specialist | None:
    """The measured specialist for a language and this kind of machine.

    A GPU entry is the most accurate model that fits beside large-v3; a CPU
    entry is the one that stays fast without a GPU. Neither is offered to the
    other kind of machine: a large-v3-sized model on a CPU takes tens of seconds
    per dictation, and a CPU model on a GPU gives away accuracy for nothing.
    """
    want = "cpu" if cpu else "gpu"
    return next((s for s in candidates(lang) if s.measured and s.device == want), None)


# ------------------------------------------------------------------ convert

def convert(src: Path, out: Path, quantization: str = "float16",
            progress=print) -> Path:
    """HF Whisper weights -> CTranslate2, fixing the two things that break loading.

    Older fine-tunes ship no tokenizer.json, which faster-whisper requires, and
    large-v3 derivatives need their 128-mel preprocessor config or faster-whisper
    assumes 80 and transcribes garbage.

    Takes the machine-wide conversion lock and waits for enough memory first -
    see livewhisper.resources for why skipping that crashes silently.
    """
    from . import resources

    weights_gb = sum(f.stat().st_size for f in list(src.glob("*.bin")) +
                     list(src.glob("*.safetensors"))) / 1e9
    lock = resources.acquire_conversion_slot(
        out.parent, resources.memory_needed_gb(weights_gb), progress=progress)
    try:
        # Imported only once there is room: torch and transformers alone commit
        # over a gigabyte, which a waiting install would otherwise hold.
        import ctranslate2
        from transformers import WhisperProcessor, WhisperTokenizerFast
        return _convert_locked(src, out, quantization, ctranslate2,
                               WhisperProcessor, WhisperTokenizerFast)
    finally:
        resources.release(lock)


def _convert_locked(src: Path, out: Path, quantization: str, ctranslate2,
                    WhisperProcessor, WhisperTokenizerFast) -> Path:
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
        convert(src, out, progress=progress)
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
    p.add_argument("--cpu", action="store_true", default=None,
                   help="pick the CPU model (default: detected from the machine)")
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
        cpu = args.cpu
        if cpu is None:
            from .hardware import detect
            cpu = not detect().has_cuda
        spec = recommended(args.lang, cpu=cpu)
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
