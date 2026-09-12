# Enabling CI

The workflow is at `ci/tests.yml` rather than `.github/workflows/tests.yml`
because the token used to push it lacked the `workflow` scope, and GitHub
refuses workflow files without it.

To enable it:

```bash
gh auth refresh -h github.com -s workflow
mkdir -p .github/workflows
cp ci/tests.yml .github/workflows/tests.yml
git add .github/workflows/tests.yml
git commit -m "Enable CI"
git push
```

Then remove `.github/workflows/` from `.gitignore`.

Once it runs, add the badge to the top of the README:

```markdown
[![tests](https://github.com/itsskofficial/LiveWhisper/actions/workflows/tests.yml/badge.svg)](https://github.com/itsskofficial/LiveWhisper/actions/workflows/tests.yml)
```

## What it runs

GitHub runners have no sound card and no GPU, so the audio and ASR stack is not
installed there. What is tested is the part most likely to break and least
likely to be noticed: lexicon integrity across all twelve languages,
romanization, the rules governing what may be learned, habits, and profile
persistence. All pure Python, all hardware-free.

Matrix: Windows and Ubuntu, Python 3.10 and 3.12.
