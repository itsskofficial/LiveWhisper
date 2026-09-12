# Contributing

The most useful contributions here don't require knowing the codebase. They
require knowing a language.

---

## The one we need most: onboarding sentences for your language

**Ten minutes, one file, no Python knowledge needed.**

When LiveWhisper first runs, it shows a few sentences in your script and asks
you to type them the way you normally would. From that it learns how *you*
romanize — whether you write `mujhe` or `muze`, `vo` or `wo`.

Hindi has five hand-written sentences. The other eleven languages fall back to
generating single-word prompts from the lexicon. That works, but sentences are
much better, because they also reveal your **capitalisation and punctuation
habits** — which single words cannot.

### What makes a good sentence

Write what you would actually send a friend. Not a textbook sentence.

- **Short.** 6–12 words. People abandon long setup screens.
- **Chat register.** Something you'd text, not something you'd publish.
- **Contains contested spellings** — words where people genuinely disagree.
  Names, `v`/`w` sounds, long vowels, `z`/`j` sounds.
- **Five of them**, together covering as many of those disagreements as you can.

Hindi's set, as a model:

```python
"मुझे कल ऑफिस जाना है, तू आ रहा है क्या?"      # mujhe/muze, tu/too
"वो फिर से देर से आया, बहुत ज्यादा टाइम लगा।"   # vo/wo, phir/fir, zyada/jyada
"ठीक है यार, कोई बात नहीं, कल मिलते हैं।"        # theek/thik, nahi/nahin
"कौन सा चाहिए तुझे? किसी वजह से नहीं आया वो।"   # kaun/kon, tujhe/tuze
"पूरा दिन काम किया फिर भी कुछ नहीं हुआ।"        # poora/pura, kiya/kia
```

### Where to put them

[`livewhisper/onboarding.py`](livewhisper/onboarding.py) → the `SENTENCES`
dictionary. Add your language code as a key:

```python
SENTENCES = {
  "hi": [ ... ],
  "ta": [                                    # <- your language
    Prompt("நான் நாளைக்கு வருவேன், நீ வரியா?",
           "I'll come tomorrow, are you coming?",   # English gloss
           "v/w (varuven), ee/i (nee)"),            # what it tests
  ],
}
```

While you're there, add a sentence to `PREVIEW` for the same language — it's
shown at the end of setup to demonstrate the before/after.

There's an issue template for this: **"Add onboarding sentences for a
language"**.

---

## Also genuinely useful

**Curated common words.** `COMMON_WORDS` in
[`livewhisper/script/lexicon.py`](livewhisper/script/lexicon.py) only has Hindi.
Dakshina is a 30,000-word sample, so it misses some very frequent forms — Hindi
was missing `जाऊंगा` ("I will go"), which the character model then mangled. A
list of 50–100 high-frequency words for your language, with the spelling you'd
actually type, measurably improves it.

**Tell us it's wrong.** If the romanization for your language reads badly, that
is a bug report worth filing even without a fix. Paste what it produced and what
you'd have written. That's the most valuable signal we can get, and we have no
way to generate it ourselves.

**macOS and Linux.** Currently Windows-only. The romanization, learning and
profile layers are pure Python and already portable; audio capture
(`audio.py`), screen reading (`context.py`) and paste (`output.py`) are the
platform-specific parts. A clean port would multiply the reach of this project.

---

## Working on the code

```powershell
git clone https://github.com/itsskofficial/LiveWhisper.git
cd LiveWhisper
python -m venv .venv; .\.venv\Scripts\activate
pip install -r requirements.txt
```

Tests, fastest first:

```powershell
python -m tools.check_data      # lexicon integrity, no hardware needed
python -m tools.check_core      # romanization + learning, no hardware needed
python test_pipeline.py         # end-to-end personalisation
python test_alignment.py        # wizard alignment regressions
python test_gui.py              # wizard + settings, on a throwaway profile
python verify.py                # everything, including audio and models
```

The first two run in CI. The rest need a microphone, a GPU or Ollama, so they
run locally only.

### House style

- **Measure before building.** `experiments/` exists because the obvious fix
  (prompting Whisper into romanized output) failed, and finding that out cost an
  hour instead of weeks. If you're adding something non-trivial, an experiment
  that shows it works is worth more than the feature.
- **Comments explain *why*, not *what*.** Especially where the code looks odd —
  most odd-looking code here is odd because something else broke first.
- **Be honest in the docs.** If a number isn't measured, don't state it. The
  README has a "measured, not claimed" section for a reason.

### Enabling CI on a fork

The workflow lives at [`ci/tests.yml`](ci/tests.yml) rather than
`.github/workflows/` — see [docs/CI-SETUP.md](docs/CI-SETUP.md).

---

## Reporting a bug

Useful bug reports for this project include:

- Your language and which app you were typing into
- What you said, what it produced, what you expected
- `python verify.py` output if it's a setup problem

If the app learned something wrong, `profiles.json` in the install directory is
the whole state — attach it (it contains only spellings and rates, no text you
wrote).
