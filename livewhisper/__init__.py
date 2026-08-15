"""LiveWhisper - hotkey-driven system-audio transcription for Windows."""

from pathlib import Path

from dotenv import load_dotenv

from . import _cuda

# Must happen before anything imports faster_whisper / ctranslate2.
_cuda.register()

# Real environment variables win over .env, so an exported key still overrides.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

__version__ = "0.1.0"
