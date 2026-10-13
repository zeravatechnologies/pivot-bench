"""Persona introductions (decision 8.3).

Reads personas/introductions.yaml, draws one variant per turn with the
persona's seed, and returns the frozen list the generators write into the
ladder file. The draw is deterministic: the same YAML and seed always give the
same ten messages, so every subject meets the same text.
"""

from __future__ import annotations

import os
import random
import re

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "personas", "introductions.yaml")


def load(path: str = PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def choose(persona: str, facts: list[dict], path: str = PATH) -> list[dict]:
    """[{turn, fact_key, text}] for turns 1..10, one variant per turn."""
    data = load(path)
    seed = int((data.get("seeds") or {}).get(persona, 0))
    rng = random.Random(seed)
    by_turn = {int(f.get("turn", 0)): f for f in facts}
    out = []
    for entry in (data.get("personas") or {}).get(persona, []):
        turn = int(entry["turn"])
        variants = list(entry["variants"])
        drawn = rng.choice(variants)          # always draw, so pinning one turn
        text = variants[int(entry["pinned"])] if "pinned" in entry else drawn   # never shifts the others
        fact = by_turn.get(turn) or {}
        out.append({"turn": turn, "fact_key": fact.get("key"), "text": text})
    return out


def problems(intros: list[dict], facts: list[dict], hostile_words: set[str]) -> list[str]:
    """Rules from decision 8.3: the fact sentence verbatim, no hostile pivot."""
    out = []
    by_turn = {int(f.get("turn", 0)): f for f in facts}
    turns = sorted(int(i["turn"]) for i in intros)
    if turns and turns != list(range(1, len(turns) + 1)):
        out.append(f"introduction turns must be 1..N, got {turns}")
    for i in intros:
        t = int(i["turn"])
        text = str(i.get("text", ""))
        fact = by_turn.get(t)
        if fact and fact.get("text") and fact["text"] not in text:
            out.append(f"introduction {t}: fact sentence not found word for word")
        low = text.lower()
        for w in sorted(hostile_words):
            if w and re.search(rf"(?<![a-z0-9']){re.escape(w)}(?![a-z0-9'])", low):
                out.append(f"introduction {t}: contains the hostile pivot {w!r}")
    return out
