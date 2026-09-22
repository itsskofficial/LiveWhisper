<div align="center">

<img src="assets/livewhisper.png" width="88" alt="LiveWhisper">

# LiveWhisper

**Voice typing for the 1.6 billion people who type their language in English letters.**

You speak Hindi. You type `kya kar rahe ho`.
Every dictation app gives you `क्या कर रहे हो`.

*Hinglish · Tanglish · Banglish · Thanglish · Manglish · Punglish · and six more*

[![tests](https://github.com/itsskofficial/LiveWhisper/actions/workflows/tests.yml/badge.svg)](https://github.com/itsskofficial/LiveWhisper/actions/workflows/tests.yml) [![release](https://img.shields.io/github/v/release/itsskofficial/LiveWhisper)](https://github.com/itsskofficial/LiveWhisper/releases/latest)

[**Download**](https://github.com/itsskofficial/LiveWhisper/releases/latest) · [What it does](https://claude.ai/code/artifact/f350c628-163d-4a75-a4e1-8a7829c6b2e9) · [How it works](#how-it-works) · [Docs](docs/) · [Contributing](CONTRIBUTING.md)

</div>

---

## The problem, in one line

Speech engines write the "correct" script. Nobody types the correct script.

```
   you say:            "kal main office jaunga"
   Whisper writes:      कल मैं ऑफिस जाऊंगा        ← correct Hindi. unusable in chat.
   LiveWhisper writes:  kal main office jaunga    ← what you'd have typed
```

There is **no way to ask a speech engine for romanized output**. We tested ten
different approaches and every one failed, so LiveWhisper converts the script
itself — and then learns the spellings *you personally* use.

## And a second problem nobody solves

Dictation tools **normalise** your writing: they add punctuation, fix
capitalisation, clean it up. But personal style *is* deviation from the norm, so
the whole category destroys the thing that makes text sound like you.

Wispr Flow's own documentation says it learns from your corrections but
explicitly discards *"capitalization-only changes"*. If you write in lowercase
on WhatsApp, it sees you delete that capital every single time — and throws the
signal away, because a word→word dictionary has nowhere to put "don't capitalise
in this app."

**LiveWhisper keeps what the others throw away.**

---

## It hands you a message, not a sentence

A speech model returns words. What you wanted was the thing you would have
typed — so the last step before the paste is a formatting pass.

It runs in two layers. **Rules** handle what can be done exactly: spoken
commands, lists, emails, corrections it can verify, per-app style — 0.6 ms per
100 words. Then **a very small local model** that the app runs itself
(qwen3 0.6B, 640 MB, downloaded at setup) handles what rules cannot: punctuating a run-on
sentence, capitalising names, spotting a list you never announced.

A small model left to itself is dangerous — asked to format "what is the capital
of france" it answers *Paris*, and it will translate Hinglish or "fix" your
spelling. So its answer is never pasted. Only its **punctuation, capitals and
line breaks** are taken, and laid back over the exact words you said. An
invented word has nothing to attach to and disappears; a dropped word comes
back; an answer instead of formatting is thrown out and the rules result is
used.

| | Rules | + qwen3 0.6B |
| --- | --- | --- |
| Exactly what a careful typist would paste | 40% | **67%** |
| Words it invented | none | **none** |
| Time per dictation | 0 ms | 155 ms GPU · 371 ms CPU |

[Measured on 42 cases](tests/results/format_llm.md), including a question, a
dictated instruction and 16 Hinglish sentences. Skip the model and the rules
alone are what you get, and nothing slows down.

```
   "hey Sarthak comma how are you question mark"
       -> Hey Sarthak, how are you?

   "the meeting is at five new paragraph bring the deck"
       -> The meeting is at five
          (blank line)
          Bring the deck.

   "let us meet Monday I mean Tuesday"   -> Let us meet Tuesday.
   "that plan is fine. scratch that."    -> (the cancelled sentence is gone)
   "write to sarthak at gmail dot com"   -> write to sarthak@gmail.com
   "bullet point ship it bullet point measure it"
       -> - Ship it
          - Measure it
```

Paragraphs also come from the recording itself: the transcriber knows how long
you paused, so a pause of 1.6 seconds or more becomes a blank line.

And it writes differently depending on where you are typing, because a chat box
and a terminal want different things:

| Where | What changes |
| --- | --- |
| Slack, Discord, Teams, WhatsApp | No full stop added at the end — a trailing period in a chat box reads as annoyance |
| VS Code, terminals, JetBrains | Case left alone, and "dash m" becomes `-m` |
| Everywhere else | Full sentences |
| Any app you mark `verbatim` | Nothing is touched |

The hard part is not the conversion, it is knowing when *not* to convert. "The
period of the wave", "a dash of salt" and "two commas" all survive, while "send
it today period" ends the sentence. Romanized Indic text comes through
untouched — `dheere dheere` keeps its reduplication, because that is Hindi
grammar and not a stutter.

---

## Twelve languages

| | Language | Romanized as | Speakers | Lexicon coverage |
| --- | --- | --- | --- | --- |
| 🇮🇳 | Hindi | Hinglish | 610M | 87.3% |
| 🇧🇩 | Bengali | Banglish | 270M | 83.4% |
| 🇵🇰 | Urdu | Urdish | 230M | **92.1%** |
| 🇮🇳 | Punjabi | Punglish | 125M | 91.4% |
| 🇮🇳 | Marathi | Minglish | 83M | 90.9% |
| 🇮🇳 | Telugu | Thanglish | 83M | 86.2% |
| 🇮🇳 | Tamil | Tanglish | 79M | 86.9% |
| 🇮🇳 | Gujarati | Gujlish | 57M | 90.8% |
| 🇮🇳 | Kannada | Kanglish | 44M | 88.2% |
| 🇮🇳 | Malayalam | Manglish | 38M | 88.1% |
| 🇵🇰 | Sindhi | Sindhlish | 32M | 88.0% |
| 🇱🇰 | Sinhala | Singlish | 17M | 76.2% |

Coverage is how much of the language the dictionary knows. It is not accuracy —
for that, see [below](#measured-not-claimed).

### Both outputs, measured

Every language can be written in its own script or romanized, switched
automatically by the box you're typing in, or with `Ctrl+Alt+H`. Word error on
20 held-out FLEURS recordings per language, through the app's own code with the
language's accuracy model installed. Romanized output counts a word right if it
is any spelling people actually use for it (Dakshina); "usual spelling" is the
share written the way people most often write it.

| Language | Model | Native WER | Native CER | Romanized WER | Usual spelling |
| --- | --- | --- | --- | --- | --- |
| Hindi | Vaani (native), Hinglish-Prime (romanized) | **10.3%** | 3.0% | 18.1% | 75.4% |
| Bengali | Bengali.AI medium | 14.5% | 2.6% | 24.1% | 91.5% |
| Urdu | large-v3 | 23.0% | 9.2% | 20.3% | 87.3% |
| Kannada | IIT Madras medium | 24.3% | 10.8% | 22.8% | 87.3% |
| Tamil | IIT Madras medium | 24.6% | 12.4% | 24.3% | 89.2% |
| Sindhi | Sindhi large | 29.2% | 13.1% | 68.4% | 19.7% |
| Telugu | IIT Madras medium | 31.7% | 19.3% | 31.1% | 82.9% |
| Marathi | Marathi large-v2 | 40.2% | 11.4% | 42.1% | 49.3% |
| Gujarati | IIT Madras medium | 45.2% | 34.1% | 43.6% | 69.1% |
| Malayalam | Malayalam large-v3 | 57.2% | 27.9% | 53.8% | 60.3% |
| Punjabi | Punjabi large-v2 | 57.3% | 28.1% | 52.9% | 53.0% |
| Sinhala* | Sinhala large-v3 | 77.6% | 34.8% | 76.9% | — |
| English | large-v3-turbo | 4.3% | 2.2% | — | — |

\* FLEURS has no Sinhala; measured on 15 Dakshina sentences read by a neural
voice (`tests/eval_dakshina_speech.py`). English: 40 FLEURS clips.

The top half is good enough to dictate with. The bottom half is honest: for
Malayalam, Punjabi and Sinhala no openly licensed model yet hears more than
about half the words right, and those numbers will move as better ones appear.
No native script ever leaks into romanized text (0 of 220 dictations).
Reproduce with `python tests/eval_outputs.py build/fleurs --n 20`.

It picks the language from the script it is handed, so speaking Tamil at work and
Hindi at home needs no setting change. Ten of these twelve scripts belong to one
language and are unambiguous; Devanagari and Arabic are each shared by two, and
there your configured language decides.

---

## Install

**[Download LiveWhisper for Windows](https://github.com/itsskofficial/LiveWhisper/releases/latest)**
(`LiveWhisper-Setup-1.0.0.exe`, 100 MB) and run it. No Python, no command line,
no administrator rights.

Windows 10 or 11, 64-bit. An NVIDIA graphics card makes it several times faster;
it works without one.

On first launch LiveWhisper asks which languages you speak and downloads what
runs on your PC - the speech model (1.5-3 GB, sized to your machine), GPU
support if you have an NVIDIA card, and a small formatting model. Then it's in
your tray, ready for the shortcut, and starts with Windows.

> Windows may show *"Windows protected your PC"* the first time, because the
> installer is not yet code-signed. Click **More info → Run anyway**. The source
> of every release is in this repository.

| Shortcut | |
| --- | --- |
| `Ctrl+Alt+Space` | Dictate: press, speak, press again. Your microphone only |
| `Ctrl+Alt+W` | Write for you: press, say *"reply saying I can't make Thursday"*, press again. It reads the message on screen and pastes a reply |
| `Ctrl+Alt+F` | Fix grammar in the field you are in, *keeping* your lowercase and slang |
| `Ctrl+Alt+N` | Notes mode: record a meeting — your mic and the other people — into a note |
| `Ctrl+Alt+X` | Throw away the recording in progress |
| `Ctrl+Alt+H` | Keep the next dictation in the original script |

All of them can be changed in **Settings**. While you speak, a small pill at the
bottom of the screen shows a live waveform; click ✓ to finish or ✕ to discard.

Everything runs on your PC by default. Writing, grammar and formatting use
small language models that LiveWhisper runs itself (llama.cpp, on any GPU or the
processor).

**Online** is one switch under **AI**: speech, formatting and writing then run
on [Groq](https://console.groq.com) (free key) - about 2 s from the end of your
sentence to the text, on any PC. If you are offline or Groq is busy, your PC
takes over. A language whose accuracy model you have downloaded is still
transcribed on your PC, because that model is far more accurate than Groq's
general one (Bengali 21% of words wrong against 73%).

<details>
<summary><b>Run from source</b> (for development)</summary>

Python 3.12, Windows 10/11.

```powershell
git clone https://github.com/itsskofficial/LiveWhisper.git
cd LiveWhisper
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run.py
```

Tests, the end-to-end harness, building the installer and releasing are in
[docs/development.md](docs/development.md).

</details>

---

## How it learns you

Correct `mujhe` → `muze` once. That isn't a fact about that word — it's a fact
about how you spell **ज**, and it applies to the **316 other words** containing
it.

We measured this across 30,000 words. Variation follows 1,200 letter-level
conventions, heavily concentrated:

| Corrections | Variation explained |
| --- | --- |
| 5 | 43.9% |
| **10** | **57.0%** |
| 20 | 70.5% |

Running the loop for real does better than that table suggests: a single habit
generalises to **100%** of held-out words after two corrections. [Measured
here.](#learning)

**It does not watch you type.** At the start of your next dictation, before
pasting, it reads what's in that field and compares it with what it left there.
Nothing runs in the background.

**What it stores** is plain readable JSON — observed rates, not settings:

```json
"whatsapp.exe": { "habits": { "capitalize": 0.04, "terminal_period": 0.11 } },
"_global":      { "conventions": { "rules": { "jh": "z" } } }
```

Spelling is global; how you spell ज doesn't change between apps. Habits are
per-app; your WhatsApp voice isn't your email voice. **Settings → Writing**
shows exactly what it has learned, with a button to forget all of it.

### It refuses to learn nonsense

Type `too` for तू once and a naive system learns `u → oo`, which rewrites `aur`
as `aoor` and `bahut` as `bahoot` — **97% of affected words wrong**, measured.

So a rule needs two *different* words before it generalises, and even then it's
checked: a single Latin vowel stands for several native vowels, so replacing it
everywhere destroys the distinction. Consonants like `jh → z` map reliably and
pass. Rejected substitutions still apply to that one word.

---

## How it works

Three stages, and only one is a neural network:

```
  87% of words  →  dictionary lookup     instant · 17 MB · no AI
  13% of words  →  4.5M character model  18 MB · runs on CPU · 12 languages
  every word    →  your own conventions  learned from your corrections
```

The dictionary is Google's [Dakshina](https://github.com/google-research-datasets/dakshina)
dataset — 350,000 words across twelve languages, with the Latin spellings real
people actually use.

**The hardest part isn't a model. It's a table.** That's why this is free and
instant where cloud tools charge monthly and count your words.

### Hearing the right language in the first place

Romanization can't fix a transcript in the wrong language, and on short clips
Whisper guesses wrong more than you'd expect — it wrote 8 of 40 real Hindi
recordings in Urdu's Arabic script. So LiveWhisper only lets it choose among the
languages **you** speak (the one you picked at install, plus English):

| Hindi, 40 real recordings | Word error | Right language |
| --- | --- | --- |
| Whisper choosing from 99 languages | 46.4% | 78% |
| Choosing from Hindi + English | **29.0%** | **98%** |

And where one model for 99 languages is simply weak, a **specialist** takes
over decoding for that language while large-v3 keeps working out which language
you spoke. Here is every language, measured the same way — 40 people reading
aloud from Google's FLEURS recordings, scored on the text you would actually
receive after romanization, against every accepted spelling:

| Language | large-v3 | With specialist | Specialist |
| --- | --- | --- | --- |
| Hindi | 24.4% | **19.5%** | Oriserve Hinglish-Prime (writes Hinglish directly) |
| Bengali | 66.5% | **31.7%** | Bengali.AI whisper-medium |
| Tamil | 51.8% | **22.4%** | IIT Madras whisper-medium |
| Telugu | 71.6% | **36.2%** | IIT Madras whisper-medium |
| Urdu | **19.6%** | — | large-v3 is already best (a turbo fine-tune measured 24.1%) |
| Punjabi | 68.6% | **56.3%** | whisper-large-v2 fine-tune (still weak) |
| Marathi | 73.2% | **51.6%** | whisper-large-v2 Marathi fine-tune (still weak) |
| Gujarati | 63.3% | **48.5%** | IIT Madras whisper-medium (still weak) |
| Kannada | 59.8% | **30.2%** | IIT Madras whisper-medium |
| Malayalam | 108.7% | **58.8%** | whisper-large-v3 Malayalam fine-tune (still weak) |
| Sindhi | 77.7% | — | no fine-tune found |

Lower is better. The large-v3 column is already limited to your languages; the
specialist column is the same recordings through the specialist.

Two failures behind the worst numbers, both measured rather than guessed:
**large-v3 hears Malayalam correctly and writes it in Telugu script**, so nearly
every character counts as wrong; and on **7 of 40 Marathi recordings it decided
the speech was English and produced fluent, unrelated English**. That one is
fixed: English now has to be clearly ahead (99% likely) before it wins over
your own language. Every misfire scored between 54% and 89%, while real English
speech never dropped below 99.98% — so all 7 Marathi clips and 13 Sindhi ones
now decode correctly, and none of 40 English recordings were misrouted. English itself,
as a check that the scoring is sound, comes out at 4.8% word error — in line
with large-v3's published results.

```powershell
python -m livewhisper.specialists list        # what's been measured
python -m livewhisper.specialists install bn  # download, convert, configure
```

Only specialists that beat large-v3 on the same recordings are offered. The
installer suggests one for your language when it exists.

Installing converts the model, which briefly uses about 2× the download in
memory — measured between 1.9× and 2.4×, so 7–8 GB for a 3 GB model. With Windows' default pagefile that
only needs a few GB actually free to start, because Windows grows the pagefile
to cover the rest; with a fixed-size pagefile it waits for the whole amount.
Either way the install **waits and tells you** instead of crashing, runs one
conversion at a time, and closing a browser or other large program lets it
continue sooner.

---

## Local by default

| | Local? |
| --- | --- |
| Audio capture | Always |
| Transcription | Yes — faster-whisper on your GPU, ~3s for a sentence |
| Romanization + style | Yes — no network at all |
| Compose & grammar | Yes — a built-in local model, or Groq if you add a key |

No telemetry. No account. No word limits. Your profile is a file on your disk.

**Honest note:** local models are fine for grammar and short rewrites. For
longer composition a frontier model is noticeably better. The built-in model
is a real capability, not parity.

---

## Measured, not claimed

### Accuracy

Google's Dakshina dataset includes ~5,000 sentences per language that a **human**
romanized by hand. That is the only real ground truth for this task, so the
headline number is how close we get to what that person wrote — 500 held-out
sentences per language, 6,000 total:

| | |
| --- | --- |
| Spelled exactly as the human did | **60.4%** |
| Spelled acceptably (both spellings attested) | **83.7%** |
| A spelling nobody uses — actually wrong | **16.3%** |
| Words left in native script | **1.0%** |

Romanization has no single right answer: 45% of words have several accepted
spellings, so `nahi` against a human's `nahin` is a disagreement, not an error.
**83.7%** is the honest headline and **16.3%** is the number to drive down.
Word error rate, if you want one number to compare against a paper, is 40.6%.

Best and worst: Hindi 93.4% acceptable, Malayalam 73.2%. Per-language results in
[`tests/results/`](tests/results/).

### Speed

Everything LiveWhisper itself does is far below what you can perceive. The wait
is Whisper, and almost all of it is fixed cost:

| | |
| --- | --- |
| Romanize a sentence | **0.01 ms** |
| Romanize 156 words | **0.12 ms** |
| Learn from a correction | **3.4 ms** |
| First word in a new language | 80–105 ms (loads that lexicon) |
| Format the text before pasting | **0.6 ms** per 100 words |
| Transcribe a 4-second English dictation | **0.87 s** |
| Transcribe a 4-second Hindi dictation | **1.1 s** with Hinglish-Prime, 2.05 s with large-v3 |
| The same, on a CPU with no GPU at all | **0.84 s** Hindi (Hinglish-Swift), 2.4 s English (`small`) |
| Transcribe two minutes | 3.5 s — 37x realtime |
| Speech model load, once per launch | ~13 s, plus one warm-up decode |

Measured warm, on an RTX 4060 and a 16-core CPU; full tables in
[`tests/results/cpu.md`](tests/results/cpu.md).

Three things were cut from that wait, each measured first:

- **The language is worked out while you are still talking.** Detection is a
  whole extra pass over the audio — 0.4 s on a GPU, up to 2 s on a CPU — and it
  only ever looks at the start of the recording, so it now runs 2.5 seconds in.
- **The first dictation after launch is no longer the slow one.** It used to
  pay for GPU warm-up: 1.8 s instead of 0.8 s. The app now does a throwaway
  decode at launch. (That warm-up is also where this table's old "2.8 s" figure
  came from.)
- **Hindi is faster in Latin letters.** A Devanagari word costs several tokens
  and decoding is paid per token, so the Hinglish model decodes twice as fast
  as large-v3 *and* is more accurate.

And one thing was lost: **long recordings used to come back a quarter short.**
The decoder was handed 30-second windows and stopped early on full ones —
paragraphs kept 74% of their Hindi words and 77% of their English, with no
error. 15-second windows keep 96% and 93% at no cost to single sentences.
[Measured here.](tests/results/decode_windows.md)

### Learning

Simulated users with consistent spelling habits, measured on words they **never
corrected** — because learning the words you fixed is worthless, the point is
that fixing `mujhe` also fixes the 316 other words containing ज:

| | |
| --- | --- |
| One habit, after 2 corrections | **100%** |
| Three habits, after 3 / 30 | 91.7% / **98.3%** |
| Five habits, after 2 / 15 | 78.8% / **91.7%** |

### And one negative result

| | |
| --- | --- |
| Character model, 12 languages | 65.4% exact match, 4.5M params, CPU |
| Whisper → romanized via prompting | **Impossible** — 10 approaches, all failed |

Every number here is reproducible. Experiments live in
[`experiments/`](experiments/), measurements in [`tests/`](tests/):

```powershell
python scripts/fetch_fleurs.py build/fleurs --n 40   # real speech, 12 languages
python tests/bench_asr.py build/fleurs               # speech models, per language
python tests/bench_romanization.py <dakshina-root>   # spelling vs humans
python tests/test_learning.py                        # convergence
python tests/bench_latency.py                        # per-stage timings
python run_tests.py                                  # 13 suites, ~20 seconds
```

---

## "Isn't this already solved?"

Reasonable question. Three things look like they solve it and don't.

### Gboard already does transliteration

It does — **in the opposite direction.** Gboard lets you *type* `kya kar rahe ho`
and turns it into `क्या कर रहे हो`. That is roman → native.

LiveWhisper is native → roman, which is what you need when the *machine*
produces the text and you want it to look like you wrote it. Gboard's own voice
typing gives you Devanagari, same as everything else.

Different problem, opposite direction, and nobody was solving this one.

### Wispr Flow / Typeless / superwhisper

All excellent at English dictation, and all give you native script for Indic
languages because they use the same speech engines everyone does.

On style: Wispr Flow does read your corrections — but its documentation says it
keeps proper nouns and jargon while discarding *"capitalization-only changes"*
and style fixes. That is a deliberate design choice forced by its data model, a
flat word→word dictionary. Per-app style needs per-app profiles.

They are also cloud services with word limits and subscriptions. This is neither.

The usual argument for the cloud is that on-device dictation cannot do the
things that make these tools feel good. Point by point, here is where this one
actually stands — including the parts that are still worse:

| What the paid tools do | Here |
| --- | --- |
| Smart formatting, lists, paragraphs | Yes — rules plus a 522 MB local model that can punctuate but never change a word, [above](#it-hands-you-a-message-not-a-sentence) |
| Auto-edits: "Monday, I mean Tuesday" | Yes, for corrections it can verify are corrections |
| Context awareness: names from your screen | Yes — read locally, used for that one dictation, never stored or sent |
| Learns your vocabulary and spelling | Yes, and it keeps the capitalisation habits they discard |
| Per-app tone and style | Yes, per app, and you can override it |
| Works offline | Yes. That is the whole design |
| Voice shortcuts, code identifiers | Say the cue, get the saved text; "camel case user name" types `userName` in an editor |
| English accuracy | 4.8% word error on FLEURS — the model's own number, not ours |
| Code-switched Hindi/English | Better than the cloud default: they transliterate English into Devanagari ([measured](#just-ask-whisper-for-romanized-output)) |
| Latency on a short dictation | 0.87 s English, 1.1 s Hindi on an RTX 4060; 0.84 s Hindi on a CPU with no GPU. Nothing to upload ([measured](tests/results/cpu.md)) |
| Indic accuracy beyond Hindi | **Worse.** Gujarati, Punjabi, Malayalam and Marathi still miss about half the words, and Sindhi has no usable model at all |
| Polish on long-form rewriting | **Worse** unless you point it at a frontier model, which is not local |

No word limits, no account, no subscription, and the numbers above are in
[`tests/results/`](tests/results/) with the scripts that produced them.

### Just ask Whisper for romanized output

The first thing we tried. It cannot be done — ten different approaches, all
failed, documented in [`experiments/exp1_romanized_prompt.py`](experiments/).

The closest attempt forces Whisper to *start* in Latin letters. It complies for
about thirty seconds and then reverts mid-sentence:

```
haan toh main ye keh raha tha ki, you were saying MNCs se zyada startup
job create karenge... mai batata hon because MNCs खरीद नहीं लेगी ...
```

Whisper decides the audio is Hindi, and to Whisper, Hindi *means* Devanagari.
You can nudge it. You cannot change its mind. That negative result is why the
conversion stage exists.

---

## Questions

**Is my audio sent anywhere?**
No. Capture and transcription run on your machine. Romanization and style
learning never touch the network at all. You can optionally point transcription
at Groq for speed, or the writing assistant at a cloud model — both are off by
default and clearly labelled.

**Does it work offline?**
Entirely, once the speech model is downloaded.

**What does it learn about me, and where does it go?**
A JSON file in the install directory, `profiles.json`: spelling rules, the
individual words you corrected that taught them, and observed rates like
"capitalises 4% of the time in WhatsApp". Never your messages. Open it, edit
it, delete it — **Settings → Writing** shows all of it and has a Forget button.

**Something went wrong.**
Tray icon → **Open log**. The log is at
`%LOCALAPPDATA%\LiveWhisper\livewhisper.log`, with one line per dictation
saying how long each stage took and where the text was pasted. Attach it to an
[issue](https://github.com/itsskofficial/LiveWhisper/issues).

**It is slower on my laptop than the numbers here.**
Laptop GPUs are held back hard by power settings. On battery the same
dictation measured about three times slower; plugged in but in the laptop
maker's quiet or eco profile, the GPU sat at its minimum clock (210 of 3105 MHz)
and everything took two to three seconds instead of under one. Plug in, pick
the *Performance* profile in your laptop's control app (Armoury Crate, Lenovo
Vantage, Omen Gaming Hub, ...), and set Windows' power mode to *Best
performance*. `nvidia-smi -q -d PERFORMANCE` shows whether a power cap is
holding the GPU back.

**My language isn't listed.**
The twelve are the ones Google's Dakshina dataset covers, because a romanization
lexicon is the hard prerequisite. If you know of an equivalent dataset for
another language, open an issue — the pipeline itself is language-agnostic.

**The romanization is wrong for my language.**
Very possibly, and we'd like to know. Eleven of the twelve have never been
checked by a native speaker. There's an issue template for exactly this.

---

## Contributing

**The most valuable thing a native speaker can do** takes ten minutes: write
five natural chat-register sentences in your language for the setup wizard.
Hindi has them; the other eleven currently generate word prompts from the
lexicon instead, which works but is less good.

See [CONTRIBUTING.md](CONTRIBUTING.md) — it's a single file edit, and there's an
issue template that walks you through it.

Also wanted: curated common-word lists per language, macOS and Linux support,
and anyone who can tell us the romanization looks wrong for their language.

```powershell
python run_tests.py           # 13 suites, ~20 seconds, no GPU or network
python run_tests.py --audio   # also real speech and loopback capture
python run_tests.py --all     # also Groq fallback and install readiness
```

## Licence

Code MIT. The Dakshina lexicons in `data/` are CC BY-SA 4.0 — see
[data/LICENSE-DATA.md](data/LICENSE-DATA.md).
