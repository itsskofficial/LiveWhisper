# How LiveWhisper Works

*Written for someone who has never studied speech recognition or machine
learning. No prior knowledge assumed. If a term appears, it gets explained
before it is used.*

---

## Part 1 — What the app is

You hold a hotkey, speak, and the words appear wherever your cursor is.

That is the whole promise. Everything else in this document exists to make
those words come out **the way you would have typed them yourself** — including
your capitalisation habits, your punctuation habits, and, if you speak Hindi or
Marathi, the Latin spellings you actually use rather than Devanagari script.

Four things it does:

| | Feature | What you press |
| --- | --- | --- |
| 1 | Dictation that learns your writing style | `Ctrl+Alt+Space` |
| 2 | Speak an instruction, it writes the text | `Ctrl+Alt+W` |
| 3 | Fix grammar in whatever field you're in | `Ctrl+Alt+F` |
| 4 | Notes from system audio | `Ctrl+Alt+N` |

---

## Part 2 — The concepts, from zero

Five ideas. Everything after this assumes only these.

### 2.1 Audio is just numbers

A microphone measures air pressure 16,000 times a second. Each measurement is a
number. One second of sound is a list of 16,000 numbers. That's all audio is to
a computer — a long list of numbers.

When this app records you, it produces exactly that list.

### 2.2 A model is a very large recipe

A **model** is a file full of numbers, plus instructions for what to do with
them. You feed something in at one end (a list of audio numbers) and something
comes out the other end (text).

Nobody wrote the numbers by hand. They were found automatically by showing the
computer millions of examples — this audio goes with this text — and nudging the
numbers until the output matched. That process is called **training**. It is
done once, by whoever made the model, on very expensive hardware.

**You never train anything.** You download the finished file and use it. Training
happened before you arrived.

### 2.3 Parameters = the size of the recipe

Those numbers inside the model are called **parameters**. More parameters means
more capacity to learn subtle things, but a bigger file and slower running.

- Our speech model: **1.5 billion** parameters — 3 GB on disk
- Our spelling model: **2.56 million** parameters — 10 MB on disk

That thousand-fold difference is deliberate, and Part 4 explains why the small
one is small.

### 2.4 Scripts are not languages

This distinction is the heart of the app, so it's worth being precise.

A **language** is what you speak. A **script** is the set of shapes you write it
in. They are independent.

Hindi is normally written in **Devanagari** — क्या कर रहे हो.
But on WhatsApp, essentially everyone writes Hindi in **Latin** letters —
kya kar rahe ho.

Same language. Same words. Different script.

Speech recognition software gets the language right and the script wrong. It
outputs क्या कर रहे हो because that is "correct" Hindi. But if the app pastes
that into your chat, it doesn't look like you wrote it, so you won't use it.

Converting between scripts is called **transliteration**. It is *not*
translation — nothing is being translated. `मुझे` → `mujhe` is the same word,
re-spelled.

### 2.5 Tokens and vocabulary

A **token** is one word-ish chunk of text. "kal main office jaunga" is 4 tokens.

**Out-of-vocabulary** (OOV) means a word the app has never seen in its
dictionary. Most words are in the dictionary; a few aren't. Part 4.3 is about
those few.

---

## Part 3 — How the app is built

### 3.1 The journey of one dictation

```
   you speak
       │
   ┌───▼─────────────┐
   │ 1. CAPTURE      │  microphone + system audio -> numbers
   └───┬─────────────┘
   ┌───▼─────────────┐
   │ 2. TRANSCRIBE   │  numbers -> text, using Whisper
   └───┬─────────────┘
   ┌───▼─────────────┐
   │ 3. SCRIPT       │  Devanagari -> your Latin spelling
   └───┬─────────────┘
   ┌───▼─────────────┐
   │ 4. STYLE        │  your capitalisation & punctuation habits
   └───┬─────────────┘
   ┌───▼─────────────┐
   │ 5. DELIVER      │  paste at your cursor
   └─────────────────┘
```

Steps 3 and 4 are what make this app different. Every dictation tool does 1, 2
and 5.

### 3.2 Step 1 — Capture

Windows has a feature called **WASAPI loopback**. Normally a microphone is an
input and speakers are an output, and you cannot record an output. Loopback
exposes every output device a *second* time, disguised as an input. So the app
can record what's coming out of your speakers without any cable, without
rerouting anything, and without breaking your audio.

The app records **two separate streams**: your microphone, and your system
audio. Keeping them apart is free and gives you "me" versus "them" without any
extra machinery.

`livewhisper/audio.py`

### 3.3 Step 2 — Transcribe

We use **Whisper**, a speech recognition model released by OpenAI, specifically
`large-v3`. It understands 99 languages and works out which one you're speaking
by itself.

We don't run OpenAI's original code. We use **faster-whisper**, a
reimplementation that produces the same output about four times faster by using
the GPU more efficiently.

On your RTX 4060 this runs at roughly **27 times real time** — a 30-minute
recording transcribes in about a minute. Measured, not estimated.

Two ways to run it:

- **Local** — on your graphics card. Free, private, ~3 GB model.
- **Groq** — a cloud service, about 2.5× faster, costs around $0.04/hour.

The app defaults to whichever you configure and falls back automatically when
one is unavailable.

`livewhisper/transcribe.py`

### 3.4 Step 5 — Deliver

The app puts text on the clipboard and sends a synthetic `Ctrl+V` to whatever
window has focus. Simple, and it works in every application because every
application supports paste.

`livewhisper/output.py`

---

## Part 4 — The script problem, in detail

This is the part with real engineering in it, so it gets its own section.

### 4.1 What we tried first, and why it failed

Whisper has a feature called an **initial prompt**: you show it a sample of text
and it tends to continue in that style. The obvious idea was to show it
romanized Hinglish — `haan bhai kya kar rahe ho` — and hope it wrote Hindi in
Latin letters.

We tested this ten different ways. **It does not work.**

Every variation produced the same output. The strongest version, which forces
Whisper to literally begin with romanized text, obeys for about thirty seconds
and then reverts:

> `haan toh main ye keh raha tha ki, you were saying MNCs se zyada startup job
> create karenge... mai batata hon because MNCs` **`खरीद नहीं लेगी`** ...

Whisper decides "this audio is Hindi", and to Whisper, Hindi *means* Devanagari.
You can nudge it. You cannot change its mind.

**This is why the app has a conversion stage.** We didn't build it because it
seemed clever — we built it because the cheap alternative was tested and
measurably failed. Cost: one hour. Saved: weeks of building on a broken
assumption.

`experiments/exp1_romanized_prompt.py`, `exp1b_prompt_controls.py`

### 4.2 The dictionary — 92% of the work, no AI at all

Google published a dataset called **Dakshina**: a list of Hindi words alongside
how real people spell them in Latin letters, collected from actual humans.

We measured it against real Whisper output from a real Hinglish podcast:

| | |
| --- | --- |
| Words in the dictionary | 30,000 |
| **Tokens it could handle** | **92.3%** |
| Size on disk | 1.1 MB |
| Time per lookup | microseconds |

**Nine out of ten words are solved by looking them up in a table.** No neural
network, no GPU, no internet. This is the single most important fact about the
app's architecture: the hard-looking problem is mostly a dictionary.

`livewhisper/script/lexicon.py`, `experiments/exp2_dakshina_coverage.py`

### 4.3 The small model — the remaining 8%

Some words aren't in the dictionary. Usually grammatical variations — `लेंगी`
(feminine future tense) rather than a base word.

For these we trained our own model. It reads a word **one letter at a time** and
writes out Latin letters, having learned the patterns from 44,000 examples. It
has never seen `लेंगी`, but it has seen enough words ending `-ेंगी` to know they
end `-engi`.

Think of a child who has never seen "brightness" but can spell it from knowing
"bright" and "-ness".

| | |
| --- | --- |
| Size | 2.56 million parameters, 10 MB |
| Accuracy | 63% exact match on held-out words |
| Hardware | trains and runs on CPU |

63% sounds low, and it is a first attempt rather than a ceiling. But it only
handles 8% of words, so the combined system is:

```
92% dictionary (near-perfect)  +  8% model (63%)  =  ~97% of words correct
```

**Two failure modes we found and fixed.** The model loops on very short inputs —
`आ` became `aaaaaaaa`. And Dakshina's 30,000-word sample happens to be missing
some very common forms: `जाऊंगा` ("I will go") isn't in it, and the model
produced `jaaungaanga`.

Both are fixed with a hand-written table of about 100 high-frequency words that
never touches the model, plus a check that rejects looping output. When output
looks wrong, the app falls back to leaving Devanagari — **visibly** wrong is
better than **plausibly** wrong, because you'll notice and correct it.

`livewhisper/script/oov.py`, `experiments/exp4_oov_seq2seq.py`

### 4.4 Deciding which script you want

Sometimes you *do* want Devanagari — a formal document, a Hindi form.

The app reads the field you're typing into. If the text already there is
Devanagari, it keeps Devanagari. If it's Latin, it romanizes. Replying inside a
Devanagari thread means you want Devanagari — no setting required, right nearly
always.

`Ctrl+Alt+H` forces Devanagari for the next dictation, and each app can have a
fixed preference.

There's a pleasant accident here: Whisper produces Devanagari *natively*, so
"write in Hindi script" is just skipping the conversion. **Native script is the
cheaper path, not the harder one.**

`livewhisper/pipeline.py`

---

## Part 5 — How it learns your style

### 5.1 The insight

Say you write `muze` where the dictionary says `mujhe`.

The naive approach stores that one word. Hindi has 17,065 words with more than
one accepted spelling, so you'd be correcting forever.

But your correction isn't a fact about the word *mujhe*. **It's a fact about how
you spell the letter ज** — with a `z`, not a `jh`. Learn the *rule* and it
applies to all 316 words containing that letter.

We measured how far this goes. Across 30,000 Hindi words there are 1,200 such
spelling conventions, but they're heavily concentrated:

| Conventions learned | Variation explained |
| --- | --- |
| 5 | 43.9% |
| **10** | **57.0%** |
| 20 | 70.5% |

**About ten corrections and it writes more than half your words your way.**
Word-by-word learning would need thousands.

`livewhisper/script/conventions.py`, `experiments/exp5_spelling_axes.py`

### 5.2 How it notices you corrected something

When you dictate, the app pastes text. If you edit it, that edit is the signal.

**It does not watch you type.** At the start of your *next* dictation, before
pasting anything, it reads what's currently in that field and compares it with
what it left there. The difference is your correction. Nothing runs in the
background, and nothing records your keystrokes.

Reading the field uses **UI Automation** — an accessibility feature Windows
built for screen readers. Any well-behaved app exposes its text through it. This
is the same mechanism Wispr Flow uses.

`livewhisper/context.py`

### 5.3 What gets stored

Not model weights. A readable file, one section per application:

```json
{
  "whatsapp.exe": {
    "habits": { "capitalize": 0.04, "terminal_period": 0.11, "samples": 24 },
    "script": null
  },
  "_global": {
    "conventions": {
      "rules":     { "jh": "z" },
      "overrides": { "मुझे": "muze" }
    }
  }
}
```

Those numbers are **observations, not settings**. `capitalize: 0.04` means "in
4% of your WhatsApp sentences you used a capital letter". Once there's enough
evidence, the app matches it.

Note what's separate: **spelling** is global, because how you spell ज doesn't
change between apps. **Habits** are per-app, because your WhatsApp voice and
your email voice are different people.

You can open this file, edit it, or delete it. Learning is inspectable, not
magic.

`livewhisper/profile.py` · stored in `profiles.json`

### 5.4 Why counting, not training

We deliberately do **not** fine-tune a model on your writing.

| | Fine-tuning | Counting (what we do) |
| --- | --- | --- |
| Effect of one correction | Next retrain | Immediate |
| Storage | 10 MB of weights | A few lines of text |
| Can you read it? | No | Yes |
| Training on your PC | Yes, slow | None |

Counting *feels* like learning because it responds instantly. And it works from
your first correction rather than your five-hundredth.

**Safety rule:** one correction fixes that word immediately but does **not**
become a general rule — you might have simply typo'd. A substitution seen in
**two different words** gets promoted. That stops one slip from mangling 316
words.

### 5.5 Where the personalisation sits

This ordering matters more than it looks:

```
  dictionary (92%) ─┐
                    ├──> YOUR CONVENTIONS ──> your overrides ──> output
  small model (8%) ─┘
```

Your rules apply **after both paths**. If they only applied to the dictionary,
92% of your words would be spelled your way and 8% wouldn't — your own text
would be internally inconsistent. One layer after both means every word obeys
your habits regardless of which path produced it.

---

## Part 6 — The other three features

### 6.1 Speaking an instruction (`Ctrl+Alt+W`)

You're in Outlook looking at an email. You press the hotkey and say *"reply
saying I can't make Thursday, propose Monday."*

1. It reads the email on screen through UI Automation
2. It sends that, your instruction, and a description of your writing habits to
   a language model
3. The reply comes back, goes through the same script and style stages, and
   pastes

The app checks first whether you're giving an *instruction* or just *dictating*,
using simple word patterns — "write", "reply", "make this shorter". Plain
dictation never goes near a language model.

**What model?** By default **Ollama** running `qwen2.5:7b` on your own machine —
nothing leaves your computer. You can switch to Groq, OpenAI or Anthropic in
settings.

**An honest limitation:** local models are genuinely fine for grammar and short
rewrites. For longer composition, a frontier model is noticeably better. Local
support is a real capability, not parity, and the settings say so.

`livewhisper/actions.py`, `livewhisper/providers.py`

### 6.2 Grammar (`Ctrl+Alt+F`)

Reads the text in your current field, fixes grammar and spelling, puts the
correction on your clipboard.

The interesting part is what it's told *not* to do. The instruction to the model
explicitly says: preserve deliberate lowercase, slang, and romanised Hindi
spellings — **those are not errors**. A normal grammar checker would "correct"
`nhi yaar` into `No, friend.` and destroy the thing that makes it sound like
you.

### 6.3 Notes (`Ctrl+Alt+N`)

Toggles notes mode. Everything transcribed appends to a Markdown file with
timestamps instead of pasting. Plain text on disk, readable without this app.

`livewhisper/notes.py`

---

## Part 7 — Every file, and what it does

```
livewhisper/
  audio.py         record microphone + system audio (WASAPI loopback)
  transcribe.py    speech -> text (Whisper, local or Groq)
  pipeline.py      the chain: script choice -> romanize -> style -> deliver
  output.py        clipboard + paste at cursor
  context.py       read the screen (UI Automation, OCR fallback)
  profile.py       per-app habits, stored as observed rates
  actions.py       compose, grammar fix, rewrite
  providers.py     Ollama / Groq / OpenAI / Anthropic
  notes.py         Markdown notes from system audio
  main.py          hotkeys, tray icon, state machine
  gui.py           settings window
  script/
    lexicon.py     the 30k-word dictionary + curated common words
    oov.py         the 2.56M character model for unknown words
    conventions.py your personal spelling rules, learned letter by letter
    romanize.py    puts the three together

data/
  hi.lexicon.tsv   30,000 Hindi words (CC BY-SA 4.0, see LICENSE-DATA.md)
  mr.lexicon.tsv   30,000 Marathi words
  translit_hi.pt   the trained character model

experiments/       every measurement quoted in this document, reproducible
```

---

## Part 8 — Every model used

| Model | Job | Size | Where it runs |
| --- | --- | --- | --- |
| **Whisper large-v3** | speech → text | 1.5B params, 3 GB | your GPU |
| **Our transliterator** | unknown Hindi words → Latin | 2.56M params, 10 MB | your CPU |
| **Qwen 2.5 7B** (Ollama) | compose & grammar | 7B params, 4.7 GB | your GPU |
| *Dakshina lexicon* | 92% of Hindi words | 30k entries, 1.1 MB | a lookup, not a model |

Note the last row. **The biggest single contribution to the hardest feature is
not a model at all** — it's a table. That's why the app can be free and instant
where competitors charge monthly and count your words.

---

## Part 9 — What is measured, and what isn't

Every number in this document comes from a script in `experiments/` that you can
re-run. Being clear about their limits:

**Measured:**
- 92.3% dictionary coverage — on one 75-second podcast clip
- 63.2% model accuracy — on Dakshina's own held-out test data
- 27x real-time transcription — on your RTX 4060
- 57% of spelling variation from 10 conventions — across 30,000 words
- Prompting fails — ten variations, all negative

**Not yet measured:**
- Accuracy on *your* voice and *your* vocabulary
- Whether the learning loop converges pleasantly in daily use
- How well UI Automation reads Chrome and Electron apps (Slack, Discord, web
  Gmail expose text only reluctantly — this is the weakest part of the app)

**Known limitations:**
- Errors compound: if Whisper mishears a word, the romanizer faithfully
  re-spells the wrong word. Romanization quality can never exceed transcription
  quality.
- The 63% model is a first attempt. More training and better decoding should
  improve it meaningfully.
- Dakshina is Wikipedia-derived, so it under-represents chat slang and heavy
  clipping (`nhi`, `krna`, `h`).

---

## Part 10 — Trying it

```
Ctrl+Alt+Space   dictate
Ctrl+Alt+W       speak an instruction
Ctrl+Alt+F       fix grammar in this field
Ctrl+Alt+N       notes mode on/off
Ctrl+Alt+H       keep the next dictation in Devanagari
Ctrl+Alt+X       discard
```

To see the personalisation work, the fastest demonstration:

1. Dictate a Hindi sentence into any text field
2. Change one spelling — `mujhe` to `muze`
3. Dictate again and change another word with the same letter — `samjho` to
   `samzo`
4. From the third dictation on, every word with that letter follows your
   spelling

That is the whole product in four steps.
