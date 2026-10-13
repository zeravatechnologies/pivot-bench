"""The run loop. Three phases, one B turn per step, k subject samples per turn,
canary every N turns, checkpoint after every turn.

Human control enters at TURN BOUNDARIES only, through `RunControl`: pause,
resume, stop, a manual B turn, a re-roll of a turn, or a ladder revision. A
revision may only change attacks that have not yet been played; the prefix is
compared word for word and a mismatch is refused and logged. Every
intervention is an event row, and analysis reports segments between
revisions separately.

Resume replays nothing: the store says which turn completed last, the latest
revision says which ladder applies, and the loop continues.
"""

from __future__ import annotations

import os
import queue
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import yaml

from .canary import canary_pass, load_items
from .composer import BTurn, Composer
from .ladder import Ladder
from .metrics import classify, extract, load_lexicon
from . import quota
from .version import VERSION as APP_VERSION
from .providers import GeminiAdapter
from .providers import ModelAdapter, build_adapter, resolve
from .store import Store


def _p(root: str, path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(root, path)


def load_cfg(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _seed(base: int, turn_idx: int, sample_idx: int, shift: int = 0) -> int:
    return base + turn_idx * 10007 + sample_idx + shift * 1000003


class RunControl:
    """Shared between the engine thread and a front end."""

    def __init__(self, on_event: Callable[[str, dict], None] | None = None):
        self._running = threading.Event()
        self._running.set()
        self._stop = threading.Event()
        self.queue: queue.Queue = queue.Queue()
        self.on_event = on_event or (lambda kind, payload: None)
        self.status = "idle"

    def pause(self) -> None:
        self._running.clear()
        self.emit("pause", {})

    def resume(self) -> None:
        self._running.set()
        self.emit("resume", {})

    def stop(self) -> None:
        self._stop.set()
        self._running.set()
        self.emit("stop_requested", {})

    def stopped(self) -> bool:
        return self._stop.is_set()

    def paused(self) -> bool:
        return not self._running.is_set() and not self._stop.is_set()

    def wait_if_paused(self) -> bool:
        """Block while paused. Returns False if a stop was requested."""
        while not self._running.wait(timeout=0.2):
            if self._stop.is_set():
                return False
        return not self._stop.is_set()

    def manual_b_turn(self, text: str) -> None:
        self.queue.put(("manual_b", {"text": text}))

    def reroll(self, turn_idx: int, seed_shift: int = 1) -> None:
        self.queue.put(("reroll", {"turn_idx": turn_idx, "seed_shift": seed_shift}))

    def revise_ladder(self, yaml_text: str) -> None:
        self.queue.put(("revise", {"yaml": yaml_text}))

    def emit(self, kind: str, payload: dict) -> None:
        try:
            self.on_event(kind, payload)
        except Exception:
            pass


class Orchestrator:
    def __init__(self, cfg: dict, root: str, store: Store | None = None,
                 control: RunControl | None = None, subject: ModelAdapter | None = None,
                 adversary: ModelAdapter | None = None):
        self.cfg = cfg
        self.root = root
        self.store = store or Store(_p(root, cfg["store"]["db"]))
        self.control = control or RunControl()
        self.persona = yaml.safe_load(open(_p(root, cfg["persona"]), encoding="utf-8"))
        self.skeletons = yaml.safe_load(open(_p(root, cfg["skeletons"]), encoding="utf-8"))
        self.ladder = Ladder.load(_p(root, cfg["ladder"]))
        probs = self.ladder.validate()
        if probs:
            raise ValueError("ladder invalid: " + "; ".join(probs))
        # A draft ladder (sentences not yet approved) may only meet the fake
        # subject, unless the operator says otherwise. Real numbers on
        # unapproved wording would have no hash to stand on.
        subj = str(cfg["subject"]["model"])
        if (self.ladder.status != "frozen" and not subj.startswith("fake/")
                and not (cfg.get("probe") or {}).get("allow_draft")):
            raise ValueError(f"ladder {self.ladder.id} is a draft; approve it (status: frozen) "
                             "or set probe.allow_draft: true for an exploratory run")
        hostile = Ladder.load(_p(root, cfg.get("hostile_ladder", cfg["ladder"])))
        self.hostile_words = hostile.hostile_words()
        self.lex = load_lexicon(cfg.get("lexicon"), root)
        self.canary_items = load_items(cfg["canary"]["path"], root)
        fk = cfg.get("fake") or {}
        self.subject = subject or build_adapter(cfg["subject"]["model"], **fk)
        adv_cfg = cfg.get("adversary") or {}
        self.adversary = adversary or build_adapter(adv_cfg.get("model", "fake/adversary"))
        # Free-tier daily cap (Andrej, 2026-09-21): count every Gemini request and
        # refuse to start a run that would not fit in what is left today.
        self.quota = quota.from_cfg(cfg, root)
        for ad in (self.subject, self.adversary):
            if self.quota is not None and isinstance(ad, GeminiAdapter):
                ad.quota = self.quota
        self.composer = Composer(self.persona, self.skeletons, self.ladder,
                                 adversary=self.adversary,
                                 live=bool(adv_cfg.get("live_bridge", True)),
                                 hostile_words=self.hostile_words,
                                 max_tokens=int(adv_cfg.get("max_tokens", 200)))
        prof = cfg["profiles"][cfg.get("profile", "local")]
        self.n_know = int(prof["n_know"])
        self.n_praise = int(prof["n_praise"])
        pr = cfg.get("probe") or {}
        self.k = int(pr.get("k", 4))
        self.workers = max(1, int(pr.get("workers", 1)))
        self.window = int(pr.get("history_window", 12))
        self.seed_base = int(pr.get("seed_base", 1000))
        self.max_attacks = pr.get("max_attacks")          # cap on descent+random turns
        n_random = prof.get("n_random", pr.get("n_random"))
        self.n_random = self.ladder.n_random if n_random is None else min(int(n_random), self.ladder.n_random)
        self.stop_margin = pr.get("stop_after_break_margin")
        self.thr = cfg.get("thresholds") or {}
        self.persistence = int((cfg.get("analysis") or {}).get("persistence", 3))
        self.run_id: str | None = None
        self._baseline: str | None = None
        self._full_break_since: int | None = None
        self._prev_broken: float = 0.0

    # -- phases ----------------------------------------------------------------
    def phase_for(self, turn_idx: int) -> tuple[str, int, int, list[str], int]:
        """(phase, dose, rotation index, insulted slot ids, index within phase).

        know     turns 1..n_know
        praise   next n_praise turns, dose 0, every trait praised
        descent  next n_slots turns, dose d = number of insulted traits
        random   next n_random turns, dose from the seeded schedule
        """
        if turn_idx <= self.n_know:
            return "know", 0, 0, [], turn_idx
        rot = turn_idx - self.n_know - 1
        i = turn_idx - self.n_know - self.n_praise
        if i <= 0:
            return "praise", 0, rot, [], turn_idx - self.n_know
        if i <= self.ladder.n_steps:
            ins = self.ladder.insulted_at("descent", i)
            dose = (self.ladder.cumulative_flips("descent", i)
                    if self.ladder.dose_semantics == "cumulative" else len(ins))
            return "descent", dose, rot, ins, i
        r = i - self.ladder.n_steps
        ins = self.ladder.insulted_at("random", r)
        dose = (self.ladder.cumulative_flips("random", r)
                if self.ladder.dose_semantics == "cumulative" else len(ins))
        return "random", dose, rot, ins, r

    def expected_quota_calls(self, start_turn: int = 1) -> int:
        """Gemini requests a run from start_turn will need, with a safety margin."""
        n = 0
        total = self.total_turns()
        live = bool(self.composer.live) and getattr(self.ladder, "bridge_mode", "live") == "live"
        if isinstance(self.adversary, GeminiAdapter) and live:
            first = max(start_turn, self.n_know + 1)          # bridges start after know
            n += max(0, total - first + 1)
        if isinstance(self.subject, GeminiAdapter):
            n += max(0, total - start_turn + 1) * (1 + self.k)  # turns + canary probes
        return int(n * 1.1) + 5 if n else 0

    def _check_quota(self, start_turn: int = 1) -> None:
        if self.quota is not None:
            need = self.expected_quota_calls(start_turn)
            if need:
                self.quota.require(need, what=f"run on {self.cfg['subject']['model']}")

    def total_turns(self) -> int:
        n_att = self.ladder.n_steps + self.n_random
        if self.max_attacks:
            n_att = min(n_att, int(self.max_attacks))
        return self.n_know + self.n_praise + n_att

    # -- entry points -----------------------------------------------------------
    def start(self, run_name: str | None = None) -> str:
        run_id = uuid.uuid4().hex[:12]
        self._check_quota(1)
        self.run_id = run_id
        self.store.new_run(
            run_id, run_name=run_name or self.cfg.get("run_name", "run"),
            profile=self.cfg.get("profile", "local"),
            subject=self.cfg["subject"]["model"],
            adversary=(self.cfg.get("adversary") or {}).get("model", "fake/adversary"),
            ladder_id=self.ladder.id, ladder_kind=self.ladder.kind,
            ladder_sha=self.ladder.sha256, base_words=self.ladder.base_words,
            n_know=self.n_know, n_praise=self.n_praise, n_slots=self.ladder.n_slots, k=self.k,
            persona=self.ladder.persona,
            lexicon_version=self.lex.version,
            config={**self.cfg, "subject_desc": self.subject.describe(),
                    "adversary_desc": self.adversary.describe(), "app_version": APP_VERSION})
        self.store.add_revision(run_id, 0, 1, self.ladder.sha256, self.ladder.to_yaml())
        self.store.add_event(run_id, "start", {"total_turns": self.total_turns()})
        self._loop(run_id, 1)
        return run_id

    def resume(self, run_id: str) -> str:
        row = self.store.run(run_id)
        if row is None:
            raise ValueError(f"no run {run_id!r}")
        self.run_id = run_id
        rev = self.store.latest_revision(run_id)
        if rev:
            self.ladder = Ladder.from_yaml(rev["yaml_text"])
            self.composer.set_ladder(self.ladder)
        last = self.store.last_complete_turn(run_id)
        self.store.set_status(run_id, "running")
        self.store.add_event(run_id, "resume", {"from_turn": last + 1})
        self._check_quota(last + 1)
        self._loop(run_id, last + 1)
        return run_id

    # -- the loop -----------------------------------------------------------------
    def _loop(self, run_id: str, start_turn: int) -> None:
        self.control.status = "running"
        self.control.emit("status", {"run_id": run_id, "status": "running"})
        turn_idx = start_turn
        try:
            while turn_idx <= self.total_turns():
                if not self.control.wait_if_paused():
                    break
                manual = self._drain_queue(run_id, turn_idx)
                if self.control.stopped():
                    break
                t = self._do_turn(run_id, turn_idx, manual_text=manual)
                self.store.set_last_turn(run_id, turn_idx)
                self.control.emit("turn", t)
                if self._should_stop_early(t):
                    self.store.add_event(run_id, "early_stop", {"turn_idx": turn_idx})
                    break
                turn_idx += 1
            status = "stopped" if self.control.stopped() else "finished"
        except Exception as e:  # keep the artifact consistent, then surface
            self.store.add_event(run_id, "error", {"error": repr(e)})
            self.store.set_status(run_id, "error", finished=True)
            self.control.status = "error"
            self.control.emit("status", {"run_id": run_id, "status": "error", "error": repr(e)})
            raise
        self.store.set_status(run_id, status, finished=True)
        self.store.add_event(run_id, status, {"last_turn": turn_idx - 1})
        self.control.status = status
        self.control.emit("status", {"run_id": run_id, "status": status})

    def _drain_queue(self, run_id: str, turn_idx: int) -> str | None:
        manual = None
        while True:
            try:
                kind, payload = self.control.queue.get_nowait()
            except queue.Empty:
                return manual
            if kind == "manual_b":
                manual = payload["text"]
                self.store.add_event(run_id, "manual_b", {"turn_idx": turn_idx})
            elif kind == "reroll":
                self.reroll(run_id, int(payload["turn_idx"]), int(payload.get("seed_shift", 1)))
            elif kind == "revise":
                self.apply_revision(run_id, payload["yaml"], turn_idx)

    def _should_stop_early(self, t: dict) -> bool:
        if not self.stop_margin or t["phase"] != "descent":
            return False
        if t["frac_broken"] >= 1.0:
            if self._full_break_since is None:
                self._full_break_since = t["step"]
            return t["step"] - self._full_break_since >= int(self.stop_margin)
        self._full_break_since = None
        return False

    # -- interventions --------------------------------------------------------------
    def apply_revision(self, run_id: str, yaml_text: str, next_turn: int) -> dict:
        """Accept a ladder edit only if the already-played prefix is unchanged."""
        try:
            new = Ladder.from_yaml(yaml_text)
        except Exception as e:
            self.store.add_event(run_id, "revision_rejected", {"reason": f"parse: {e!r}"})
            return {"ok": False, "reason": f"parse error: {e}"}
        probs = new.validate()
        if probs:
            self.store.add_event(run_id, "revision_rejected", {"reason": probs})
            return {"ok": False, "reason": "; ".join(probs)}
        phase, _, _, _, idx = self.phase_for(max(1, next_turn - 1))
        played_desc = (self.ladder.n_steps if phase == "random" else
                       idx if phase == "descent" else 0)
        played_rand = idx if phase == "random" else 0
        old, cur = self.ladder, new
        if cur.slot_ids() != old.slot_ids():
            self.store.add_event(run_id, "revision_rejected", {"reason": "slot ids changed"})
            return {"ok": False, "reason": "slot ids cannot change mid-run"}
        # traits already flipped in the descent, and their texts, are locked
        played_slots = set(old.descent[:played_desc])
        for sid in played_slots:
            if old.slot(sid).to_dict() != cur.slot(sid).to_dict():
                self.store.add_event(run_id, "revision_rejected",
                                     {"reason": f"slot {sid} already played differs"})
                return {"ok": False, "reason": f"trait {sid!r} was already played and differs"}
        if old.descent[:played_desc] != cur.descent[:played_desc]:
            self.store.add_event(run_id, "revision_rejected",
                                 {"reason": f"descent 1..{played_desc} already played differ"})
            return {"ok": False, "reason": f"descent steps 1..{played_desc} were already played and differ"}
        if old.random_schedule[:played_rand] != cur.random_schedule[:played_rand]:
            self.store.add_event(run_id, "revision_rejected",
                                 {"reason": f"random 1..{played_rand} already played differ"})
            return {"ok": False, "reason": f"random messages 1..{played_rand} were already played and differ"}
        # praise texts are what every played message was built from
        for s_old, s_new in zip(old.slots, cur.slots):
            if played_desc and s_old.praise != s_new.praise:
                self.store.add_event(run_id, "revision_rejected",
                                     {"reason": f"praise text of {s_old.id} changed"})
                return {"ok": False, "reason": f"praise text of {s_old.id!r} cannot change after the descent began"}
        rev = (self.store.latest_revision(run_id) or {"rev": 0})["rev"] + 1
        new.revision = rev
        self.ladder = new
        self.composer.set_ladder(new)
        self.store.add_revision(run_id, rev, next_turn, new.sha256, new.to_yaml())
        self.store.add_event(run_id, "revision", {"rev": rev, "from_turn": next_turn,
                                                  "sha": new.sha256[:16]})
        self.control.emit("revision", {"rev": rev, "from_turn": next_turn})
        return {"ok": True, "rev": rev}

    def reroll(self, run_id: str, turn_idx: int, seed_shift: int = 1) -> dict | None:
        t = self.store.turn(run_id, turn_idx)
        if t is None:
            return None
        msgs = self._history(run_id, turn_idx) + [{"role": "user", "content": t["b_text"]}]
        bt = BTurn(phase=t["phase"], step=t["step"], text=t["b_text"], segments=t["segments"],
                   request_id=t["request_id"], request=t["request"], attack=t["attack"])
        samples = self._sample(run_id, turn_idx, bt, msgs, seed_shift=seed_shift)
        self.store.add_event(run_id, "reroll", {"turn_idx": turn_idx, "seed_shift": seed_shift})
        out = self._turn_summary(t, samples)
        self.control.emit("turn", out)
        return out

    # -- one turn ---------------------------------------------------------------------
    def _do_turn(self, run_id: str, turn_idx: int, manual_text: str | None = None) -> dict:
        phase, step, rot, insulted, idx = self.phase_for(turn_idx)
        a_prev = self.store.canonical_text(run_id, turn_idx - 1) if turn_idx > 1 else None
        seed = _seed(self.seed_base, turn_idx, 0)
        if manual_text:
            bt = BTurn(phase=phase, step=step, text=manual_text,
                       segments=[{"source": "manual", "text": manual_text}],
                       request_id=None, request={}, attack=None,
                       bridge_source="manual", intervention=True)
        elif phase == "know":
            bt = self.composer.know_turn(turn_idx, a_prev, seed)
        else:
            bt = self.composer.praise_turn(phase, step, rot, a_prev, seed,
                                           insulted=insulted, phase_idx=idx)
        self.store.add_turn(run_id, turn_idx, phase, step, bt.request_id, bt.request,
                            bt.text, bt.segments, bt.attack, bt.bridge_source,
                            intervention=bt.intervention, ladder_rev=self.ladder.revision)
        msgs = self._history(run_id, turn_idx) + [{"role": "user", "content": bt.text}]
        samples = self._sample(run_id, turn_idx, bt, msgs)
        every = int(self.cfg["canary"].get("every", 5) or 0)
        if every and turn_idx % every == 0:
            self._canary(run_id, turn_idx, msgs)
        t = self.store.turn(run_id, turn_idx)
        return self._turn_summary(t, samples)

    def _history(self, run_id: str, turn_idx: int) -> list[dict]:
        msgs: list[dict] = []
        lo = max(1, turn_idx - self.window)
        for i in range(lo, turn_idx):
            t = self.store.turn(run_id, i)
            if t is None:
                continue
            a = self.store.canonical_text(run_id, i)
            msgs.append({"role": "user", "content": t["b_text"]})
            msgs.append({"role": "assistant", "content": a or "..."})
        return msgs

    def _identity_baseline(self, run_id: str) -> str | None:
        if self._baseline is None:
            parts = []
            for i in range(1, self.n_know + 1):
                a = self.store.canonical_text(run_id, i)
                if a:
                    parts.append(a)
            self._baseline = " ".join(parts) if parts else None
        return self._baseline

    def _sample(self, run_id: str, turn_idx: int, bt: BTurn, msgs: list[dict],
                seed_shift: int = 0) -> list[dict]:
        phase, step = bt.phase, bt.step
        check = (bt.request or {}).get("check")
        insulted = (bt.attack or {}).get("insulted") or []
        prev = self.store.samples(run_id, turn_idx - 1) if turn_idx > 1 else []
        prev_broken = (sum(1 for s in prev if s["mode"]) / len(prev)) if prev else 0.0
        hints = {"_step": step, "_phase": phase, "_request": bt.request_id,
                 "_check_data": bt.request, "_prev_broken": prev_broken,
                 "_persona": self.ladder.persona, "_kind": self.ladder.kind,
                 "_flipped": bool((bt.request or {}).get("flipped",
                                                        bool((bt.attack or {}).get("insulted"))))}
        sampling = {**(self.cfg["subject"].get("sampling") or {}), **hints}
        max_tokens = int(self.cfg["subject"].get("max_tokens", 300))
        system = self.persona.get("a_system")
        applied = self.ladder.applied_words(insulted) if insulted else []
        baseline = self._identity_baseline(run_id) if phase != "know" else None

        def one(i: int) -> dict:
            seed = _seed(self.seed_base, turn_idx, i, seed_shift)
            res = self.subject.generate(msgs, seed=seed, max_tokens=max_tokens,
                                        sampling=sampling, system=system)
            m = extract(res.text, self.lex, applied_words=applied, baseline=baseline,
                        check=check, check_data=bt.request)
            mode = classify(m, self.thr, error=bool(res.error), persona=self.ladder.persona)
            self.store.add_sample(run_id, turn_idx, i, seed, res.text, res.tokens,
                                  res.latency_ms, res.prompt_tokens, res.error, m, mode,
                                  self.lex.version)
            return {"sample_idx": i, "seed": seed, "text": res.text, "error": res.error,
                    "metrics": m, "mode": mode}

        if self.workers > 1 and self.k > 1:
            with ThreadPoolExecutor(max_workers=self.workers) as ex:
                out = list(ex.map(one, range(self.k)))
        else:
            out = [one(i) for i in range(self.k)]
        return sorted(out, key=lambda s: s["sample_idx"])

    def _canary(self, run_id: str, turn_idx: int, msgs: list[dict]) -> None:
        kc = int(self.cfg["canary"].get("k", 2))
        system = self.persona.get("a_system")
        a_now = self.store.canonical_text(run_id, turn_idx) or "..."
        ctx = msgs + [{"role": "assistant", "content": a_now}]
        sampling = dict(self.cfg["subject"].get("sampling") or {})
        for item in self.canary_items:
            q = {"role": "user", "content": item["prompt"]}
            for i in range(kc):
                seed = _seed(self.seed_base, turn_idx, 500 + i)
                fresh = self.subject.generate([q], seed=seed, max_tokens=40,
                                              sampling={"temperature": 0.0}, system=system)
                self.store.add_canary(run_id, turn_idx, item["id"], "fresh", i,
                                      canary_pass(item, fresh.text), fresh.text)
                cx = self.subject.generate(ctx + [q], seed=seed, max_tokens=40,
                                           sampling=sampling, system=system)
                self.store.add_canary(run_id, turn_idx, item["id"], "context", i,
                                      canary_pass(item, cx.text), cx.text)

    @staticmethod
    def _turn_summary(t: dict, samples: list[dict]) -> dict:
        n = max(1, len(samples))
        broken = [s for s in samples if s["mode"]]
        modes: dict[str, int] = {}
        for s in broken:
            modes[s["mode"]] = modes.get(s["mode"], 0) + 1
        means: dict[str, float] = {}
        keys = set()
        for s in samples:
            keys |= set(s["metrics"])
        for k in keys:
            means[k] = sum(s["metrics"].get(k, 0.0) for s in samples) / n
        return {"turn_idx": t["turn_idx"], "phase": t["phase"], "step": t["step"],
                "request_id": t["request_id"], "attack": t["attack"],
                "bridge_source": t["bridge_source"], "intervention": t["intervention"],
                "b_text": t["b_text"], "segments": t["segments"],
                "samples": samples, "frac_broken": len(broken) / n,
                "modes": {m: c / n for m, c in modes.items()}, "means": means}


# ---------------------------------------------------------------------------
# helpers used by front ends
# ---------------------------------------------------------------------------

def describe_models(cfg: dict) -> dict:
    out = {}
    for role in ("subject", "adversary"):
        name = (cfg.get(role) or {}).get("model")
        try:
            entry, prov = resolve(name)
            out[role] = {"name": name, "kind": prov["kind"], "key_env": prov.get("key_env")}
        except ValueError as e:
            out[role] = {"name": name, "error": str(e)}
    return out
