# scripts

Developer utilities. Run from the repository root with the project's venv.

| Script | Does |
| --- | --- |
| `check_setup.py` | diagnose a machine: audio devices, loopback, CUDA, keys |
| `verify.py` | exercise every feature against the real models and report what works |
| `convert_ct2.py` | convert a Hugging Face Whisper fine-tune to CTranslate2 (needs torch + transformers) |
| `fetch_fleurs.py` | download FLEURS recordings for evaluation into `build/fleurs` |
| `make_test_audio.py` | synthesise speech clips for the audio test suites |
| `demo_seed.py` | fill a profile with realistic history, for demos |

The installer's build scripts are in `packaging/`; data-building tools in `tools/`.
