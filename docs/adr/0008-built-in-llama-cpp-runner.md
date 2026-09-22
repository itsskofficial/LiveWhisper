# 0008. Run the formatting and writing models with a bundled llama.cpp

- **Status:** Accepted
- **Date:** 2026-09-21

## Context

Formatting and Ctrl+Alt+W needed Ollama, a separate install most users would
not have. A 7B writing model left resident by Ollama also held 6 GB of an 8 GB
card, pushing Whisper out and making dictations take 12-40 s.

## Decision

Ship llama.cpp's `llama-server` (Vulkan build, pinned by
`packaging/fetch_llama.py`) and run it on demand (`livewhisper/llm.py`):
Qwen3 0.6B for formatting, kept loaded; Qwen 2.5 3B for writing, unloaded as
soon as it has written. The server is started on a private port with no
window, pointed at the discrete GPU (laptops list the integrated one first),
and put in a job object so it dies with the app. Its DLL search path is reset
when spawning: inherited from the frozen app, it had loaded the wrong copy of
ggml and silently run on the CPU.

## Consequences

- Works on NVIDIA, AMD and Intel GPUs, and on the CPU, with nothing else
  installed. Ollama still works as a fallback in a source checkout.
- The first run on a machine compiles Vulkan shaders (about 20 s, once, in the
  background).
- Formatting at 0.2-0.6 s on this machine's throttled GPU, as fast as Ollama's.
