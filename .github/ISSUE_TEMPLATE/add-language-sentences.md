---
name: Add onboarding sentences for a language
about: Ten minutes, one file edit, no Python needed. The most useful contribution here.
title: "Onboarding sentences: [your language]"
labels: ["good first issue", "language"]
---

## Which language?

<!-- e.g. Tamil (ta), Bengali (bn) -->

## Your five sentences

Write what you'd actually send a friend — not a textbook sentence. Short (6–12
words), chat register, and between them covering as many contested spellings as
you can: names, `v`/`w` sounds, long vowels, `z`/`j` sounds.

For each, give the sentence in your script, an English gloss, and (optionally)
which spelling disagreements it tests.

```
1. <your script>
   English: 
   Tests: 

2. 
   English: 
   Tests: 

3. 
   English: 
   Tests: 

4. 
   English: 
   Tests: 

5. 
   English: 
   Tests: 
```

## One preview sentence

Shown at the end of setup to demonstrate the before/after. Any natural sentence
in your language:

```

```

## Does the current romanization look right?

Run this and paste the output — it tells us whether the lexicon is producing
spellings a native speaker would actually write:

```powershell
python -c "from livewhisper.script.romanize import Romanizer; print(Romanizer('XX').text('<a sentence in your script>'))"
```

<!-- replace XX with your language code -->

**Anything that looks wrong here is worth reporting even if you don't send a
fix.** We have no way to judge this ourselves for most of these languages.
