# Changelog

## 1.0.0

The first release meant for people other than its author. Everything below was
measured on a mid-range laptop (RTX 4060 8 GB, 16-core CPU); the scripts that
produced each number are in `tests/`, and their output in `tests/results/`.

### Dictation

- **Press, speak, press** (`Ctrl+Alt+Space`). Records your microphone only;
  meetings with system audio are what notes mode (`Ctrl+Alt+N`) is for.
- **Twelve South Asian languages written the way you type them** — Hinglish,
  Tanglish, Banglish and nine more — plus English.
- **Your spelling, learned.** Correct `mujhe` to `muze` twice and every word
  with ज follows.
- **Finished text, not a transcript.** Spoken punctuation ("comma", "new
  paragraph", "bullet point"), corrections said out loud ("Monday, I mean
  Tuesday", "kal matlab parso"), emails, percentages and money, and a style per
  app: no trailing full stop in chat, identifiers in code editors
  (`camel case user name` → `userName`).
- **A 522 MB local model for punctuation**, if Ollama is installed: 67% of test
  cases exactly as a careful typist would write them, against 40% for rules
  alone. It can add punctuation and capitals but never change a word.
- **Names from your screen** help the names in the thread you are replying to
  come out right. Read locally, used once, never stored or sent.
- **Voice shortcuts**: dictate a cue alone and saved text is pasted instead.

### Speed

- About 0.9 s to text for a four-second English sentence, 1.1 s for Hindi with
  the Hinglish model, on mains power. A laptop on battery is about three times
  slower; the README says why.
- The language is worked out while you are still speaking.
- English is decoded by a smaller model when installed, 30–55% faster with no
  loss in accuracy.
- The first dictation after launch is no longer slow.

### Accuracy

- Long dictations no longer lose words: paragraphs used to come back missing a
  quarter of what was said.
- Language-specialist models for eight languages, chosen by measurement, and a
  144 MB Hinglish model for machines with no GPU.

### Writing for you

- `Ctrl+Alt+W`: press, say what to write, press again. It reads the message on
  screen and pastes a reply in your voice.
- `Ctrl+Alt+F`: fixes the grammar in the field you are in, keeping your
  lowercase and slang.
- Runs on a local model through Ollama, or Groq with a key. A missing model is
  reported before you speak, with the command that fixes it.

### Everything else

- A log at `%LOCALAPPDATA%\LiveWhisper\livewhisper.log` (tray → Open log), with
  one line per dictation saying how long each stage took.
- The installer works on a fresh Python, and offers the optional models it can
  use on your hardware.

### Known limits

- Gujarati, Punjabi, Malayalam and Marathi still get about half the words
  wrong; Sindhi has no specialist model.
- Windows only.
