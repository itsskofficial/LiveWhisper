# Experiment 7 - does the approach hold across twelve languages?

Lexicon coverage measured per language. `held-out` uses Dakshina's test split; `in running text` weights by how often words actually occur, which is closer to what speech contains.

| language | | speakers | lexicon | held-out | in running text |
|---|---|---|---|---|---|
| Hindi | Hinglish | 610M | 30,000 | 100.0% | 87.3% |
| Bengali | Banglish | 270M | 30,000 | 100.0% | 83.4% |
| Urdu | Urdish | 230M | 30,000 | 100.0% | 92.1% |
| Punjabi | Punglish | 125M | 30,000 | 100.0% | 91.4% |
| Marathi | Minglish | 83M | 30,000 | 100.0% | 90.9% |
| Telugu | Thanglish | 83M | 30,000 | 100.0% | 86.2% |
| Tamil | Tanglish | 79M | 30,000 | 100.0% | 86.9% |
| Gujarati | Gujlish | 57M | 30,000 | 100.0% | 90.8% |
| Kannada | Kanglish | 44M | 30,000 | 100.0% | 88.2% |
| Malayalam | Manglish | 38M | 30,000 | 100.0% | 88.1% |
| Sinhala | Singlish | 17M | 30,000 | 100.0% | 76.2% |
| Sindhi | Sindhlish | 32M | 20,000 | 100.0% | 88.0% |

**Average across 12 languages: 100.0% held-out, 87.4% in running text. Combined reach ~1.7 billion speakers.**
