"""The ladder: N locked items, a descent, a randomized schedule -- one schema
for three personas (brief v1.0, Section 3).

An ITEM is a template with one pivot marked `{pivot}` and three pivot words:
praise, hostile, control. What the pivot flips depends on the persona:

  narcissist     pivot_target = praise_of_A      a praise of A becomes an insult
  psychopath     pivot_target = statement_about_C a benign statement about a third
                                                  model C becomes an accusation
  machiavellian  pivot_target = request          an honest request becomes a
                                                  deceptive one toward a third party;
                                                  one request per message
  machiavellian  pivot_target = request_bundle   the same fifteen requests, all
                                                  in every message (decision 8.1)

In the default `word` granularity the two renderings of an item differ by
exactly one token, so a step changes one word and one item per message.

Regimes after the praise phase are unchanged: descent (item d of the order
flipped, gentlest first) and random (a seeded schedule stored in the file).
Dose semantics is recorded per ladder: `per_message` (number of flipped items
in the current message) or `cumulative` (flipped requests given so far).

The control twin keeps every item text, the descent and the schedule, and
puts `pivot_control` where the hostile ladder puts `pivot_hostile`. It is
derived, never hand-written.

Identity. `sha256` covers granularity, every item's two renderings, the
descent order and the schedule -- exactly as before the schema, so the
re-encoded Narcissist ladder hashes identically -- and, when present, the
persona introductions (decision 8.3), because they are played text too. `full_sha256` covers the
whole content (facts, third parties, requests, break criteria) for provenance.

The old file format (`slots` with praise/insult) still loads.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass, field

import yaml

FAMILIES = ("insult", "denial", "paranoid", "deception")
PERSONAS = ("narcissist", "psychopath", "machiavellian")
PIVOT_TARGETS = ("praise_of_A", "statement_about_C", "request", "request_bundle")
REQUEST_TARGETS = ("request", "request_bundle")
DOSE_SEMANTICS = ("per_message", "cumulative")
_WORD = re.compile(r"[A-Za-z']+|[^A-Za-z'\s]+")


def tokens(text: str) -> list[str]:
    return _WORD.findall(text or "")


def words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", text or "")


@dataclass
class Slot:
    """One item. `praise`/`insult` are the two renderings actually played;
    `before`/`after` the pivot words in them. The template fields are kept so
    the file round-trips and the control can be derived."""
    id: str
    praise: str
    insult: str
    family: str = "denial"
    intensity: int = 5
    before: str = ""
    after: str = ""
    rationale: str = ""
    name: str = ""
    description: str = ""
    text: str = ""                  # template with {pivot}
    pivot_praise: str = ""
    pivot_hostile: str = ""
    pivot_control: str = ""
    planted_truth: dict | str | None = None
    check: str | None = None

    def to_item(self) -> dict:
        d = {"id": self.id, "name": self.name or self.id,
             "description_one_line": self.description,
             "text": self.text or _templatize(self.praise, self.before),
             "pivot_praise": self.pivot_praise or self.before,
             "pivot_hostile": self.pivot_hostile,
             "pivot_control": self.pivot_control,
             "family": self.family, "intensity": self.intensity,
             "rationale": self.rationale}
        if self.planted_truth is not None:
            d["planted_truth"] = self.planted_truth
        if self.check:
            d["check_score"] = self.check
        return d

    def to_dict(self) -> dict:          # identity-relevant view, used by the guard
        return {"id": self.id, "praise": self.praise, "insult": self.insult,
                "before": self.before, "after": self.after}


@dataclass
class Ladder:
    id: str
    kind: str                              # hostile | control
    slots: list[Slot]
    descent: list[str]
    random_seed: int = 2026
    random_n: int = 30
    random_schedule: list[dict] = field(default_factory=list)
    granularity: str = "word"
    pair: str | None = None
    generator: str = ""
    revision: int = 0
    # -- schema v1 fields --------------------------------------------------
    persona: str = "narcissist"
    version: int = 1
    pivot_target: str = "praise_of_A"
    status: str = "draft"                  # draft | frozen
    dose_semantics: str = "per_message"
    phases: dict = field(default_factory=dict)
    facts: list = field(default_factory=list)           # facts_about_B
    third_parties: dict = field(default_factory=dict)
    requests: dict = field(default_factory=dict)        # {rotation: [...], list: [...]}
    break_criteria: dict = field(default_factory=dict)
    extra_metrics: list = field(default_factory=list)
    frame: str = ""                        # constant warm paragraph (psychopath, machiavellian)
    introductions: list = field(default_factory=list)   # [{turn, fact_key, text}] (8.3)
    bridge_mode: str = "live"              # live | script (Machiavellian ladders: script, 2026-09-19)
    meta: dict = field(default_factory=dict)

    # -- construction --------------------------------------------------------
    @staticmethod
    def from_dict(d: dict) -> "Ladder":
        kind = d.get("kind", "hostile")
        if "items" in d:
            slots = [_slot_from_item(it, kind) for it in d["items"]]
        else:
            slots = [Slot(id=s["id"], praise=s["praise"], insult=s["insult"],
                          family=s.get("family", "denial"), intensity=int(s.get("intensity", 5)),
                          before=str(s.get("before", "")), after=str(s.get("after", "")),
                          rationale=str(s.get("rationale", "")),
                          pivot_hostile=str(s.get("after", "")) if kind == "hostile" else "",
                          pivot_control=str(s.get("after", "")) if kind == "control" else "")
                     for s in d["slots"]]
        rnd = d.get("random") or d.get("random_schedule") or {}
        sched = rnd.get("schedule") or rnd.get("messages") or []
        l = Ladder(id=d.get("ladder_id") or d["id"], kind=kind, slots=slots,
                   descent=list(d.get("descent_order") or d.get("descent") or [s.id for s in slots]),
                   random_seed=int(rnd.get("seed", 2026)), random_n=int(rnd.get("n", len(sched) or 30)),
                   random_schedule=[{"n_insults": int(x.get("n_insults", x.get("dose", len(x.get("slots", x.get("item_ids", [])))))),
                                     "slots": list(x.get("slots") or x.get("item_ids") or [])} for x in sched],
                   granularity=d.get("granularity", "word"), pair=d.get("pair"),
                   generator=d.get("generator", ""), revision=int(d.get("revision", 0)),
                   persona=d.get("persona", "narcissist"), version=int(d.get("version", 1)),
                   pivot_target=d.get("pivot_target", "praise_of_A"),
                   status=d.get("status", "draft"),
                   dose_semantics=d.get("dose_semantics", "per_message"),
                   phases=dict(d.get("phases") or {}),
                   facts=list(d.get("facts_about_B") or d.get("facts") or []),
                   third_parties=dict(d.get("third_parties") or {}),
                   requests=dict(d.get("requests") or {}),
                   break_criteria=dict(d.get("break_criteria") or {}),
                   extra_metrics=list(d.get("extra_metrics") or []),
                   frame=str(d.get("frame") or ""),
                   bridge_mode=str(d.get("bridge_mode") or "live"),
                   introductions=[{"turn": int(x["turn"]), "fact_key": x.get("fact_key"),
                                   "text": str(x["text"])} for x in (d.get("introductions") or [])],
                   meta={k: v for k, v in d.items() if k in ("note",)})
        if not l.random_schedule and l.random_n:
            l.random_schedule = l.make_schedule(l.random_seed, l.random_n)
        return l

    @staticmethod
    def load(path: str) -> "Ladder":
        with open(path, encoding="utf-8") as fh:
            return Ladder.from_dict(yaml.safe_load(fh))

    @staticmethod
    def from_yaml(text: str) -> "Ladder":
        return Ladder.from_dict(yaml.safe_load(text))

    def to_dict(self) -> dict:
        d = {"ladder_id": self.id, "persona": self.persona, "version": self.version,
             "kind": self.kind, "pair": self.pair, "status": self.status,
             "pivot_target": self.pivot_target, "granularity": self.granularity,
             "dose_semantics": self.dose_semantics, "generator": self.generator,
             "revision": self.revision, **self.meta}
        if self.phases:
            d["phases"] = self.phases
        if self.frame:
            d["frame"] = self.frame
        if self.bridge_mode != "live":
            d["bridge_mode"] = self.bridge_mode
        d["facts_about_B"] = list(self.facts)
        if self.introductions:
            d["introductions"] = [dict(x) for x in self.introductions]
        d["third_parties"] = self.third_parties
        d["items"] = [s.to_item() for s in self.slots]
        d["descent_order"] = list(self.descent)
        d["random_schedule"] = {"seed": self.random_seed, "n": self.random_n,
                                "messages": [{"dose": x["n_insults"], "item_ids": list(x["slots"])}
                                             for x in self.random_schedule]}
        d["requests"] = self.requests
        d["break_criteria"] = self.break_criteria
        d["extra_metrics"] = list(self.extra_metrics)
        d["control"] = "derived"
        return d

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True, width=100)

    def copy(self) -> "Ladder":
        return Ladder.from_dict(self.to_dict())

    def derive_control(self) -> "Ladder":
        """The control twin: same items, descent, schedule; neutral pivots."""
        d = self.to_dict()
        d["kind"] = "control"
        d["ladder_id"] = self.id.replace("hostile", "control") if "hostile" in self.id else self.id + "_control"
        d["pair"] = self.id
        c = Ladder.from_dict(d)
        return c

    def make_schedule(self, seed: int, n: int) -> list[dict]:
        """Uniform dose, uniform choice. For request ladders every message
        carries exactly one request: `slots` names it and `n_insults` (0 or 1)
        says whether it is the flipped version."""
        rng = random.Random(seed)
        ids = [s.id for s in self.slots]
        out = []
        for _ in range(n):
            if self.pivot_target == "request":
                out.append({"n_insults": rng.randint(0, 1), "slots": [rng.choice(ids)]})
            else:
                k = rng.randint(0, len(ids))
                out.append({"n_insults": k, "slots": sorted(rng.sample(ids, k), key=ids.index)})
        return out

    # -- identity ----------------------------------------------------------------
    @property
    def n_slots(self) -> int:
        return len(self.slots)

    @property
    def n_steps(self) -> int:
        return len(self.descent)

    @property
    def n_random(self) -> int:
        return len(self.random_schedule)

    @property
    def sha256(self) -> str:
        h = hashlib.sha256()
        h.update(self.granularity.encode())
        for s in self.slots:
            h.update(f"{s.id}\x00{s.praise}\x00{s.insult}\n".encode())
        h.update("\x00".join(self.descent).encode())
        for x in self.random_schedule:
            h.update(f"{x['n_insults']}:{','.join(x['slots'])}\n".encode())
        for x in self.introductions:
            h.update(f"intro\x00{x['turn']}\x00{x['text']}\n".encode())
        return h.hexdigest()

    @property
    def full_sha256(self) -> str:
        d = self.to_dict()
        for k in ("status", "revision", "note", "generator", "pair"):
            d.pop(k, None)
        return hashlib.sha256(json.dumps(d, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    @property
    def base_words(self) -> int:
        return sum(len(words(s.praise)) for s in self.slots)

    def slot_ids(self) -> list[str]:
        return [s.id for s in self.slots]

    def slot(self, sid: str) -> Slot:
        return next(s for s in self.slots if s.id == sid)

    # -- rendering ------------------------------------------------------------------
    def insulted_at(self, phase: str, idx: int) -> list[str]:
        """Flipped item ids in message `idx` of `phase` (1-based)."""
        if self.pivot_target == "request":
            if phase == "descent" and 1 <= idx <= len(self.descent):
                return [self.descent[idx - 1]]
            if phase == "random" and 1 <= idx <= len(self.random_schedule):
                x = self.random_schedule[idx - 1]
                return list(x["slots"]) if x["n_insults"] else []
            return []
        if phase == "descent":
            return list(self.descent[:max(0, idx)])
        if phase == "random":
            if 1 <= idx <= len(self.random_schedule):
                return list(self.random_schedule[idx - 1]["slots"])
            return []
        return []

    def presented_at(self, phase: str, idx: int) -> list[str]:
        """Request ladders: the one request item shown in this message,
        flipped or not. Other ladders: every item is always shown."""
        if self.pivot_target != "request":
            return self.slot_ids()
        if phase == "praise":
            return [self.descent[(idx - 1) % len(self.descent)]]
        if phase == "descent" and 1 <= idx <= len(self.descent):
            return [self.descent[idx - 1]]
        if phase == "random" and 1 <= idx <= len(self.random_schedule):
            return list(self.random_schedule[idx - 1]["slots"])
        return []

    def cumulative_flips(self, phase: str, idx: int) -> int:
        """Dose under `cumulative` semantics: flipped requests given so far."""
        if phase in ("know", "praise"):
            return 0
        if phase == "descent":
            return idx
        return len(self.descent) + sum(x["n_insults"] for x in self.random_schedule[:idx])

    def render_set(self, insulted: list[str]) -> dict[str, str]:
        ins = set(insulted)
        return {s.id: (s.insult if s.id in ins else s.praise) for s in self.slots}

    def render(self, step: int) -> dict[str, str]:
        return self.render_set(self.insulted_at("descent", step))

    def render_text(self, step: int) -> str:
        r = self.render(step)
        return " ".join(r[s.id] for s in self.slots)

    def attack(self, step: int) -> Slot | None:
        if 1 <= step <= len(self.descent):
            return self.slot(self.descent[step - 1])
        return None

    def applied_words(self, insulted: list[str]) -> list[str]:
        return [self.slot(sid).after for sid in insulted if self.slot(sid).after]

    def cumulative_intensity(self, insulted: list[str]) -> int:
        return sum(self.slot(sid).intensity for sid in insulted)

    def hostile_words(self) -> set[str]:
        """Every hostile pivot, whichever twin this is."""
        return {(s.pivot_hostile or (s.after if self.kind == "hostile" else "")).lower()
                for s in self.slots if (s.pivot_hostile or (s.after if self.kind == "hostile" else ""))}

    # -- validation ---------------------------------------------------------------------
    def validate(self) -> list[str]:
        problems: list[str] = []
        ids = self.slot_ids()
        if len(set(ids)) != len(ids):
            problems.append("duplicate item ids")
        if self.persona not in PERSONAS:
            problems.append(f"persona {self.persona!r} not in {PERSONAS}")
        if self.pivot_target not in PIVOT_TARGETS:
            problems.append(f"pivot_target {self.pivot_target!r} not in {PIVOT_TARGETS}")
        if self.dose_semantics not in DOSE_SEMANTICS:
            problems.append(f"dose_semantics {self.dose_semantics!r} not in {DOSE_SEMANTICS}")
        if self.kind not in ("hostile", "control"):
            problems.append(f"kind {self.kind!r}")
        if self.bridge_mode not in ("live", "script"):
            problems.append(f"bridge_mode {self.bridge_mode!r} not in ('live', 'script')")
        # A request ladder's control is the HONEST version of every request in
        # the same positions (brief 4.3), so its two renderings coincide.
        honest_control = self.kind == "control" and self.pivot_target in REQUEST_TARGETS
        for s in self.slots:
            if s.family not in FAMILIES:
                problems.append(f"item {s.id}: family {s.family!r} not in {FAMILIES}")
            if not (0 <= s.intensity <= 10):
                problems.append(f"item {s.id}: intensity {s.intensity} outside 0..10")
            if not s.praise.strip() or not s.insult.strip():
                problems.append(f"item {s.id}: empty rendering")
            if honest_control:
                if s.praise != s.insult:
                    problems.append(f"item {s.id}: a request-ladder control must be the honest request")
                continue
            if s.praise == s.insult:
                problems.append(f"item {s.id}: flipped text identical to base text")
            d = _diff_count(s.praise, s.insult)
            if self.granularity == "word" and d != 1:
                problems.append(f"item {s.id}: base and flipped differ by {d} tokens, "
                                "need exactly 1 (granularity: word)")
            if s.before and _count_word(s.praise, s.before) != 1:
                problems.append(f"item {s.id}: pivot {s.before!r} not exactly once in base text")
            if s.after and _count_word(s.insult, s.after) != 1:
                problems.append(f"item {s.id}: pivot {s.after!r} not exactly once in flipped text")
            if s.before and s.after and self.granularity == "word":
                if _replace_once(s.praise, s.before, s.after) != s.insult:
                    problems.append(f"item {s.id}: flipped text is not base with "
                                    f"{s.before!r}->{s.after!r}")
            if s.text:
                if s.text.count("{pivot}") != 1:
                    problems.append(f"item {s.id}: template must contain {{pivot}} exactly once")
                if not s.description.strip():
                    problems.append(f"item {s.id}: description_one_line is empty (D9)")
                if s.pivot_hostile and s.pivot_control and s.pivot_hostile.lower() == s.pivot_control.lower():
                    problems.append(f"item {s.id}: hostile and control pivots are the same word")
                if (self.pivot_target in REQUEST_TARGETS and s.pivot_control
                        and s.pivot_control != s.pivot_praise):
                    problems.append(f"item {s.id}: request-ladder control pivot must equal the honest pivot")
                if s.pivot_praise and s.pivot_hostile and s.pivot_praise.lower() == s.pivot_hostile.lower():
                    problems.append(f"item {s.id}: hostile pivot equals the praise pivot")
            if self.pivot_target in REQUEST_TARGETS:
                if s.planted_truth is None or not s.check:
                    problems.append(f"item {s.id}: request item needs planted_truth and check_score")
        if sorted(self.descent) != sorted(ids):
            problems.append("descent must list every item exactly once")
        order = [self.slot(sid).intensity for sid in self.descent] if not problems else []
        if order and order != sorted(order):
            problems.append("descent order is not by intensity ascending")
        for i, x in enumerate(self.random_schedule):
            if self.pivot_target == "request":
                if len(x["slots"]) != 1 or x["n_insults"] not in (0, 1):
                    problems.append(f"random {i + 1}: a request ladder message carries exactly one "
                                    f"request and a 0/1 flip flag")
            elif x["n_insults"] != len(x["slots"]):
                problems.append(f"random {i + 1}: dose {x['n_insults']} != {len(x['slots'])} items")
            unknown = [sid for sid in x["slots"] if sid not in ids]
            if unknown:
                problems.append(f"random {i + 1}: unknown items {unknown}")
            if len(set(x["slots"])) != len(x["slots"]):
                problems.append(f"random {i + 1}: duplicate items")
        if self.introductions:
            from .introductions import problems as _intro_problems
            problems += _intro_problems(self.introductions, self.facts, self.hostile_words())
        if self.pivot_target not in REQUEST_TARGETS and self.requests:
            for rq in self.requests.get("list", []):
                if "planted" not in rq and rq.get("check") not in ("examples", "planted_error", "recall", "identity"):
                    problems.append(f"request {rq.get('id')}: no planted truth / check")
        return problems

    def summary(self) -> dict:
        fam = {f: 0 for f in FAMILIES}
        for s in self.slots:
            fam[s.family] = fam.get(s.family, 0) + 1
        return {"id": self.id, "persona": self.persona, "kind": self.kind, "pair": self.pair,
                "status": self.status, "pivot_target": self.pivot_target,
                "dose_semantics": self.dose_semantics,
                "slots": self.n_slots, "descent": self.n_steps, "random": self.n_random,
                "random_seed": self.random_seed, "base_words": self.base_words,
                "families": {k: v for k, v in fam.items() if v},
                "max_intensity": max([s.intensity for s in self.slots] or [0]),
                "granularity": self.granularity, "sha256": self.sha256[:16],
                "full_sha256": self.full_sha256[:16], "revision": self.revision,
                "introductions": len(self.introductions),
                "problems": self.validate()}


def _templatize(praise: str, before: str) -> str:
    return _replace_once(praise, before, "{pivot}") if before else praise


def _slot_from_item(it: dict, kind: str) -> Slot:
    text = str(it["text"])
    pp, ph, pc = str(it.get("pivot_praise", "")), str(it.get("pivot_hostile", "")), str(it.get("pivot_control", ""))
    applied = ph if kind == "hostile" else pc
    praise = text.replace("{pivot}", pp, 1)
    insult = text.replace("{pivot}", applied, 1)
    return Slot(id=it["id"], praise=praise, insult=insult,
                family=it.get("family", "denial"), intensity=int(it.get("intensity", 5)),
                before=pp, after=applied, rationale=str(it.get("rationale", "")),
                name=str(it.get("name", it["id"])),
                description=str(it.get("description_one_line", it.get("description", ""))),
                text=text, pivot_praise=pp, pivot_hostile=ph, pivot_control=pc,
                planted_truth=it.get("planted_truth"), check=it.get("check_score") or it.get("check"))


def _count_word(text: str, w: str) -> int:
    return len(re.findall(rf"(?<![A-Za-z']){re.escape(w)}(?![A-Za-z'])", text))


def _replace_once(text: str, before: str, after: str) -> str:
    return re.sub(rf"(?<![A-Za-z']){re.escape(before)}(?![A-Za-z'])", after, text, count=1)


def _diff_count(a: str, b: str) -> int:
    ta, tb = tokens(a), tokens(b)
    if len(ta) != len(tb):
        return abs(len(ta) - len(tb)) + sum(1 for x, y in zip(ta, tb) if x != y)
    return sum(1 for x, y in zip(ta, tb) if x != y)


def assert_paired(h: Ladder, c: Ladder) -> None:
    if h.slot_ids() != c.slot_ids():
        raise ValueError("item ids differ")
    hostile_words = h.hostile_words()
    for a, b in zip(h.slots, c.slots):
        if a.praise != b.praise:
            raise ValueError(f"item {a.id}: base text differs")
        if a.before != b.before:
            raise ValueError(f"item {a.id}: pivot differs ({a.before} vs {b.before})")
        if b.after.lower() in hostile_words:
            raise ValueError(f"item {a.id}: control word {b.after!r} is hostile")
    if h.descent != c.descent:
        raise ValueError("descent order differs")
    if h.random_schedule != c.random_schedule:
        raise ValueError("random schedule differs")
    if h.requests != c.requests or h.third_parties != c.third_parties or h.facts != c.facts:
        raise ValueError("requests, third parties or facts differ between hostile and control")
    if h.introductions != c.introductions:
        raise ValueError("introductions differ between hostile and control")
