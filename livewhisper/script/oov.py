"""Character model for words the lexicon does not contain (~8% of tokens).

A 2.56M-parameter encoder-decoder trained on 44k Dakshina word pairs. It learns
letter patterns rather than words, so it can spell forms it has never seen -
लेंगी -> "lengi" without that word being in any dictionary (exp4).

Torch is an optional dependency. Without it the lexicon still covers 92% of
tokens; unknown words simply pass through in Devanagari rather than crashing.
"""

from __future__ import annotations

import logging
import math
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

DATA = Path(__file__).resolve().parent.parent.parent / "data"
MULTI_CHECKPOINT = DATA / "translit.pt"          # all languages, one model
LEGACY_CHECKPOINT = DATA / "translit_hi.pt"      # hindi-only, older builds

PAD, BOS, EOS = 0, 1, 2
MAX_OUT = 24

# The positional embedding has 64 slots, so a longer input indexes off the end
# and raises IndexError deep inside the encoder. Real words never come close -
# the longest in any shipped lexicon is 39 characters - but a transcript can
# arrive with no spaces at all, and then the whole utterance is one "word".
# Whisper does exactly this on run-on speech in Indic languages.
#
# 48 leaves headroom under 64 for the language tag and EOS. Anything longer is
# not a word the model was trained to spell anyway, so it is left in the native
# script: visible and correctable, which is the better failure.
MAX_IN = 48


def _architecture(state: dict) -> dict:
    """Recover the model's shape from its own weights.

    Hardcoding the architecture here as well as in the trainer meant the two
    could drift apart - and they did: the trainer moved to d=256 while this
    still said 192, so the checkpoint failed to load and the app silently fell
    back to dictionary-only. Reading it off the tensors cannot drift.
    """
    d = state["src_emb.weight"].shape[1]
    ff = state["core.encoder.layers.0.linear1.weight"].shape[0]
    layers = len({k.split(".")[3] for k in state
                  if k.startswith("core.encoder.layers.")})
    heads = 4 if d % 4 == 0 else 8         # not recoverable; 4 is what we train
    return {"d": d, "ff": ff, "layers": layers, "heads": heads}


def _build():
    import torch
    import torch.nn as nn

    class Transliterator(nn.Module):
        def __init__(self, n_src, n_tgt, d=192, heads=4, layers=3, ff=512):
            super().__init__()
            self.d = d
            self.src_emb = nn.Embedding(n_src, d, padding_idx=PAD)
            self.tgt_emb = nn.Embedding(n_tgt, d, padding_idx=PAD)
            self.pos = nn.Embedding(64, d)
            self.core = nn.Transformer(d_model=d, nhead=heads,
                                       num_encoder_layers=layers,
                                       num_decoder_layers=layers,
                                       dim_feedforward=ff, dropout=0.0,
                                       batch_first=True)
            self.out = nn.Linear(d, n_tgt)

        def _embed(self, x, emb):
            pos = torch.arange(x.size(1), device=x.device).unsqueeze(0)
            return emb(x) * math.sqrt(self.d) + self.pos(pos)

        @torch.no_grad()
        def greedy(self, src, max_len=MAX_OUT):
            pad = (src == PAD)
            mem = self.core.encoder(self._embed(src, self.src_emb),
                                    src_key_padding_mask=pad)
            ys = torch.full((src.size(0), 1), BOS, dtype=torch.long)
            done = torch.zeros(src.size(0), dtype=torch.bool)
            for _ in range(max_len):
                m = nn.Transformer.generate_square_subsequent_mask(ys.size(1))
                h = self.core.decoder(self._embed(ys, self.tgt_emb), mem,
                                      tgt_mask=m, memory_key_padding_mask=pad)
                nxt = self.out(h[:, -1]).argmax(-1, keepdim=True)
                ys = torch.cat([ys, nxt], dim=1)
                done |= nxt.squeeze(1) == EOS
                if done.all():
                    break
            return ys

    return Transliterator


class OOVModel:
    """Lazily loaded; absence is not an error."""

    def __init__(self):
        self._model = None
        self._src = self._tgt = None
        self._tried = False
        self.available = False
        self.multilingual = False
        self.languages: set = set()

    def load(self) -> bool:
        if self._tried:
            return self.available
        self._tried = True
        checkpoint = (MULTI_CHECKPOINT if MULTI_CHECKPOINT.exists()
                      else LEGACY_CHECKPOINT)
        if not checkpoint.exists():
            log.info("no transliteration checkpoint in %s", DATA)
            return False
        try:
            import torch
        except ImportError:
            log.info("torch not installed - unknown words will pass through")
            return False
        try:
            ck = torch.load(checkpoint, map_location="cpu", weights_only=False)
            self.languages = set(ck.get("languages") or ["hi"])
            self.multilingual = bool(ck.get("languages"))
            self._src = {c: i for i, c in enumerate(ck["src_itos"])}
            self._tgt = ck["tgt_itos"]
            cls = _build()
            arch = ck.get("arch") or _architecture(ck["model"])
            self._model = cls(len(ck["src_itos"]), len(ck["tgt_itos"]), **arch)
            self._model.load_state_dict(ck["model"])
            self._model.eval()
            self.available = True
            log.info("transliteration model ready: d=%d, %d chars, languages %s",
                     arch["d"], len(self._src), ",".join(sorted(self.languages)))
        except Exception:
            log.warning("could not load transliteration model", exc_info=True)
        return self.available

    def spell(self, words: list[str], lang: str = "hi") -> dict[str, str]:
        """Romanize a batch of unknown native-script words.

        The multilingual model is told which language it is reading via a tag
        character prepended to the input, because the same letter can romanize
        differently across scripts.
        """
        if not words or not self.load():
            return {}
        if self.multilingual and lang not in self.languages:
            return {}
        import torch

        # Over-long inputs would index past the positional embedding. Drop them
        # here rather than truncating: a spelling derived from the first 48
        # characters of a 600-character blob would be confidently wrong, and
        # leaving the native script is the honest outcome.
        words = [w for w in words if len(w) <= MAX_IN]
        if not words:
            return {}

        tag = [self._src[f"<{lang}>"]] if (self.multilingual
                                           and f"<{lang}>" in self._src) else []
        enc = [tag + [self._src[c] for c in w if c in self._src] + [EOS]
               for w in words]
        enc = [e if len(e) > 1 else [EOS] for e in enc]
        width = max(len(e) for e in enc)
        S = torch.full((len(enc), width), PAD, dtype=torch.long)
        for k, e in enumerate(enc):
            S[k, :len(e)] = torch.tensor(e)

        out = {}
        for w, row in zip(words, self._model.greedy(S)):
            chars = []
            for i in row.tolist()[1:]:
                if i == EOS:
                    break
                if i > EOS:
                    chars.append(self._tgt[i])
            guess = "".join(chars)
            # Guard against the degenerate repetition seen on very short inputs.
            if guess and not _degenerate(guess):
                out[w] = guess
        return out


def _degenerate(s: str) -> bool:
    """Reject the model's known failure mode: looping output.

    exp4 saw "aaaaaaaa" for आ and "nanan" for न. A milder version appeared in
    testing as जाऊंगा -> "jaaungaanga", where a trigram recurs. Rejecting is
    safe: the word falls back to Devanagari, which is visible and correctable,
    rather than a plausible-looking wrong spelling that slips past unnoticed.
    """
    if len(s) >= 4 and len(set(s)) <= 2:
        return True
    if len(s) > MAX_OUT - 2:
        return True
    if len(s) >= 9:
        grams = [s[i:i + 3] for i in range(len(s) - 2)]
        if len(grams) - len(set(grams)) >= 2:
            return True
    return False


@lru_cache(maxsize=1)
def get_model() -> OOVModel:
    return OOVModel()
