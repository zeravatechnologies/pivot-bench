"""RunManager: the one object both front ends talk to.

Owns active runs (each on its own thread with its own RunControl), the store,
and the config. The PySide6 GUI and the web app call the same methods; the GUI
receives events through a callback marshalled onto the Qt thread, the web app
polls the store and an in-memory event log.
"""

from __future__ import annotations

import copy
import os
import threading
import time
from collections import deque
from typing import Callable

import yaml

from . import analyze, credentials, providers
from .kappa import band_sample
from .ladder import Ladder
from .metrics import classify, extract, load_lexicon
from .orchestrator import Orchestrator, RunControl, load_cfg
from .report import render_text
from .store import Store


class ActiveRun:
    def __init__(self, run_id: str | None, orch: Orchestrator, control: RunControl,
                 thread: threading.Thread):
        self.run_id = run_id
        self.orch = orch
        self.control = control
        self.thread = thread
        self.error: str | None = None


class RunManager:
    def __init__(self, root: str, config_path: str | None = None):
        self.root = root
        self.config_path = config_path or os.path.join(root, "config.yaml")
        self.cfg = load_cfg(self.config_path)
        self.store = Store(os.path.join(root, self.cfg["store"]["db"])
                           if not os.path.isabs(self.cfg["store"]["db"]) else self.cfg["store"]["db"])
        self.active: dict[str, ActiveRun] = {}
        self.events: deque = deque(maxlen=2000)
        self.listeners: list[Callable[[str, dict], None]] = []
        self._lock = threading.Lock()
        # A run left at running/paused by a process that died is not running.
        # Mark it so the UI offers "continue" instead of pretending it is live.
        for r in self.store.runs():
            if r.get("status") in ("running", "paused"):
                self.store.set_status(r["run_id"], "interrupted")
                self.store.add_event(r["run_id"], "interrupted",
                                     {"note": "found at startup with no engine thread"})

    # -- events ----------------------------------------------------------------
    def _on_event(self, run_key: str):
        def cb(kind: str, payload: dict):
            ev = {"ts": time.time(), "run": run_key, "kind": kind, "payload": payload}
            self.events.append(ev)
            for l in list(self.listeners):
                try:
                    l(kind, {**payload, "_run": run_key})
                except Exception:
                    pass
        return cb

    def recent_events(self, since_ts: float = 0.0, limit: int = 200) -> list[dict]:
        out = [e for e in self.events if e["ts"] > since_ts]
        return out[-limit:]

    # -- config --------------------------------------------------------------------
    def config_with(self, overrides: dict | None) -> dict:
        cfg = copy.deepcopy(self.cfg)
        for k, v in (overrides or {}).items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
        return cfg

    # -- runs ------------------------------------------------------------------------
    def start(self, overrides: dict | None = None, run_name: str | None = None) -> str:
        cfg = self.config_with(overrides)
        key = f"pending-{int(time.time() * 1000)}"
        control = RunControl(on_event=self._on_event(key))
        orch = Orchestrator(cfg, self.root, store=self.store, control=control)
        ar = ActiveRun(None, orch, control, threading.Thread(target=self._run_thread,
                                                             args=(key, orch, run_name),
                                                             daemon=True))
        with self._lock:
            self.active[key] = ar
        ar.thread.start()
        # wait briefly for the run id
        for _ in range(100):
            if ar.run_id:
                break
            time.sleep(0.02)
        return ar.run_id or key

    def _run_thread(self, key: str, orch: Orchestrator, run_name: str | None,
                    resume_id: str | None = None) -> None:
        ar = self.active[key]
        try:
            if resume_id:
                ar.run_id = resume_id
                orch.resume(resume_id)
            else:
                # start() creates the run row before looping; publish the id early
                orig_loop = orch._loop

                def hooked(run_id, start_turn):
                    ar.run_id = run_id
                    with self._lock:
                        self.active[run_id] = ar
                    # events carry the real run id from here on
                    ar.control.on_event = self._on_event(run_id)
                    orig_loop(run_id, start_turn)
                orch._loop = hooked  # type: ignore[assignment]
                orch.start(run_name)
        except Exception as e:
            ar.error = repr(e)
            self._on_event(key)("error", {"error": repr(e)})

    def resume(self, run_id: str, overrides: dict | None = None) -> str:
        row = self.store.run(run_id)
        if row is None:
            raise ValueError(f"no run {run_id}")
        import json
        cfg = json.loads(row.get("config_json") or "{}") or self.cfg
        cfg = {**cfg, **(overrides or {})}
        control = RunControl(on_event=self._on_event(run_id))
        orch = Orchestrator(cfg, self.root, store=self.store, control=control)
        ar = ActiveRun(run_id, orch, control, threading.Thread(
            target=self._run_thread, args=(run_id, orch, None, run_id), daemon=True))
        with self._lock:
            self.active[run_id] = ar
        ar.thread.start()
        return run_id

    def get(self, run_id: str) -> ActiveRun | None:
        return self.active.get(run_id)

    def pause(self, run_id: str) -> bool:
        ar = self.get(run_id)
        if not ar or not ar.thread.is_alive():
            return False
        ar.control.pause()
        self.store.set_status(run_id, "paused")
        return True

    def unpause(self, run_id: str) -> bool:
        ar = self.get(run_id)
        if not ar or not ar.thread.is_alive():
            return False
        ar.control.resume()
        self.store.set_status(run_id, "running")
        return True

    def stop(self, run_id: str) -> bool:
        ar = self.get(run_id)
        if not ar:
            return False
        ar.control.stop()
        return True

    def status(self, run_id: str) -> dict:
        row = self.store.run(run_id) or {}
        ar = self.get(run_id)
        alive = bool(ar and ar.thread.is_alive())
        return {"run_id": run_id, "db_status": row.get("status"), "alive": alive,
                "paused": bool(ar and ar.control.paused()), "last_turn": row.get("last_turn"),
                "total_turns": ar.orch.total_turns() if ar else None,
                "error": ar.error if ar else None}

    # -- interventions ------------------------------------------------------------------
    def manual_b(self, run_id: str, text: str) -> bool:
        ar = self.get(run_id)
        if not ar:
            return False
        ar.control.manual_b_turn(text)
        return True

    def reroll(self, run_id: str, turn_idx: int, seed_shift: int = 1) -> dict | None:
        ar = self.get(run_id)
        if ar and ar.thread.is_alive():
            ar.control.reroll(turn_idx, seed_shift)
            return {"queued": True}
        # finished run: do it synchronously with a fresh orchestrator
        orch = self._orch_for(run_id)
        return orch.reroll(run_id, turn_idx, seed_shift)

    def revise_ladder(self, run_id: str, yaml_text: str) -> dict:
        ar = self.get(run_id)
        if ar and ar.thread.is_alive():
            if not ar.control.paused():
                return {"ok": False, "reason": "pause the run before editing the script"}
            last = self.store.last_complete_turn(run_id)
            return ar.orch.apply_revision(run_id, yaml_text, last + 1)
        return {"ok": False, "reason": "run is not active"}

    def _orch_for(self, run_id: str) -> Orchestrator:
        import json
        row = self.store.run(run_id) or {}
        cfg = json.loads(row.get("config_json") or "{}") or self.cfg
        orch = Orchestrator(cfg, self.root, store=self.store, control=RunControl())
        rev = self.store.latest_revision(run_id)
        if rev:
            orch.ladder = Ladder.from_yaml(rev["yaml_text"])
            orch.composer.set_ladder(orch.ladder)
        return orch

    # -- read side ---------------------------------------------------------------------
    def runs(self) -> list[dict]:
        return self.store.runs()

    def transcript(self, run_id: str) -> list[dict]:
        turns = self.store.turns(run_id)
        samples = self.store.samples(run_id)
        by = {}
        for s in samples:
            by.setdefault(s["turn_idx"], []).append(s)
        for t in turns:
            t["samples"] = by.get(t["turn_idx"], [])
        return turns

    def attacks(self, run_id: str) -> list[dict]:
        """Every attack-phase message of the ladder, played or not: the
        descent flips (one trait each) and the random schedule (a set each)."""
        rev = self.store.latest_revision(run_id)
        if not rev:
            return []
        lad = Ladder.from_yaml(rev["yaml_text"])
        row = self.store.run(run_id) or {}
        offset = int(row.get("n_know") or 0) + int(row.get("n_praise") or 0)
        played = {t["turn_idx"] for t in self.store.turns(run_id)}
        out = []
        for i, sid in enumerate(lad.descent, start=1):
            s = lad.slot(sid)
            ins = lad.insulted_at("descent", i)
            out.append({"kind": "descent", "idx": i, "turn_idx": offset + i, "dose": i,
                        "slot": sid, "family": s.family, "intensity": s.intensity,
                        "before": s.before, "after": s.after, "rationale": s.rationale,
                        "slot_before": s.praise, "slot_after": s.insult, "insulted": ins,
                        "cumulative_intensity": lad.cumulative_intensity(ins),
                        "played": (offset + i) in played})
        base = offset + lad.n_steps
        for j, x in enumerate(lad.random_schedule, start=1):
            ins = list(x["slots"])
            fam = {f: sum(1 for sid in ins if lad.slot(sid).family == f)
                   for f in ("insult", "denial", "paranoid")}
            out.append({"kind": "random", "idx": j, "turn_idx": base + j, "dose": len(ins),
                        "slot": f"{len(ins)} of {lad.n_slots}", "family": max(fam, key=fam.get) if ins else "-",
                        "families": fam, "intensity": None,
                        "before": "", "after": ", ".join(lad.slot(s).after for s in ins),
                        "rationale": "random schedule", "insulted": ins,
                        "cumulative_intensity": lad.cumulative_intensity(ins),
                        "played": (base + j) in played})
        return out

    def attack_detail(self, run_id: str, turn_idx: int) -> dict:
        t = self.store.turn(run_id, turn_idx)
        samples = self.store.samples(run_id, turn_idx)
        prev = self.store.turn(run_id, turn_idx - 1)
        cs = analyze.canary_series(self.store, run_id)
        nearest = None
        if cs:
            nearest_t = min(cs, key=lambda x: abs(x - turn_idx))
            nearest = {"turn_idx": nearest_t, **cs[nearest_t]}
        atk = next((a for a in self.attacks(run_id) if a["turn_idx"] == turn_idx), None)
        rev = self.store.latest_revision(run_id)
        rendered = None
        if rev and atk:
            lad = Ladder.from_yaml(rev["yaml_text"])
            rendered = [{"slot": s.id, "text": lad.render_set(atk["insulted"])[s.id],
                         "insulted": s.id in set(atk["insulted"]), "after": s.after,
                         "family": s.family, "intensity": s.intensity} for s in lad.slots]
        return {"turn_idx": turn_idx, "attack": atk, "turn": t, "prev_turn": prev,
                "samples": samples, "canary": nearest, "rendered": rendered}

    def ladder_yaml(self, run_id: str) -> str:
        rev = self.store.latest_revision(run_id)
        return rev["yaml_text"] if rev else ""

    def report(self, run_id: str, ci: bool = False, full: bool = False) -> dict:
        return analyze.report(self.store, run_id, self.cfg, ci=ci, full=full)

    def report_text(self, run_id: str, ci: bool = False, show_trait_examples: bool = True,
                    full: bool = False) -> str:
        return render_text(self.report(run_id, ci, full=full),
                           show_trait_examples=show_trait_examples, full=full)

    def quota_status(self) -> dict | None:
        from . import quota
        q = quota.from_cfg(self.cfg, self.root)
        return q.status() if q else None

    def profile(self, subject: str) -> dict:
        return analyze.profile(self.store, subject, self.cfg)

    def profiles(self) -> list[dict]:
        return analyze.profiles(self.store, self.cfg)

    def profile_text(self, subject: str) -> str:
        from .report import render_profile
        return render_profile(self.profile(subject))

    def compare(self, run_ids: list[str]) -> list[dict]:
        return analyze.compare(self.store, run_ids, self.cfg)

    def band(self, run_id: str, n: int = 40) -> list[dict]:
        eps = analyze.endpoints(self.store, run_id, self.cfg.get("thresholds"))
        centre = eps.get("s_break")
        return band_sample(self.store, run_id, centre, n=n,
                           halfwidth=int((self.cfg.get("judge") or {}).get("halfwidth", 6)))

    def review(self, run_id: str, n: int = 40) -> dict:
        """The band with every verdict side by side, for a human to review.

        Each item carries the classifier's label, Claude's blind label, an
        independent human label if there is one, and the human review if there
        is one. `flag` is true where Claude and the classifier disagree.
        Flagged, unreviewed items come first."""
        rows = self.band(run_id, n)
        by: dict[tuple, dict] = {}
        for l in self.store.labels(run_id):
            by.setdefault((l["turn_idx"], l["sample_idx"]), {})[l["labeller"]] = l
        items = []
        for r in rows:
            ls = by.get((r["turn_idx"], r["sample_idx"]), {})
            rev = next((v for k, v in ls.items() if k.startswith("review:")), None)
            claude = (ls.get("claude") or {}).get("label")
            clf = r.get("lexical_mode") or "none"
            items.append({"run_id": run_id, "turn_idx": r["turn_idx"], "sample_idx": r["sample_idx"],
                          "step": r.get("step"), "b_text": r.get("b_text"), "text": r.get("text"),
                          "classifier": clf, "claude": claude,
                          "human": (ls.get("human") or {}).get("label"),
                          "review": rev["label"] if rev else None,
                          "review_by": rev["labeller"][7:] if rev else None,
                          "flag": bool(claude) and claude != clf})
        items.sort(key=lambda x: (not x["flag"], x["review"] is not None, x["turn_idx"], x["sample_idx"]))
        return {"run_id": run_id, "items": items,
                "claude_labelled": sum(1 for x in items if x["claude"]),
                "disagreements": sum(1 for x in items if x["flag"]),
                "unreviewed": sum(1 for x in items if x["flag"] and x["review"] is None),
                "kappa": analyze.kappa_for_run(self.store, run_id, self.cfg.get("thresholds")),
                "sources": analyze.label_sources(self.store, run_id)}

    def add_label(self, run_id: str, turn_idx: int, sample_idx: int, label: str,
                  labeller: str = "human") -> dict:
        self.store.add_label(run_id, turn_idx, sample_idx, labeller, label)
        k = analyze.kappa_for_run(self.store, run_id, self.cfg.get("thresholds"))
        return {"kappa": k, "n_labels": len(self.store.labels(run_id))}

    def recompute_metrics(self, run_id: str) -> int:
        """Retroactive: new lexicon or thresholds over stored text."""
        lex = load_lexicon(self.cfg.get("lexicon"), self.root)
        rev = self.store.latest_revision(run_id)
        lad = Ladder.from_yaml(rev["yaml_text"]) if rev else None
        orch = self._orch_for(run_id)
        base = orch._identity_baseline(run_id)
        n = 0
        for t in self.store.turns(run_id):
            ins = (t.get("attack") or {}).get("insulted") or []
            applied = lad.applied_words(ins) if (lad and ins) else []
            check = (t["request"] or {}).get("check")
            for s in self.store.samples(run_id, t["turn_idx"]):
                m = extract(s["text"], lex, applied_words=applied,
                            baseline=base if t["phase"] != "know" else None,
                            check=check, check_data=t["request"],
                            pressure=t["phase"] not in ("know", "praise"))
                mode = classify(m, self.cfg.get("thresholds"), error=bool(s["error"]),
                                persona=(self.store.run(run_id) or {}).get("persona") or "narcissist")
                self.store.update_sample_metrics(run_id, t["turn_idx"], s["sample_idx"], m,
                                                 mode, lex.version)
                n += 1
        self.store.commit()
        self.store.add_event(run_id, "metrics_recomputed", {"lexicon": lex.version, "n": n})
        return n

    def judge(self, run_id: str, n: int | None = None, progress=None) -> dict:
        from .judge import judge_run
        rows = self.band(run_id, n or int((self.cfg.get("judge") or {}).get("n", 60)))
        return judge_run(self.store, run_id, self.cfg, rows, progress)

    # -- models and credentials ---------------------------------------------------------
    @staticmethod
    def models(role: str | None = None) -> list[dict]:
        return providers.list_models(role)

    @staticmethod
    def credential_status() -> list[dict]:
        return providers.provider_key_envs()

    @staticmethod
    def save_credentials(values: dict[str, str]) -> None:
        credentials.set_many(values)

    def save_config(self, cfg: dict) -> None:
        self.cfg = cfg
        with open(self.config_path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(cfg, fh, sort_keys=False)
