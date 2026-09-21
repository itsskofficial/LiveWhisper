# Changelog

## 1.0.0

The first release meant for people other than its author. Everything below was
measured on a mid-range laptop (RTX 4060 8 GB, 16-core CPU); the scripts that
produced each number are in `tests/`, and their output in `tests/results/`.

### A desktop app

- **One installer, no command line.** `LiveWhisper-Setup-1.0.0.exe` (100 MB)
  installs per user, without administrator rights. No Python, no pip.
- **Set up on first launch.** You pick your languages, and it downloads what
  your PC should run, with progress and resume: the speech model, GPU support
  (just the two cuBLAS files Whisper needs, 550 MB instead of 1.3 GB), the
  formatting model, and faster English on a GPU.
- **An app window** for your History (searchable, kept on your PC), words to
  know, learned spellings, languages and their accuracy models, AI settings,
  and shortcuts you set by pressing them.
- **A recording pill** at the bottom of the screen: a live waveform, ✓ to
  finish, ✕ to discard, and short notes in place of pop-ups. It never takes
  focus from the field you are dictating into.
- **Language models built in.** Formatting and `Ctrl+Alt+W` run on llama.cpp
  inside the app, on any GPU (NVIDIA, AMD, Intel) or the processor. Ollama is
  no longer needed. The writing model is unloaded as soon as it has written, so
  dictation keeps the GPU.
- **No PyTorch.** The romanizer's character model now runs on numpy, with
  identical output on 2,400 test words and faster than before. The language
  models download already converted.
- **One copy at a time.** Launching it again opens the running app.

### Dictation

- **Press, speak, press** (`Ctrl+Alt+Space`). Records your microphone only;
  meetings with system audio are what notes mode (`Ctrl+Alt+N`) is for.
- **Twelve South Asian languages written the way you type them** — Hinglish,
  Tanglish, Banglish and nine more — plus English.
- **Your spelling, learned.** Correct `mujhe` to `muze` twice and every word
  with ज follows. Corrections to the Hinglish model's text are learned too
  (`karunga` → `karoonga`); only spelling changes are, never edits like
  `meeting` → `meetings`.
- **Nothing invented is pasted.** Given silence or a muted microphone, Whisper
  makes up text ("aapke liye aapke liye…"); that is caught and you are told
  nothing was heard. No false alarm on 239,516 real sentences.
- **Finished text, not a transcript.** Spoken punctuation ("comma", "new
  paragraph", "bullet point"), corrections said out loud ("Monday, I mean
  Tuesday", "kal matlab parso"), emails, percentages and money, and a style per
  app: no trailing full stop in chat, identifiers in code editors
  (`camel case user name` → `userName`).
- **A 640 MB local model for punctuation**: 67% of test cases exactly as a
  careful typist would write them, against 40% for rules alone. It can add
  punctuation and capitals but never change a word.
- **Names from your screen** help the names in the thread you are replying to
  come out right. Read locally, used once, never stored or sent.
- **Voice shortcuts**: dictate a cue alone and saved text is pasted instead.

### Speed

- About 0.9 s to text for a four-second English sentence, 1.1 s for Hindi with
  the Hinglish model, on mains power. On battery Windows caps a laptop GPU and
  it is several times slower (6 s measured); the README says what to change.
- With a Groq key: about 2 s from the end of speech to pasted text, 1 s of it
  the transcription itself (English, measured end to end).
- The language is worked out while you are still speaking.
- English is decoded by a smaller model when installed, 30–55% faster with no
  loss in accuracy.
- The first dictation after launch is no longer slow.

### Accuracy

- Long dictations no longer lose words: paragraphs used to come back missing a
  quarter of what was said.
- Accuracy models for all twelve languages, chosen by measurement and
  downloaded in one click (native-script Hindi at 10% word error), and a
  144 MB Hinglish model for machines with no GPU. Every language can be written
  in its own script or romanized; the README has both numbers per language.
- Spoken punctuation survives Whisper's own: "Hi Rahul comma" is no longer
  heard as a name, and never doubles a comma.
- Words to know also fix one-letter near misses ("full request" → "pull
  request").

### Writing for you

- `Ctrl+Alt+W`: press, say what to write, press again. It reads the message on
  screen and pastes a reply in your voice.
- `Ctrl+Alt+F`: fixes the grammar in the field you are in, keeping your
  lowercase and slang.
- Runs on the built-in local model, or Groq with a key. A missing model is
  reported before you speak, with where to get it.

### Everything else

- A log at `%LOCALAPPDATA%\LiveWhisper\livewhisper.log` (Settings → Open log),
  with one line per dictation saying how long each stage took.
- Uninstalling offers to remove your settings and the downloaded models too.

### Known limits

- Gujarati, Punjabi, Malayalam and Marathi still get about half the words
  wrong, and Sinhala most of them: no better openly licensed model exists yet.
- The installer is not code-signed yet, so Windows asks for confirmation the
  first time.
- Windows 10/11 only.
