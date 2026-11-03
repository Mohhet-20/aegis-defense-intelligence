"""Lexical retrieval: tokenisation, stop words and Okapi BM25.

BM25 scores are relative ranking signals inside one result set. They are NOT
probabilities and say nothing about whether a statement is true."""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Iterable, Sequence

STOPWORDS = frozenset(
    "a an and are as at be but by for from has have how i if in into is it its of on or that the their then there these this "
    "to was were what when where which who whom why will with about any all can could did do does done during had he her his "
    "me my no not our she should so than they them we you your show tell give list find".split()
)
_TOKEN = re.compile(r"[a-z0-9][a-z0-9_\-./:]*[a-z0-9]|[a-z0-9]")


_SPLIT = re.compile(r"[_\-./:]+")


def tokenize(text: str, *, drop_stopwords: bool = True) -> list[str]:
    """Lower-cased word tokens. A compound such as `harbor_photo.png` or
    `02:10` is kept whole AND also emitted as its parts, so a search for
    `harbor_photo` or `02` can still find it."""
    text = unicodedata.normalize("NFKC", text or "").lower()
    toks: list[str] = []
    for raw in _TOKEN.findall(text):
        t = raw.strip(".-_/:")
        if not t:
            continue
        toks.append(t)
        if _SPLIT.search(t):
            toks.extend(p for p in _SPLIT.split(t) if len(p) >= 2)
    return [t for t in toks if t not in STOPWORDS] if drop_stopwords else toks


def query_terms(query: str, max_terms: int = 8) -> list[str]:
    seen: list[str] = []
    for t in tokenize(query):
        if t not in seen:
            seen.append(t)
    return seen[:max_terms]


def idf(n_docs: int, df: int) -> float:
    return math.log(1 + (n_docs - df + 0.5) / (df + 0.5))


def bm25_scores(
    terms: Sequence[str], docs: Sequence[str], *, n_docs: int, avg_len: float, df: dict[str, int], k1: float = 1.5, b: float = 0.75
) -> list[tuple[float, list[str]]]:
    """Per document: (score, matched_terms). Matching is on whole tokens."""
    results: list[tuple[float, list[str]]] = []
    avg = avg_len if avg_len > 0 else 1.0
    for d in docs:
        toks = tokenize(d)
        tf = Counter(toks)
        dl = len(toks) or 1
        score = 0.0
        matched: list[str] = []
        for t in terms:
            f = tf.get(t, 0)
            if f == 0:
                continue
            matched.append(t)
            score += idf(max(n_docs, 1), min(df.get(t, 1), max(n_docs, 1))) * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avg))
        results.append((score, matched))
    return results


def excerpt(text: str, terms: Iterable[str], width: int = 280) -> str:
    """A bounded excerpt centred on the first matching term (verbatim text)."""
    if len(text) <= width:
        return text
    low = text.lower()
    idx = -1
    for t in terms:
        i = low.find(t)
        if i != -1 and (idx == -1 or i < idx):
            idx = i
    if idx == -1:
        return text[:width].rstrip() + "…"
    start = max(0, idx - width // 3)
    end = min(len(text), start + width)
    return ("…" if start > 0 else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def support_ratio(claim: str, evidence_texts: Iterable[str]) -> float:
    """Share of the claim's content terms that occur in the cited excerpts. A
    crude lexical-overlap check, NOT proof the excerpt entails the claim."""
    ct = set(tokenize(claim))
    if not ct:
        return 0.0
    et: set[str] = set()
    for e in evidence_texts:
        et.update(tokenize(e))
    return len(ct & et) / len(ct)
