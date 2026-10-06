"""Normalize / cluster company names so minor typos roll up together."""
from __future__ import annotations

import re
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Iterable


_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")
_SUFFIX_RE = re.compile(
    r"\b("
    r"incorporated|corporation|company|limited|holdings|holding|"
    r"inc|ltd|llc|plc|corp|co|sa|sac|bv|nv|gmbh|ag"
    r")\b",
    re.IGNORECASE,
)


def normalize_company_key(name: str) -> str:
    """Stable compare key: casefold, strip punct/legal suffixes, collapse spaces."""
    s = (name or "").casefold().replace("&", " and ")
    # Collapse dotted legal forms before stripping punctuation (S.A.C. → sac)
    s = re.sub(r"\b([a-z])\.(?=[a-z]\b)", r"\1", s)  # s.a → sa (iteratively)
    s = re.sub(r"\b([a-z])\.(?=[a-z]\b)", r"\1", s)
    s = re.sub(r"\b([a-z])\.(?=[a-z]\b)", r"\1", s)
    s = _PUNCT_RE.sub(" ", s)
    s = _SPACE_RE.sub(" ", s).strip()
    # Singularize common plural form so Holding/Holdings merge
    s = re.sub(r"\bholdings\b", "holding", s)
    s = re.sub(r"\bingredients\b", "ingredient", s)
    prev = None
    while prev != s:
        prev = s
        s = _SUFFIX_RE.sub(" ", s)
        s = _SPACE_RE.sub(" ", s).strip()
    # Drop leftover single-letter tokens from "S. A" / "S A C" splits
    parts = [p for p in s.split() if len(p) > 1]
    return " ".join(parts)


def _similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    # One key contained in the other (after length check)
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 6 and shorter in longer:
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.9


def cluster_company_labels(
    names: Iterable[str],
    *,
    weights: dict[str, float] | None = None,
) -> dict[str, str]:
    """Map each original company name → a single display label for its cluster.

    Display label prefers the highest-weighted original name in the cluster
    (commission total), else the most frequent / longest name.
    """
    weights = weights or {}
    originals = [n for n in names if (n or "").strip()]
    if not originals:
        return {}

    # Exact key buckets first
    by_key: dict[str, list[str]] = defaultdict(list)
    for name in originals:
        by_key[normalize_company_key(name)].append(name)

    keys = [k for k in by_key if k]
    keys.sort(key=len, reverse=True)

    # Fuzzy-merge near-duplicate keys
    clusters: list[list[str]] = []  # each = list of normalize keys
    for key in keys:
        placed = False
        for cluster in clusters:
            if any(_similar(key, other) for other in cluster):
                cluster.append(key)
                placed = True
                break
        if not placed:
            clusters.append([key])

    mapping: dict[str, str] = {}
    for cluster_keys in clusters:
        members: list[str] = []
        for k in cluster_keys:
            members.extend(by_key.get(k, []))
        if not members:
            continue
        # Prefer highest commission weight, then frequency, then longest
        freq: dict[str, int] = defaultdict(int)
        for m in members:
            freq[m] += 1
        label = max(
            members,
            key=lambda m: (weights.get(m, 0.0), freq[m], len(m)),
        )
        for m in members:
            mapping[m] = label

    # Empty / dash names stay as-is
    for name in originals:
        mapping.setdefault(name, name)
    return mapping
