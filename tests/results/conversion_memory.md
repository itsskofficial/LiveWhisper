# Converting a speech model: how much memory it really takes

Measured on the development machine: 16 GB RAM, Windows 11, system-managed
pagefile on the SSD. "Peak commit" is the converting process's own
`PeakPagefileUsage`, printed by `scripts/convert_ct2.py` at the end of every run.
"Committable at start" is Windows' commit limit minus what was already
committed, read just before the conversion began.

## Lone conversions — nothing else heavy running

| Model | Checkpoint | Committable at start | Peak commit | Result |
| --- | --- | --- | --- | --- |
| Gujarati whisper-medium, converted directly | 3.06 GB float32 pickle | 7.1 GB | **6.9 GB** (2.25×) | ok, 34 s |
| Kannada whisper-medium, re-saved as float16 | 3.06 GB float32 pickle | 3.9 GB | 6.8 GB | ok, 17 s |
| Kannada whisper-medium, from the float16 copy | 1.53 GB float16 safetensors | ~3.0 GB | 4.5 GB | ok, 23 s |
| Urdu whisper-large-v3-turbo, converted directly | 3.24 GB float32 safetensors | — | **7.9 GB** (2.44×) | ok, 39 s |
| Marathi whisper-large-v2, converted directly | 6.17 GB float32 pickle | limit rising mid-run | **11.4 GB** (1.85×) | ok, 78 s |

Across the three direct conversions the peak ranged from 1.85× to 2.44× the
checkpoint. `livewhisper/resources.py` uses 2.5× as the full-peak factor, above
the worst ratio measured.

Two things follow.

**Converting through a float16 copy saves nothing.** Its worst step peaks at the
same ~6.9 GB as converting the original directly; it only splits the work.

**A lone conversion succeeds with less committable memory than it will use.**
Kannada's re-save started with 3.9 GB committable and peaked at 6.8 GB: Windows
grew the pagefile to cover it. The commit limit was observed rising from 44.6 to
49.0 GB during that run.

## The crashes

Every conversion that died — seven Kannada attempts and one plain `torch.load`
of the Tamil checkpoint — did so with an access violation and no traceback,
while three or more heavy processes (benchmarks committing 4–5 GB each, plus
other conversions) were allocating at the same time. Windows logged "low virtual
memory condition" (Resource-Exhaustion-Detector, event 2004) in the same
minutes. The checkpoint was intact throughout: its SHA-256 matched Hugging Face,
and a plain `torch.load` of it succeeded whenever memory was free.

## What that means for the gate

The danger is not a conversion needing more memory than is free at the moment it
starts — Windows handles that by growing the pagefile. The danger is several
processes racing for memory at once. So the guards that matter are:

- one conversion at a time (the machine-wide lock), and
- no benchmark or conversion starting into a machine that is already exhausted.

Reserving the full peak up front — which the first version of the gate did — left
a conversion waiting indefinitely on a 16 GB machine with ordinary applications
open, while holding up everything queued behind it.
