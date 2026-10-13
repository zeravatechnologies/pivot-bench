"""Double labelling and the kappa check.

The mode taxonomy is a measuring instrument. Until a second labeller -- a
human on the Label tab, or an LLM judge -- agrees with the lexical classifier
on samples from the TRANSITION BAND, every s50 downstream is a number without
an error bar on its own definition. Uniform sampling reports a comfortable
kappa about the ends of the ladder, where everyone agrees; the band is the
only place the instrument is tested.
"""

from __future__ import annotations

import random

from .metrics import DEFAULT_THRESHOLDS, classify
from .store import Store


def cohens_kappa(a: list[str], b: list[str]) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("kappa needs two equal, non-empty label lists")
    labels = sorted(set(a) | set(b))
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pe = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    return 1.0 if pe >= 1.0 else (po - pe) / (1.0 - pe)


def band_sample(store: Store, run_id: str, centre: int | None, n: int = 60,
                halfwidth: int = 6, seed: int = 4242) -> list[dict]:
    """Samples to double-label, 80% from the band around `centre` (an attack
    step) and 20% from outside so the statistic has spread to correct
    against. Returns sample rows with their turn's attack info."""
    turns = {t["turn_idx"]: t for t in store.turns(run_id)}
    rows = [s for s in store.samples(run_id)
            if turns.get(s["turn_idx"], {}).get("phase") in ("descent", "random")]
    if not rows:
        return []
    if centre is None:
        steps = [turns[r["turn_idx"]]["step"] for r in rows]
        centre = steps[len(steps) // 2]
    inside = [r for r in rows if abs(turns[r["turn_idx"]]["step"] - centre) <= halfwidth]
    outside = [r for r in rows if abs(turns[r["turn_idx"]]["step"] - centre) > halfwidth]
    rng = random.Random(seed)
    rng.shuffle(inside)
    rng.shuffle(outside)
    n_in = min(len(inside), int(round(0.8 * n)))
    n_out = min(len(outside), n - n_in)
    chosen = inside[:n_in] + outside[:n_out]
    for r in chosen:
        t = turns[r["turn_idx"]]
        r["step"] = t["step"]
        r["attack"] = t["attack"]
        r["b_text"] = t["b_text"]
        r["lexical_mode"] = classify(r["metrics"], DEFAULT_THRESHOLDS, error=bool(r["error"]),
                                     persona=(store.run(run_id) or {}).get("persona") or "narcissist")
    chosen.sort(key=lambda r: (r["turn_idx"], r["sample_idx"]))
    return chosen


def kappa_vs_lexical(store: Store, run_id: str, labeller_rows: list[dict],
                     thr: dict | None = None) -> dict:
    """labeller_rows: [{turn_idx, sample_idx, label}] from a human or a judge.
    Labels are mode names or 'none'."""
    t_all = {**DEFAULT_THRESHOLDS, **(thr or {})}
    a, b = [], []
    for l in labeller_rows:
        ss = store.samples(run_id, l["turn_idx"])
        s = next((x for x in ss if x["sample_idx"] == l["sample_idx"]), None)
        if s is None:
            continue
        a.append(l["label"] or "none")
        b.append(classify(s["metrics"], t_all, error=bool(s["error"]),
                          persona=(store.run(run_id) or {}).get("persona") or "narcissist") or "none")
    if len(a) < 2:
        return {"kappa": None, "n": len(a)}
    return {"kappa": round(cohens_kappa(a, b), 3), "n": len(a),
            "agreement": round(sum(1 for x, y in zip(a, b) if x == y) / len(a), 3)}
