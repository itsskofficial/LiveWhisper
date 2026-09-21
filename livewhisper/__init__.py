"""LiveWhisper - hotkey-driven system-audio transcription for Windows."""

import os

from dotenv import load_dotenv

from . import _cuda, paths

# The installed app keeps downloaded models with its other large files, where
# uninstalling can find them, instead of in the shared ~/.cache.
if paths.FROZEN:
    os.environ.setdefault("HF_HOME", str(paths.CACHE / "huggingface"))

# Must happen before anything imports faster_whisper / ctranslate2.
_cuda.register()

# Real environment variables win over .env, so an exported key still overrides.
load_dotenv(paths.ENV)

__version__ = "1.0.0"
