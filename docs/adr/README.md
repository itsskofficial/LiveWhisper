# Architecture decision records

Why LiveWhisper is built the way it is. One decision per file, never
rewritten: a changed decision gets a new record that supersedes the old.
New ones start from [0000-template.md](0000-template.md).

| # | Decision | Status |
| --- | --- | --- |
| 0001 | [Record architecture decisions](0001-record-architecture-decisions.md) | Accepted |
| 0002 | [Romanize after transcription instead of asking the speech model for Latin](0002-romanize-after-transcription.md) | Accepted, with one exception (see Consequences) |
| 0003 | [Route each language to its own model, chosen only by measurement](0003-specialist-models-by-measurement.md) | Accepted |
| 0004 | [Run everything on the user's PC by default](0004-local-first.md) | Accepted; extended by [0012](0012-online-as-one-switch.md) |
| 0005 | [Ship a per-user Setup.exe; download models from inside the app](0005-desktop-installer-and-in-app-downloads.md) | Accepted |
| 0006 | [Draw the window with WebView2 and the pill as a layered Win32 window](0006-webview2-window-and-layered-pill.md) | Accepted |
| 0007 | [No PyTorch at runtime](0007-no-pytorch-at-runtime.md) | Accepted |
| 0008 | [Run the formatting and writing models with a bundled llama.cpp](0008-built-in-llama-cpp-runner.md) | Accepted |
| 0009 | [GPU support is two cuBLAS files, and the CPU until they arrive](0009-gpu-support-as-cublas-only.md) | Accepted |
| 0010 | [The formatting model may add punctuation, never change words](0010-formatter-never-changes-words.md) | Accepted |
| 0011 | [Learn from corrections by reading the field at the next dictation](0011-learn-at-the-next-dictation.md) | Accepted |
| 0012 | [Online is one switch, and languages with their own model stay local](0012-online-as-one-switch.md) | Accepted |
| 0013 | [Never paste what was not said, or where it was not meant](0013-never-paste-what-was-not-said.md) | Accepted |
