# Decisions

Every product and scope decision, newest first, one line each: what was
decided, who decided, and why. The larger engineering choices each have a full
record in [adr/](adr/), linked here. Add a line when a decision is made; when
one is reversed, add the new line and strike the old one through rather than
deleting it.

**Who:** *owner* = the maintainer's call; *measured* = chosen by an evaluation
(the numbers are in the linked record or [evaluation.md](evaluation.md));
*incident* = forced by a failure seen in testing.

## 2026-09-23

| Decision | Who | Why |
| --- | --- | --- |
| Correct Whisper when it hears Marathi as Hindi, by detection score and by the words written | incident + measured | A user's "tu AI system design kuthun shikla?" was heard as Hindi on every voice; held-out Marathi recognised 22% -> 59% ([ADR 0015](adr/0015-hear-marathi-as-marathi.md)) |
| Take IndicWhisper for Marathi, Punjabi and Malayalam; keep the current model for Kannada, Gujarati, Telugu and Urdu | measured | Marathi 47.2% -> 26.5% word error, Punjabi 60.9% -> 40.3%, Malayalam 61.3% -> 50.6%; the others no better or worse ([ADR 0016](adr/0016-indicwhisper-specialists.md)) |
| Do not put a code-switched example in the decoding prompt | measured | English words kept 43.3% -> 44.0%, and 52% -> 50% on IndicWhisper: noise, as in the earlier Hindi experiment |
| Keep romanizing Marathi verbs as people type them ("shikala", not "shikla") | measured | Dakshina annotators kept the middle vowel 658 times against 297; a personal spelling is learned instead |

## 2026-09-22

| Decision | Who | Why |
| --- | --- | --- |
| Build polish as an opt-in setting with guardrails, English only | owner | Typeless-style cleanup without risking a pasted answer or a lost "not" ([ADR 0014](adr/0014-opt-in-english-polish.md)) |
| Polish runs online only, on gpt-oss-120b | measured | Held-out: 35 -> 11-17 word distance, 0 violations; the local 3B left text no better and dropped a "maybe" |
| Publish 1.0.0 as a GitHub release with the installer attached; nothing goes to PyPI | owner | Users get a Setup.exe; the Python package is only for source checkouts |
| Keep documentation in `docs/` with ADRs; retire `install.ps1`, `uninstall.ps1`, `start.bat` | owner | The Setup.exe replaced the command-line install ([ADR 0005](adr/0005-desktop-installer-and-in-app-downloads.md)) |
| Online is one switch covering speech, formatting and writing | owner | "Whatever we can do offline, do online with one setting" ([ADR 0012](adr/0012-online-as-one-switch.md)) |
| Online keeps a language with its own downloaded model on this PC | owner + measured | Groq's general model: Bengali 73% of words wrong against 21% locally |
| Online falls back to this PC when Groq fails, and says so in the pill | owner | A dictation must still happen offline |
| New installs start with Online off | owner | Private by default, and works without a key ([ADR 0004](adr/0004-local-first.md)) |
| Formatting online on gpt-oss-20b, writing on gpt-oss-120b | measured | 71% exact vs 67% local; Groq's Llama models were retired |
| ~~Do not add a Typeless-style "polish" rewrite in 1.0~~ (superseded above: opt-in polish) | owner | The formatter stays word-preserving ([ADR 0010](adr/0010-formatter-never-changes-words.md)); revisit as an opt-in |
| Names from the screen go only to English and Hinglish decoding | incident | Notepad's status bar wrecked a Bengali transcript ([ADR 0013](adr/0013-never-paste-what-was-not-said.md)) |
| Corrections to the Hinglish model's Latin text are learned when only the spelling changed | incident | They were silently ignored ([ADR 0011](adr/0011-learn-at-the-next-dictation.md)) |
| Drop looping or stock text from silence instead of pasting it | incident | A muted mic pasted "aapke liye aapke liye..." |
| Setup closes a running copy and restarts it after a silent upgrade | incident | A silent upgrade gave up while the app ran |
| Use the CPU until cuBLAS can load | incident | A fresh install's first dictation failed ([ADR 0009](adr/0009-gpu-support-as-cublas-only.md)) |

## 2026-09-21

| Decision | Who | Why |
| --- | --- | --- |
| Ship 1.0 as a Setup.exe desktop app; hold the release until it is ready | owner | "A desktop exe, no command line, no pip installs" ([ADR 0005](adr/0005-desktop-installer-and-in-app-downloads.md)) |
| Models and GPU libraries download inside the app on first launch | owner | Keeps the installer at 100 MB |
| Bundle a language-model runner instead of requiring Ollama | owner | Nothing to install separately ([ADR 0008](adr/0008-built-in-llama-cpp-runner.md)) |
| Window and recording pill styled after Typeless | owner | [ADR 0006](adr/0006-webview2-window-and-layered-pill.md) |
| Publish the converted language models under the maintainer's Hugging Face account | owner | The app cannot convert without PyTorch ([ADR 0007](adr/0007-no-pytorch-at-runtime.md)) |
| Build tools: Inno Setup 6, llama.cpp Vulkan build (pinned) | owner | Approved downloads; Vulkan runs on any GPU |
| GPU support is cuBLAS only | measured | cuDNN never loads for Whisper; 550 MB instead of 1.3 GB |
| First run on a GPU machine also fetches English turbo | measured | 30-55% shorter wait on English, same accuracy |
| English decoding gets a spoken-punctuation prompt | measured + incident | "comma" was heard as "Kama"; FLEURS English WER improved slightly |
| Sinhala gets its own model | measured | 114.7% -> 77.6% native WER |
| Character-model spellings with invented consonants fall back to letter spelling, except Tamil and Malayalam | measured | Better on 10 of 12 languages on two disjoint samples |
| Letter spelling writes long i/u plainly outside Tamil, Telugu, Malayalam | measured | Hindi usual-spelling 36.9% -> 47.4% over the lexicon |

## Before 2026-09-21 (0.2 to 1.0)

| Decision | Who | Why |
| --- | --- | --- |
| Every one of the twelve languages in both its own script and romanized, with high accuracy; English translation is out of scope | owner | People dictate in their language and sometimes want it in Latin |
| Script chosen automatically from the field being typed into, with Ctrl+Alt+H to switch the next dictation | owner | No setting to forget |
| English and Hinglish must work both locally and on Groq | owner | |
| Dictation records the microphone only; meetings are notes mode's job | owner | A dictation must not pick up whatever is playing |
| Ctrl+Alt+W is press, speak, press - not a fixed 8 s | incident | Short instructions waited 8 s; long ones were cut off |
| Paste only into the window dictation started in | incident | Text landed in another window the user had moved to |
| Trust an early language guess only if it heard 70% of the recording or 8 s | incident | Guesses on 2.5 s heard Punjabi and Marathi as English |
| 15 s decode windows, fixed | measured | 30 s lost a quarter of long dictations; adaptive windows lost too |
| Unload the writing model as soon as it has written | incident | A resident 7B model made dictations take 12-40 s |
| Romanize after transcription rather than asking Whisper for Latin | measured | Ten attempts failed ([ADR 0002](adr/0002-romanize-after-transcription.md)) |
| Per-language models only by measurement; Urdu stays on large-v3; Sindhi reported on the test split only | measured | [ADR 0003](adr/0003-specialist-models-by-measurement.md) |
| Hindi has two models: Hinglish-Prime for romanized, Vaani for Devanagari | measured | Vaani 10.3% native WER, but it writes English words in Devanagari |
| Learn from corrections at the next dictation, never by watching typing | owner | [ADR 0011](adr/0011-learn-at-the-next-dictation.md) |

## Open

Decided to defer, with what would change it:

- **Code signing.** Windows warns on first run until the installer is signed; worth it once people outside early users install it.
- **Faster first run.** Download turbo first so dictation works within minutes while large-v3 follows; the current first run is about 25 minutes at 4 MB/s.
- **Polish offline and beyond English.** Needs a local model that improves the
  held-out set with 0 violations, and an evaluation set per language.
- **Untested hardware.** No-GPU PCs, AMD/Intel graphics and Windows 10 have not been run end to end.
- **English written in native script.** A Marathi or Hindi model writes "ready"
  as रेडी, and romanization then spells it "redi". The lexicons cover loanwords
  only patchily, and Marathi attaches case endings to English words
  ("deadlineच्या"). Needs an English pronunciation dictionary and suffix
  splitting; measured at 62% of English words kept on held-out code-switched
  Marathi ([ADR 0015](adr/0015-hear-marathi-as-marathi.md)).
- **Weak languages.** Gujarati, Telugu and Sinhala wait on better openly
  licensed models; Marathi, Punjabi and Malayalam were improved in 1.1
  ([ADR 0016](adr/0016-indicwhisper-specialists.md)); re-measure when one appears.
- **Urdu and Sindhi confusion.** They share a script, and the word check covers
  them, but no audio measurement has been made; the detection threshold is
  Hindi/Marathi only.
