# Changelog

## 1.1.0 - 2026-09-23

### Fixed

- **No more empty terminal windows piling up.** Each time the app checked the
  graphics card it opened a console window, and Windows Terminal left every
  one on the desktop as an empty see-through frame - 421 of them after a day,
  stacked over the LiveWhisper window and catching its clicks. The AI page
  also took about 5 s to open because of them; it now opens in under 1 s.
- **Spelling corrections are learned inside a longer message.** A correction
  was aligned word by word from the start of the box, so with an earlier
  dictation still in it, a fix to the second line was never seen - correcting
  "tujhe" to "tuze" and then "mujhe" to "muze" in one message did not form the
  "jh" -> "z" habit. It now learns from the stretch of the box that was the
  last dictation.
- **A dropped connection no longer fails a model download.** Installing the
  1.5 GB Marathi model broke 7 MB in and gave up, though each file is written
  to a part file that can be resumed. It now carries on from where it stopped,
  and an attempt that moved the file forward does not count against the
  retries - the same download then completed over a connection that broke
  five times.

### Added

- **Replies to an email are written as an email.** Ctrl+Alt+W used to answer
  an email with one line ("Sure, I'll be there.") - no greeting, no sign-off.
  A reply to an email now opens with the sender's first name and ends with
  yours, taken from the new `actions.sign_as` setting or your Windows account.
  The app's own writing model ignored the instruction, so it is done after the
  model: on tests/bench_compose.py the built-in model went from 5 to 8 of 8
  usable replies, Groq from 7 to 8. Chat replies are unchanged.
- **Marathi is heard as Marathi.** Whisper labelled Marathi speech Hindi and
  wrote it as Hindi; on a new 40-sentence code-switched set it got the
  language right on 22% of held-out clips. It now reconsiders both from the
  detection score and from the words written, and gets 59% right, with no
  Hindi clip turned into Marathi. Only for people who dictate in both
  ([ADR 0015](docs/adr/0015-hear-marathi-as-marathi.md)).
- **Better Marathi, Punjabi and Malayalam models.** AI4Bharat's IndicWhisper,
  measured on FLEURS through the app: Marathi 47.2% -> 26.5% of words wrong,
  Punjabi 60.9% -> 40.3%, Malayalam 61.3% -> 50.6%, and each 1.5 GB instead of
  3-6 GB. On the README's 20-clip measure, Marathi words are now spelled the
  way people write them 64.7% of the time against 49.3%, Punjabi 72.5% against
  53.0%, Malayalam 69.8% against 60.3%. Kannada, Gujarati, Telugu and Urdu
  were no better and keep their models
  ([ADR 0016](docs/adr/0016-indicwhisper-specialists.md)).
- **Polish my English (Beta)**, off by default, on the AI page. With Online
  on, English dictation is rewritten the way you would have typed it: false
  starts, repeated words and filler removed, grammar fixed. A rewrite that
  changes a name, number, link, "not" or "maybe", answers a question or adds
  anything you did not say is thrown away and the formatted text pasted
  instead. On 28 held-out dictations it brought the text from 35 to 11-17 word
  edits away from a careful typist's version (two runs), with nothing unsafe
  pasted (`tests/bench_polish.py`). Not used for Hinglish, other languages, code
  editors or Ctrl+Alt+W.

### Project

- Documentation reorganised: [docs/](docs/) has an index, the architecture,
  the development and release workflow, the evaluation method and results, and
  architecture decision records for every major choice
  ([docs/adr/](docs/adr/)).
- Tests, developer scripts and experiments moved out of the repository root
  into `tests/`, `scripts/` and `experiments/`, each with a README.
- CI runs on every push (`.github/workflows/tests.yml`).
- The command-line installer (`install.ps1`) is retired; the Setup.exe
  replaces it.

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
- **Online, as one switch.** Speech, formatting and writing all move to Groq
  together, and all fall back to this PC when Groq cannot answer. Languages
  with their own downloaded model stay here, where they are more accurate.
  Formatting online is the most accurate option measured: 71% of cases exactly
  right (gpt-oss-20b), against 67% for the local model and 40% for rules.

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
- Runs on the built-in local model, or on Groq when Online is on
  (gpt-oss-120b; Groq's retired Llama models, and Python's default user agent,
  which Groq's firewall refuses, had both broken it). A missing model is
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
