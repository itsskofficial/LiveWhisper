# Benchmark: romanization vs human ground truth

500 sentences per language from Dakshina's human-romanized corpus. These are sentences a person wrote out in Latin letters; we compare our output to theirs.

| language | sentences | WER | identical | acceptable | wrong | untouched |
|---|---|---|---|---|---|---|
| Hindi | 500 | 25.3% | 74.9% | 93.4% | 6.6% | 0.2% |
| Bengali | 500 | 43.9% | 58.7% | 81.7% | 18.3% | 1.1% |
| Urdu | 500 | 37.4% | 63.7% | 90.7% | 9.3% | 0.1% |
| Punjabi | 500 | 37.5% | 62.5% | 91.4% | 8.6% | 0.7% |
| Marathi | 500 | 32.9% | 69.1% | 87.5% | 12.5% | 0.7% |
| Telugu | 500 | 42.7% | 57.8% | 78.9% | 21.1% | 1.0% |
| Tamil | 500 | 51.4% | 48.6% | 75.5% | 24.5% | 1.3% |
| Gujarati | 500 | 52.7% | 47.8% | 84.1% | 15.9% | 0.8% |
| Kannada | 500 | 33.1% | 67.9% | 80.4% | 19.6% | 1.1% |
| Malayalam | 500 | 49.9% | 50.0% | 73.2% | 26.8% | 2.8% |
| Sinhala | 500 | 37.3% | 64.4% | 84.1% | 15.9% | 1.6% |
| Sindhi | 500 | 43.3% | 59.6% | 83.1% | 16.9% | 0.6% |

**Average — WER 40.6%, identical to human 60.4%, acceptable 83.7%, unambiguously wrong 16.3%, untouched 1.0%**

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
