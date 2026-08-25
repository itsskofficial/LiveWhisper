#!/usr/bin/env python
"""Experiment 4: can a small model spell the words the dictionary is missing?

exp2 showed a Dakshina lexicon lookup covers 92.3% of Devanagari tokens in real
Whisper output. The remaining 8% are out-of-vocabulary - mostly inflected forms
like लेंगी (feminine future) or रोकू (subjunctive), which are morphologically
regular. A character-level model should be able to spell them by learning the
letter-to-letter patterns, without ever having seen the whole word.

This trains one and checks two things:
  1. accuracy on Dakshina's own held-out test split
  2. what it produces for the 7 real OOV words from our actual sample

Deliberately tiny: this has to run on CPU inside a desktop app.

    python experiments/exp4_oov_seq2seq.py <dakshina-root>
"""

from __future__ import annotations

import math
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import torch
import torch.nn as nn

OUT = Path("experiments/results")
SEED = 17

# The 7 tokens the lexicon could not resolve, from exp3 on real audio.
REAL_OOV = ["क्यूं", "लेंगी", "समझो", "आ", "आखों", "रोकू", "न"]
# What a fluent Hinglish typist would plausibly write, for eyeballing only.
PLAUSIBLE = {
    "क्यूं": {"kyun", "kyu", "kyon"},
    "लेंगी": {"lengi", "lengee"},
    "समझो": {"samjho", "samajho"},
    "आ": {"aa", "a"},
    "आखों": {"aankhon", "ankhon", "aakhon"},
    "रोकू": {"roku", "rokun", "rokoo"},
    "न": {"na", "n", "naa"},
}

PAD, BOS, EOS = 0, 1, 2


def load_pairs(root: Path, lang: str, split: str) -> list[tuple[str, str]]:
    path = root / lang / "lexicons" / f"{lang}.translit.sampled.{split}.tsv"
    pairs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2 and parts[0].strip() and parts[1].strip():
                pairs.append((parts[0].strip(), parts[1].strip()))
    return pairs


class Vocab:
    def __init__(self, texts):
        chars = sorted({c for t in texts for c in t})
        self.itos = ["<pad>", "<bos>", "<eos>"] + chars
        self.stoi = {c: i for i, c in enumerate(self.itos)}

    def __len__(self):
        return len(self.itos)

    def encode(self, s: str, bos=False, eos=False) -> list[int]:
        ids = [self.stoi[c] for c in s if c in self.stoi]
        if bos:
            ids = [BOS] + ids
        if eos:
            ids = ids + [EOS]
        return ids


class Transliterator(nn.Module):
    """Char-level encoder-decoder. Small on purpose - this runs on CPU."""

    def __init__(self, n_src, n_tgt, d=192, heads=4, layers=3, ff=512, drop=0.1):
        super().__init__()
        self.d = d
        self.src_emb = nn.Embedding(n_src, d, padding_idx=PAD)
        self.tgt_emb = nn.Embedding(n_tgt, d, padding_idx=PAD)
        self.pos = nn.Embedding(64, d)
        self.core = nn.Transformer(d_model=d, nhead=heads,
                                   num_encoder_layers=layers,
                                   num_decoder_layers=layers,
                                   dim_feedforward=ff, dropout=drop,
                                   batch_first=True)
        self.out = nn.Linear(d, n_tgt)

    def _embed(self, x, emb):
        pos = torch.arange(x.size(1), device=x.device).unsqueeze(0)
        return emb(x) * math.sqrt(self.d) + self.pos(pos)

    def forward(self, src, tgt):
        mask = nn.Transformer.generate_square_subsequent_mask(
            tgt.size(1), device=tgt.device)
        h = self.core(self._embed(src, self.src_emb),
                      self._embed(tgt, self.tgt_emb),
                      tgt_mask=mask,
                      src_key_padding_mask=(src == PAD),
                      tgt_key_padding_mask=(tgt == PAD))
        return self.out(h)

    @torch.no_grad()
    def greedy(self, src, max_len=32):
        self.eval()
        memory_in = self._embed(src, self.src_emb)
        pad = (src == PAD)
        mem = self.core.encoder(memory_in, src_key_padding_mask=pad)
        ys = torch.full((src.size(0), 1), BOS, dtype=torch.long, device=src.device)
        done = torch.zeros(src.size(0), dtype=torch.bool, device=src.device)
        for _ in range(max_len):
            m = nn.Transformer.generate_square_subsequent_mask(
                ys.size(1), device=ys.device)
            h = self.core.decoder(self._embed(ys, self.tgt_emb), mem, tgt_mask=m,
                                  memory_key_padding_mask=pad)
            nxt = self.out(h[:, -1]).argmax(-1, keepdim=True)
            ys = torch.cat([ys, nxt], dim=1)
            done |= nxt.squeeze(1) == EOS
            if done.all():
                break
        return ys


def batchify(pairs, sv, tv, bs, shuffle=True):
    idx = list(range(len(pairs)))
    if shuffle:
        random.shuffle(idx)
    for i in range(0, len(idx), bs):
        chunk = [pairs[j] for j in idx[i:i + bs]]
        src = [sv.encode(s, eos=True) for s, _ in chunk]
        tgt = [tv.encode(t, bos=True, eos=True) for _, t in chunk]
        ms, mt = max(len(x) for x in src), max(len(x) for x in tgt)
        S = torch.full((len(chunk), ms), PAD, dtype=torch.long)
        T = torch.full((len(chunk), mt), PAD, dtype=torch.long)
        for k, (a, b) in enumerate(zip(src, tgt)):
            S[k, :len(a)] = torch.tensor(a)
            T[k, :len(b)] = torch.tensor(b)
        yield S, T


def decode(ids, tv) -> str:
    out = []
    for i in ids.tolist()[1:]:
        if i == EOS:
            break
        if i > EOS:
            out.append(tv.itos[i])
    return "".join(out)


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("dakshina_dataset_v1.0")
    if not root.exists():
        print(f"dakshina root not found: {root}")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    random.seed(SEED)
    torch.manual_seed(SEED)

    train = load_pairs(root, "hi", "train")
    test = load_pairs(root, "hi", "test")
    print(f"train pairs {len(train):,}   test pairs {len(test):,}")

    sv = Vocab([s for s, _ in train])
    tv = Vocab([t for _, t in train])
    print(f"src chars {len(sv)}   tgt chars {len(tv)}")

    model = Transliterator(len(sv), len(tv))
    params = sum(p.numel() for p in model.parameters())
    print(f"model parameters {params/1e6:.2f}M  (CPU)\n")

    opt = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=0.01)
    lossf = nn.CrossEntropyLoss(ignore_index=PAD, label_smoothing=0.1)
    EPOCHS, BS = 12, 256

    t0 = time.time()
    for ep in range(1, EPOCHS + 1):
        model.train()
        total = n = 0
        for S, T in batchify(train, sv, tv, BS):
            opt.zero_grad()
            logits = model(S, T[:, :-1])
            loss = lossf(logits.reshape(-1, logits.size(-1)), T[:, 1:].reshape(-1))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            total += loss.item()
            n += 1
        print(f"  epoch {ep:2d}/{EPOCHS}  loss {total/n:.3f}  "
              f"({time.time()-t0:.0f}s elapsed)")

    # --- eval: a prediction counts as correct if it matches ANY attested form,
    # because exp2 showed 45% of words have several valid romanizations.
    attested = defaultdict(set)
    for s, t in test:
        attested[s].add(t)
    words = sorted(attested)

    correct = 0
    preds = {}
    for i in range(0, len(words), 256):
        chunk = words[i:i + 256]
        enc = [sv.encode(w, eos=True) for w in chunk]
        m = max(len(x) for x in enc)
        S = torch.full((len(chunk), m), PAD, dtype=torch.long)
        for k, a in enumerate(enc):
            S[k, :len(a)] = torch.tensor(a)
        for w, row in zip(chunk, model.greedy(S)):
            p = decode(row, tv)
            preds[w] = p
            if p in attested[w]:
                correct += 1

    acc = correct / len(words) * 100
    print(f"\nheld-out test: {correct}/{len(words)} = {acc:.1f}% "
          f"match an attested romanization")

    # --- the real question: the 7 OOV words from actual audio
    print("\nreal OOV words from exp3:")
    lines = ["# Experiment 4 - character model for out-of-vocabulary words\n\n",
             f"- train pairs: {len(train):,}\n- model: {params/1e6:.2f}M params, CPU\n",
             f"- held-out accuracy: **{acc:.1f}%** "
             f"({correct}/{len(words)} match an attested form)\n\n",
             "## The 7 real OOV words\n\n| word | model output | plausible? |\n|---|---|---|\n"]

    enc = [sv.encode(w, eos=True) for w in REAL_OOV]
    m = max(len(x) for x in enc)
    S = torch.full((len(REAL_OOV), m), PAD, dtype=torch.long)
    for k, a in enumerate(enc):
        S[k, :len(a)] = torch.tensor(a)
    hits = 0
    for w, row in zip(REAL_OOV, model.greedy(S)):
        p = decode(row, tv)
        ok = p in PLAUSIBLE.get(w, set())
        hits += ok
        print(f"  {w:<8} -> {p:<12} {'OK' if ok else '?'}")
        lines.append(f"| {w} | `{p}` | {'yes' if ok else 'no'} |\n")

    lines.append(f"\n{hits}/{len(REAL_OOV)} matched a plausible spelling.\n")
    print(f"\n{hits}/{len(REAL_OOV)} plausible")

    torch.save({"model": model.state_dict(),
                "src_itos": sv.itos, "tgt_itos": tv.itos},
               OUT / "translit_hi.pt")
    size_mb = (OUT / "translit_hi.pt").stat().st_size / 1e6
    lines.append(f"\nCheckpoint: {size_mb:.1f} MB\n")
    print(f"checkpoint {size_mb:.1f} MB")

    (OUT / "exp4_oov_seq2seq.md").write_text("".join(lines), encoding="utf-8")
    print(f"wrote {OUT / 'exp4_oov_seq2seq.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
