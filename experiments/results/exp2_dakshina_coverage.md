# Experiment 2 - Dakshina lexicon coverage

Measured on real large-v3 output from `accuracy_runs/hinglish.wav` (91 Devanagari tokens, 63 unique).

## Hindi

- lexicon entries: 30,000
- token coverage: **92.3%** (84/91)
- type coverage: **88.9%** (56/63)
- average romanizations per covered word: 1.5
- words with more than one attested form: 25/56

| word | top romanization | variants | alternatives |
|---|---|---|---|
| अगर | `agar` | 1 | - |
| अब | `ab` | 2 | aab |
| आ | **missing** | - | - |
| आखों | **missing** | - | - |
| आप | `aap` | 1 | - |
| आपको | `aapko` | 1 | - |
| इतनी | `itni` | 1 | - |
| इस | `is` | 1 | - |
| उनका | `unka` | 1 | - |
| एक | `ek` | 1 | - |
| और | `aur` | 2 | or |
| कर | `kar` | 1 | - |
| करना | `karna` | 1 | - |
| करेंगे | `karenge` | 1 | - |
| का | `ka` | 1 | - |
| कि | `ki` | 1 | - |
| की | `ki` | 2 | key |
| कुछ | `kuchh` | 2 | kuch |
| के | `ke` | 2 | k |
| कैसे | `kaise` | 3 | case, kese |
| को | `ko` | 2 | co |
| क्यूं | **missing** | - | - |
| खरीद | `kharid` | 2 | khareed |
| चला | `chala` | 1 | - |
| चीज | `chij` | 2 | chees |
| जाएंगे | `jaayenge` | 4 | jaenage, jaenge, jayenge |

Missing (7): आ आखों क्यूं न रोकू लेंगी समझो

## Marathi

- lexicon entries: 30,000
- token coverage: **47.3%** (43/91)
- type coverage: **38.1%** (24/63)
- average romanizations per covered word: 3.0
- words with more than one attested form: 17/24

| word | top romanization | variants | alternatives |
|---|---|---|---|
| अगर | **missing** | - | - |
| अब | **missing** | - | - |
| आ | **missing** | - | - |
| आखों | **missing** | - | - |
| आप | **missing** | - | - |
| आपको | **missing** | - | - |
| इतनी | **missing** | - | - |
| इस | **missing** | - | - |
| उनका | **missing** | - | - |
| एक | `ek` | 2 | aek |
| और | **missing** | - | - |
| कर | `kar` | 1 | - |
| करना | **missing** | - | - |
| करेंगे | **missing** | - | - |
| का | `ka` | 1 | - |
| कि | **missing** | - | - |
| की | `ki` | 7 | kee, key, kii, qee |
| कुछ | **missing** | - | - |
| के | `ke` | 9 | k, kee, qe, cai |
| कैसे | **missing** | - | - |
| को | `ko` | 1 | - |
| क्यूं | **missing** | - | - |
| खरीद | **missing** | - | - |
| चला | `chala` | 1 | - |
| चीज | `chij` | 2 | cheese |
| जाएंगे | **missing** | - | - |

Missing (39): अगर अब आ आखों आप आपको इतनी इस उनका और करना करेंगे कि कुछ कैसे क्यूं खरीद जाएंगे जैसे तेजी दिख पड़ेगा बड़ी बताता बनने बहुत बारे मुझे मेरा मेरे मैं रही रहे रोकू लेंगी वाला वो समझो हूँ

## Hindi + Marathi merged

- lexicon entries: 53,904
- token coverage: **93.4%** (85/91)
- type coverage: **90.5%** (57/63)
- average romanizations per covered word: 1.6
- words with more than one attested form: 26/57

| word | top romanization | variants | alternatives |
|---|---|---|---|
| अगर | `agar` | 1 | - |
| अब | `ab` | 2 | aab |
| आ | **missing** | - | - |
| आखों | **missing** | - | - |
| आप | `aap` | 1 | - |
| आपको | `aapko` | 1 | - |
| इतनी | `itni` | 1 | - |
| इस | `is` | 1 | - |
| उनका | `unka` | 1 | - |
| एक | `ek` | 1 | - |
| और | `aur` | 2 | or |
| कर | `kar` | 1 | - |
| करना | `karna` | 1 | - |
| करेंगे | `karenge` | 1 | - |
| का | `ka` | 1 | - |
| कि | `ki` | 1 | - |
| की | `ki` | 2 | key |
| कुछ | `kuchh` | 2 | kuch |
| के | `ke` | 2 | k |
| कैसे | `kaise` | 3 | case, kese |
| को | `ko` | 2 | co |
| क्यूं | **missing** | - | - |
| खरीद | `kharid` | 2 | khareed |
| चला | `chala` | 1 | - |
| चीज | `chij` | 2 | chees |
| जाएंगे | `jaayenge` | 4 | jaenage, jaenge, jayenge |

Missing (6): आ आखों क्यूं रोकू लेंगी समझो
