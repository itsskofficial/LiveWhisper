# 0005. Ship a per-user Setup.exe; download models from inside the app

- **Status:** Accepted
- **Date:** 2026-09-21

## Context

Up to 0.2 the app was installed with a PowerShell script that created a
virtualenv and ran pip - acceptable for developers, not for the people the app
is for. The models (several gigabytes, depending on the GPU and languages)
cannot sensibly go in an installer.

## Decision

- PyInstaller builds one folder (`packaging/LiveWhisper.spec`); Inno Setup
  wraps it into `LiveWhisper-Setup-<version>.exe` (`packaging/installer.iss`),
  about 100 MB.
- Per-user install to `%LOCALAPPDATA%\Programs\LiveWhisper`, no
  administrator rights. Settings in `%APPDATA%\LiveWhisper`, models in
  `%LOCALAPPDATA%\LiveWhisper` (`livewhisper/paths.py`).
- First launch asks for languages and downloads what this machine should run,
  with progress, resume, cancel and integrity checks (`livewhisper/components.py`).
  The config is fitted to the hardware on creation (`hardware.fit`).
- Setup closes a running copy itself and restarts it after a silent upgrade;
  uninstall offers to remove the downloaded models.
- One instance at a time (`livewhisper/instance.py`).

## Consequences

- No Python, no command line for users. The old `install.ps1` is retired.
- About 25 minutes of downloading at 4 MB/s before the first dictation on a
  GPU machine. Downloading the small turbo model first would shorten that.
- The installer is not code-signed yet, so SmartScreen warns on first run.
