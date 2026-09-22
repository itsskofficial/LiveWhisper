# Architecture

How LiveWhisper is put together as software. For the ideas behind it (scripts,
romanization, learning) read [how-it-works.md](how-it-works.md); for why each
piece is the way it is, the [decision records](adr/).

## The shape of it

One Windows process, `LiveWhisper.exe`, built with PyInstaller and installed
per user by an Inno Setup installer. It runs in the tray; the window and the
recording pill are views onto it.

```
                         ┌────────────────────────── LiveWhisper.exe ─────────────────────────┐
  hotkeys (keyboard) ───►│ main.App  ── state machine: IDLE → RECORDING → TRANSCRIBING → IDLE   │
  tray menu (pystray) ──►│   │                                                                 │
                         │   ├─ audio.Recorder        mic (and system audio for notes)         │
                         │   ├─ transcribe.*Backend   Local (faster-whisper) / Groq / Auto     │
                         │   ├─ guard                 drop text nobody said                    │
                         │   ├─ pipeline.Pipeline     script → romanize → vocab → format →     │
                         │   │                        habits → learn from last correction      │
                         │   ├─ output                paste into the window you started in     │
                         │   ├─ history               every dictation, on disk                 │
                         │   ├─ actions/providers     Ctrl+Alt+W / Ctrl+Alt+F                  │
                         │   ├─ overlay.RecordingOverlay  the pill (own thread, Win32)         │
                         │   └─ window.AppWindow      the window (WebView2 via pywebview)      │
                         └──────────────┬───────────────────────────────┬──────────────────────┘
                                        │ subprocess, job object        │ HTTPS (Online only)
                              llama-server.exe (vendor/llama)      Groq API
                              formatter / writer models
```

## Threads

| Thread | Owns | Why |
| --- | --- | --- |
| main | the app window (`webview.start`) | pywebview's WinForms backend requires it |
| overlay | the pill's Win32 window and message loop | animates at 30 fps whatever else is busy |
| pystray | the tray icon | its own message loop |
| one per hotkey press | `toggle_record`, `toggle_command`, ... | a slow handler must never wedge the keyboard hook |
| settle | language detection while you speak | takes an encoder pass off the wait after you stop |
| warm-up | model loading after launch or a settings change | first dictation is not the slow one |
| downloads | `components.Components` worker | one download at a time, cancellable |

`App._lock` serialises state changes. Everything that touches the window goes
through `window.Api`, which pywebview calls on its own threads.

## One dictation

1. **Press** `Ctrl+Alt+Space` → `App._start`: remembers the foreground window,
   reads the screen for names (`context.capture`), starts `audio.Recorder`, shows
   the pill, and starts the *settle* thread, which guesses the language every
   2 s on the audio so far (`LocalBackend.prime`).
2. **Press again** → `App._stop` → `_transcribe`:
   - `backend.transcribe(audio, hotwords, native)`. `AutoBackend` (Online)
     decides here: a language with its own downloaded model is decoded locally,
     everything else goes to Groq, and anything Groq cannot serve falls back to
     local. `LocalBackend` picks the model per language (`_model_for`), keeping
     at most `max_extra_models` loaded.
   - `guard.invented` drops looping or stock text from silence.
   - `Pipeline.process`: choose the script from the target field; romanize
     (`script.Romanizer`: lexicon → character model → letters) or respell a
     Hinglish model's Latin; remove fillers; fix vocabulary near misses; format
     (rules, then the formatting model, which may only add punctuation, capitals
     and line breaks); apply this app's habits.
   - `output.deliver` pastes, unless focus moved to another window, in which
     case the text stays on the clipboard.
   - `history.add`; the pill fades out.
3. **Next dictation** starts by reading the field again: if the user edited what
   was pasted, `Pipeline.learn_from_screen` learns the spelling change.

## Where things live

| What | Installed app | Source checkout |
| --- | --- | --- |
| Code, `data/`, `assets/`, UI page, default config, llama.cpp | `%LOCALAPPDATA%\Programs\LiveWhisper\_internal` (read-only) | repo |
| `config.yaml`, `profiles.json`, `history.jsonl`, `.env`, notes, transcripts | `%APPDATA%\LiveWhisper` | repo root |
| Speech models, cuBLAS, formatter/writer GGUFs, Hugging Face cache | `%LOCALAPPDATA%\LiveWhisper` | repo root (`models/`, `llm/`, …) |
| Log | `%LOCALAPPDATA%\LiveWhisper\livewhisper.log` | same |

All of it is resolved in one place, `livewhisper/paths.py`. `LIVEWHISPER_HOME`
overrides the per-user folders (tests use it).

## Local and Online

`processing: local | online` in the config is the single switch
(`window.processing_patch`). It sets:

| | local | online |
| --- | --- | --- |
| `transcription.backend` | `local` | `auto` (Groq, local fallback, local specialists) |
| `output.format.engine` | `auto` (built-in model) | `groq` (Groq, then built-in) |
| `actions.models.provider` | `auto` (built-in) | `groq` (Groq, then built-in) |

## Downloads after install

`components.py` owns them: cuBLAS (two DLLs lifted out of NVIDIA's PyPI wheel
with range requests), the speech model, per-language models (from
`itsskofficial/livewhisper-*` mirrors, already converted), and the two GGUF
models. Each download resumes, is CRC- or size-checked, and lands under a
temporary name until complete. `App.component_installed` reloads what changed.

## Failure behaviour

| Failure | Behaviour |
| --- | --- |
| No cuBLAS yet | speech runs on the CPU until it arrives (`LocalBackend._device`) |
| Groq down, out of credit, or rate-limited | local model; Groq benched for `fallback_cooldown_minutes` |
| Formatting model slow or missing | rules only (the timeout is 1.5 s local, 2.5 s online) |
| Focus moved during dictation | text left on the clipboard, never pasted elsewhere |
| Silence / muted mic | "Nothing was heard", nothing pasted |
| Model runner crashes | job object kills it with the app; the next request restarts it |
