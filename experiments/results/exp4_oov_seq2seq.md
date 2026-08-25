# Experiment 4 - character model for out-of-vocabulary words

- train pairs: 44,204
- model: 2.56M params, CPU
- held-out accuracy: **63.2%** (1581/2500 match an attested form)

## The 7 real OOV words

| word | model output | plausible? |
|---|---|---|
| क्यूं | `kyun` | yes |
| लेंगी | `lengi` | yes |
| समझो | `samjho` | yes |
| आ | `aaaaaaaaaaaaaaa` | no |
| आखों | `aakhon` | yes |
| रोकू | `roku` | yes |
| न | `nanan` | no |

5/7 matched a plausible spelling.

Checkpoint: 10.3 MB
