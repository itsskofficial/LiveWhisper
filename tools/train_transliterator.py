#!/usr/bin/env python
"""Train one character model that romanizes all twelve languages.

The lexicon handles ~87% of words. This handles the rest by learning letter
patterns, so it can spell forms it has never seen.

One model rather than twelve: the scripts are different but the task is the
same, the shared decoder learns Latin spelling conventions once, and a single
10 MB file ships instead of twelve. Language is signalled by a tag token
prepended to the input, since the same sound romanizes differently across
languages.

    python tools/train_transliterator.py <dakshina-root> [--epochs 8] [--per-lang 30000]

Writes data/translit.pt
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from livewhisper.script.languages import CODES, LANGUAGES  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"
PAD, BOS, EOS = 0, 1, 2
SEED = 17


def load_pairs(root: Path, lang: str, split: str) -> list:
    path = root / lang / "lexicons" / f"{lang}.translit.sampled.{split}.tsv"
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 2 and p[0].strip() and p[1].strip():
                out.append((p[0].strip(), p[1].strip()))
    return out


class Vocab:
    def __init__(self, texts, extra=()):
        chars = sorted({c for t in texts for c in t})
        self.itos = ["<pad>", "<bos>", "<eos>"] + list(extra) + chars
        self.stoi = {c: i for i, c in enumerate(self.itos)}

    def __len__(self):
        return len(self.itos)

    def encode(self, s, bos=False, eos=False, prefix=()):
        ids = [self.stoi[c] for c in s if c in self.stoi]
        ids = [self.stoi[p] for p in prefix if p in self.stoi] + ids
        if bos:
            ids = [BOS] + ids
        if eos:
            ids = ids + [EOS]
        return ids


class Transliterator(nn.Module):
    def __init__(self, n_src, n_tgt, d=256, heads=4, layers=3, ff=640, drop=0.1):
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
                      self._embed(tgt, self.tgt_emb), tgt_mask=mask,
                      src_key_padding_mask=(src == PAD),
                      tgt_key_padding_mask=(tgt == PAD))
        return self.out(h)

    @torch.no_grad()
    def greedy(self, src, max_len=24):
        self.eval()
        pad = (src == PAD)
        mem = self.core.encoder(self._embed(src, self.src_emb),
                                src_key_padding_mask=pad)
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


def batches(data, sv, tv, bs, device, shuffle=True):
    idx = list(range(len(data)))
    if shuffle:
        random.shuffle(idx)
    for i in range(0, len(idx), bs):
        chunk = [data[j] for j in idx[i:i + bs]]
        src = [sv.encode(n, eos=True, prefix=(f"<{lg}>",)) for lg, n, _ in chunk]
        tgt = [tv.encode(r, bos=True, eos=True) for _, _, r in chunk]
        ms, mt = max(map(len, src)), max(map(len, tgt))
        S = torch.full((len(chunk), ms), PAD, dtype=torch.long)
        T = torch.full((len(chunk), mt), PAD, dtype=torch.long)
        for k, (a, b) in enumerate(zip(src, tgt)):
            S[k, :len(a)] = torch.tensor(a)
            T[k, :len(b)] = torch.tensor(b)
        yield S.to(device), T.to(device)


def decode(ids, tv):
    out = []
    for i in ids.tolist()[1:]:
        if i == EOS:
            break
        if i > EOS:
            out.append(tv.itos[i])
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--per-lang", type=int, default=30000)
    ap.add_argument("--batch", type=int, default=512)
    args = ap.parse_args()

    random.seed(SEED)
    torch.manual_seed(SEED)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(max(1, (torch.get_num_threads() or 8)))

    train, test = [], defaultdict(list)
    for code in CODES:
        pairs = load_pairs(args.root, code, "train")
        if not pairs:
            print(f"  {code}: no data, skipped")
            continue
        random.shuffle(pairs)
        pairs = pairs[:args.per_lang]
        train += [(code, n, r) for n, r in pairs]
        for n, r in load_pairs(args.root, code, "test")[:1500]:
            test[code].append((n, r))
        print(f"  {code}: {len(pairs):,} train")

    tags = [f"<{c}>" for c in CODES]
    sv = Vocab([n for _, n, _ in train], extra=tags)
    tv = Vocab([r for _, _, r in train])
    print(f"\ntrain {len(train):,} pairs | src {len(sv)} chars | tgt {len(tv)} "
          f"| device {device}")

    model = Transliterator(len(sv), len(tv)).to(device)
    params = sum(p.numel() for p in model.parameters())
    print(f"model {params/1e6:.2f}M params\n")

    opt = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=0.01)
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=1e-3, total_steps=args.epochs *
        ((len(train) + args.batch - 1) // args.batch))
    lossf = nn.CrossEntropyLoss(ignore_index=PAD, label_smoothing=0.1)

    t0 = time.time()
    for ep in range(1, args.epochs + 1):
        model.train()
        tot = n = 0
        for S, T in batches(train, sv, tv, args.batch, device):
            opt.zero_grad()
            logits = model(S, T[:, :-1])
            loss = lossf(logits.reshape(-1, logits.size(-1)), T[:, 1:].reshape(-1))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            tot += loss.item()
            n += 1
        print(f"  epoch {ep}/{args.epochs}  loss {tot/n:.3f}  "
              f"({time.time()-t0:.0f}s)", flush=True)

    # Per-language accuracy: any attested spelling counts, since exp2 showed
    # 45% of words have several valid ones.
    print("\nper-language accuracy (any attested spelling counts):")
    report = []
    for code, pairs in test.items():
        attested = defaultdict(set)
        for n, r in pairs:
            attested[n].add(r)
        words = sorted(attested)
        correct = 0
        for i in range(0, len(words), 256):
            chunk = words[i:i + 256]
            enc = [sv.encode(w, eos=True, prefix=(f"<{code}>",)) for w in chunk]
            m = max(map(len, enc))
            S = torch.full((len(chunk), m), PAD, dtype=torch.long)
            for k, e in enumerate(enc):
                S[k, :len(e)] = torch.tensor(e)
            for w, row in zip(chunk, model.greedy(S.to(device))):
                if decode(row, tv) in attested[w]:
                    correct += 1
        acc = correct / len(words) * 100 if words else 0
        report.append((code, acc, len(words)))
        print(f"  {LANGUAGES[code].name:<12} {acc:5.1f}%  ({len(words)} words)")

    avg = sum(a for _, a, _ in report) / len(report) if report else 0
    print(f"  {'AVERAGE':<12} {avg:5.1f}%")

    out = DATA / "translit.pt"
    torch.save({"model": model.state_dict(), "src_itos": sv.itos,
                "tgt_itos": tv.itos, "languages": CODES,
                "accuracy": {c: a for c, a, _ in report}}, out)
    print(f"\nwrote {out} ({out.stat().st_size/1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
