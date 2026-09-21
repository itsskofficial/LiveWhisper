# Benchmark: romanization vs human ground truth

500 sentences per language from Dakshina's human-romanized corpus. These are sentences a person wrote out in Latin letters; we compare our output to theirs.

| language | sentences | WER | identical | acceptable | wrong | untouched |
|---|---|---|---|---|---|---|
| Hindi | 500 | 25.2% | 75.0% | 93.5% | 6.5% | 0.0% |
| Bengali | 500 | 43.7% | 58.9% | 81.8% | 18.2% | 0.0% |
| Urdu | 500 | 37.4% | 63.7% | 90.7% | 9.3% | 0.0% |
| Punjabi | 500 | 37.3% | 62.7% | 91.6% | 8.4% | 0.0% |
| Marathi | 500 | 32.7% | 69.3% | 87.7% | 12.3% | 0.0% |
| Telugu | 500 | 42.5% | 58.1% | 79.2% | 20.8% | 0.0% |
| Tamil | 500 | 51.4% | 48.7% | 75.6% | 24.4% | 0.0% |
| Gujarati | 500 | 52.3% | 48.2% | 84.5% | 15.5% | 0.0% |
| Kannada | 500 | 31.7% | 69.2% | 81.8% | 18.2% | 0.0% |
| Malayalam | 500 | 49.7% | 50.2% | 73.4% | 26.6% | 0.0% |
| Sinhala | 500 | 36.9% | 64.8% | 84.4% | 15.6% | 0.0% |
| Sindhi | 500 | 43.0% | 60.0% | 83.4% | 16.6% | 0.0% |

**Average — WER 40.3%, identical to human 60.7%, acceptable 84.0%, unambiguously wrong 16.0%, untouched 0.0%**

## Reading these numbers

**Acceptable is the honest headline.** Romanization has no single right answer -
Dakshina itself records several accepted spellings for 45% of words. Strict WER
penalises `nahi` against a human's `nahin`, which is not an error anybody would
report. `acceptable` counts our word right if it matches the human OR if both
are spellings Dakshina records for that word.

**Wrong** is the bucket that genuinely is wrong: a spelling nobody offered.

**Untouched** is the one number with no ambiguity: native-script words still
sitting in the output because neither the dictionary nor the model could spell
them. Those are visibly wrong to a user, so it is the metric to drive down.
