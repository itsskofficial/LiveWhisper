# Development

Everything needed to work on LiveWhisper from source, test it, build the
installer and ship a release.

## Set up

Windows 10/11, Python 3.12, an NVIDIA GPU for anything involving speech (the
text-only tests run without one).

```powershell
git clone https://github.com/itsskofficial/LiveWhisper.git
cd LiveWhisper
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run.py            # the app, with its window
```

A source checkout keeps its config, profile, history and downloaded models in
the repo folder (all gitignored), so it never touches an installed copy's data
in `%APPDATA%` / `%LOCALAPPDATA%`. Set `LIVEWHISPER_HOME` to put them elsewhere.

`scripts/check_setup.py` diagnoses a machine (audio devices, CUDA, keys);
`scripts/verify.py` exercises every feature against the real models.

## Layout

```
livewhisper/     the app - see docs/architecture.md
  ui/index.html  the app window (one self-contained page)
  script/        romanization
data/            lexicons and the character model (shipped)
assets/          icons
packaging/       PyInstaller spec, Inno Setup script, build.py, release notes
tests/           unit suites (test_*), end-to-end and evaluation harnesses
  results/       every evaluation's output, committed
experiments/     one-off measurements behind early decisions
scripts/         developer utilities
tools/           rebuild the lexicons, train and export the character model
docs/            this documentation; docs/adr/ holds the decision records
```

## Tests

| Command | What | Needs |
| --- | --- | --- |
| `python run_tests.py` | 25 fast suites: formatting, romanization, learning, routing, the window API, the downloader, guards | nothing |
| `python run_tests.py --audio` | plus speech end to end from recorded clips | GPU, models |
| `python run_tests.py --all` | plus Groq fallback and `scripts/verify.py` | GPU, models, Groq key |
| `python tests/e2e_app.py --routes D:/models/ct2` | the real app: speech played through the speakers, captured by loopback, pasted into Notepad | GPU, models; leave the PC alone for ~15 min |
| `python tests/e2e_app.py --online ...` | the same with the Online switch on | Groq key |
| `python tests/ui_tour.py [--dark] [--onboarding]` | opens the window, visits every page, screenshots each, reports JS errors | WebView2 |

Every suite is a plain script that prints `[ ok ]` / `[ FAIL ]` lines and exits
non-zero on failure, so each can be run on its own.

Evaluations (accuracy per language, formatting quality, latency) are described
in [evaluation.md](evaluation.md).

## House rules

- **Measure before shipping a change that affects output.** Accuracy claims in
  code comments, the README and the changelog each name the script that
  produced them. A model or rule that did not win on held-out data does not go
  in (see [ADR 0003](adr/0003-specialist-models-by-measurement.md)).
- **Comments explain why**, usually with the incident or number that forced the
  decision. The code already says what.
- **A test for every bug found end to end** - most suites are named after what
  they protect ("no invented text", "learning from Hinglish").
- Never write a secret to a file. Keys are read from the environment or the
  per-user `.env` the app manages.

## Building the installer

```powershell
.venv\Scripts\python packaging\build.py
```

It fetches the pinned llama.cpp runtime into `vendor/llama` if missing
(`packaging/fetch_llama.py`), builds the app folder with PyInstaller
(`packaging/LiveWhisper.spec`) into `build/dist/LiveWhisper`, then compiles
`packaging/installer.iss` with Inno Setup 6 into
`build/installer/LiveWhisper-Setup-<version>.exe` (about 100 MB). The version
comes from `livewhisper/__init__.py`.

## Releasing

1. Bump `__version__` in `livewhisper/__init__.py`; add the version to
   `CHANGELOG.md`; update `packaging/RELEASE_NOTES.md`.
2. `python run_tests.py` - all suites pass.
3. `python packaging/build.py`.
4. Test the installer on this machine, in this order:
   - upgrade over a running copy (it must close, update and restart it);
   - a clean install (move `%APPDATA%\LiveWhisper` and
     `%LOCALAPPDATA%\LiveWhisper` aside first) through first-run downloads;
   - dictate with your own voice, with Online off and on;
   - uninstall.
5. Push, then draft the release with the installer attached:
   `gh release create vX.Y.Z build/installer/LiveWhisper-Setup-X.Y.Z.exe --draft --notes-file packaging/RELEASE_NOTES.md`
6. Publish the draft. The README's download link points at the latest release.

The converted per-language models are hosted as `itsskofficial/livewhisper-*` on
Hugging Face (see [ADR 0007](adr/0007-no-pytorch-at-runtime.md)); publishing a
new one means converting it with `scripts/convert_ct2.py` and uploading it with
`scripts/publish_specialist.py`, which needs a model card crediting the
original beside the folder (`<name>.card.md`) and reads `HF_TOKEN` from the
environment - pass it inline for that one command and keep it out of files.

## CI

`.github/workflows/tests.yml` runs `run_tests.py` on Windows (Python 3.10 and
3.12) and `ruff` on every push and pull request. Runners have no GPU and no
sound card: speech suites use stand-ins and the real-speech ones stay behind
`--audio`.
