# tools

Rebuild what ships in `data/`. None of these run in the app.

| Tool | Does |
| --- | --- |
| `build_lexicons.py` | build the twelve lexicons from Google's Dakshina dataset |
| `rerank_lexicons.py` | order each word's spellings by how people write in sentences |
| `train_transliterator.py` | train the character model for words the lexicons miss (needs torch) |
| `export_translit.py` | export that model to `data/translit.npz`, which the app runs in numpy |
| `check_data.py` | the lexicons are present and well formed (runs in CI) |
| `check_core.py` | romanization and learning logic, no hardware needed (runs in CI) |

Run as modules from the repository root: `python -m tools.check_data`.
