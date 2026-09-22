# 0004. Run everything on the user's PC by default

- **Status:** Accepted; extended by [0012](0012-online-as-one-switch.md)
- **Date:** before 0.2; recorded 2026-09-22

## Context

Dictation hears everything a person says and the screen they reply to. Cloud
dictation tools send it all away, count words and charge monthly. Consumer
GPUs can now run Whisper large-v3 in about a second.

## Decision

Speech, romanization, formatting, writing and learning all run locally by
default. The screen is read locally and used once, never stored or sent. No
account and no telemetry. Cloud use is opt-in and visible.

## Consequences

- Works offline and costs nothing per word.
- Needs a download of 1.5-6 GB on first launch, and a GPU for the best
  experience; a laptop on battery is several times slower.
- The app must manage models itself ([0005](0005-desktop-installer-and-in-app-downloads.md),
  [0008](0008-built-in-llama-cpp-runner.md), [0009](0009-gpu-support-as-cublas-only.md)).
