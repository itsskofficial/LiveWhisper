# AGENTS.md

LiveWhisper: a Windows voice-dictation desktop app (Python, shipped as a
PyInstaller + Inno Setup `Setup.exe`). Start with
[docs/architecture.md](docs/architecture.md) for the map.

## Commands

Windows, Python 3.12, the venv at `.venv`. Run everything from the repo root.

- `.venv\Scripts\python run_tests.py` - the 25 fast suites; must stay green. Any suite also runs alone (`tests/test_<name>.py`).
- `.venv\Scripts\python run.py` - the app from source; it keeps its config and models in the repo folder, apart from an installed copy.
- `.venv\Scripts\python tests\ui_tour.py` - screenshots every page of the window and reports JS errors; run it after touching `livewhisper/ui/index.html`.
- `.venv\Scripts\python packaging\build.py` - builds `build/installer/LiveWhisper-Setup-<version>.exe`.

## How work is done here

- **Measure first.** A change to what the app delivers (transcripts, spelling, formatting, routing) ships with before/after numbers from a harness in [docs/evaluation.md](docs/evaluation.md), on data it was not tuned on. Numbers written in comments, docs or the changelog name the script that produced them.
- **Record decisions.** A product or scope decision gets a line in [docs/decisions.md](docs/decisions.md); a significant engineering one also gets an ADR in [docs/adr/](docs/adr/) from the template. Reversals get a new entry that supersedes the old.
- **Every bug found end to end gets a test** named for what it protects.
- **Comments say why**, usually citing the incident or measurement.
- Update `CHANGELOG.md` under *Unreleased* for anything a user would notice.

## Ask the maintainer first

- **Before running `tests/e2e_app.py` or any `--audio` suite**: they play speech through the speakers, open Notepad and take keyboard focus for 5-20 minutes.
- **Before publishing anything**: pushing a release, uploading models to Hugging Face, or creating GitHub releases. Draft releases are the default; the maintainer publishes.
- **Before downloading build tools or models** onto the machine.

## Secrets

API keys (Groq, Hugging Face, OpenRouter) live only in environment variables or the app's per-user `.env`. Pass one inline to the single command that needs it; keep it out of files, scripts, logs and commits.

## Gotchas

- **Backslashes in patch scripts.** Python written through a bash heredoc loses `\n`, `\b`, `\t` and `\1` (they become control characters or vanish, and `\` line continuations collapse). Write patch scripts to a file, or use a direct edit, whenever the text contains a backslash; then `grep` for control characters.
- **The window page** is loaded as a string (`window.AppWindow`); pywebview injects its bridge into the page's global scope, so the page's own globals avoid generic names (a global `keys` once broke every call).
- **Frozen app paths** all come from `livewhisper/paths.py`; child processes are spawned through `llm._spawn` so they do not inherit the bundle's DLL directory.
- **GPU numbers** on this laptop are only valid on mains power; on battery the GPU is capped at 210 MHz and local latency triples. Check `nvidia-smi` clocks before quoting speed.
