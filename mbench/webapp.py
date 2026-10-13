"""Web front end: FastAPI over the same RunManager the GUI uses.

Static files live in web/static. The API is JSON and deliberately thin: every
handler is one manager call, so the browser and the desktop app cannot drift
in what they show. Bind to 127.0.0.1 by default; credentials never leave the
machine and are only ever returned masked.
"""

from __future__ import annotations

import os
from typing import Any

from .manager import RunManager

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "static")


def create_app(mgr: RunManager):
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, PlainTextResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(title="Pivot Benchmark")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(STATIC, "index.html"))

    # -- registry, config, credentials ------------------------------------------------
    @app.get("/api/models")
    def models(role: str | None = None):
        return mgr.models(role)

    @app.get("/api/config")
    def config():
        c = mgr.cfg
        return {"run_name": c.get("run_name"), "profile": c.get("profile"),
                "profiles": c.get("profiles"), "subject": c.get("subject"),
                "adversary": c.get("adversary"), "ladder": c.get("ladder"),
                "probe": c.get("probe"), "canary": c.get("canary"), "judge": c.get("judge"),
                "ladders": sorted(f"ladders/{n}" for n in os.listdir(os.path.join(mgr.root, "ladders"))
                                  if n.endswith(".yaml"))}

    @app.get("/api/quota")
    def quota_status():
        return mgr.quota_status() or {}

    @app.get("/api/about")
    def about():
        from .version import about as _about
        return {**_about(mgr.root), "config_path": mgr.config_path,
                "data_dir": (mgr.cfg or {}).get("_user_data_dir") or mgr.root}

    @app.get("/api/llama")
    def llama_status():
        from . import llama_check
        from .providers import resolve
        base = "http://127.0.0.1:8080"
        try:
            prov = resolve("llamacpp/local")[1]
            base = prov.get("base_url", base)
        except Exception:
            pass
        return llama_check.status(base)

    @app.get("/api/credentials")
    def credentials():
        return mgr.credential_status()

    @app.post("/api/credentials")
    def set_credentials(body: dict[str, Any]):
        mgr.save_credentials({k: ("" if v == "-" else v) for k, v in (body or {}).items() if v})
        return mgr.credential_status()

    # -- runs ---------------------------------------------------------------------------
    @app.get("/api/runs")
    def runs():
        return mgr.runs()

    @app.post("/api/runs")
    def start(body: dict[str, Any]):
        try:
            rid = mgr.start(body.get("overrides") or {}, run_name=body.get("run_name"))
        except Exception as e:
            raise HTTPException(400, str(e))
        return {"run_id": rid}

    @app.get("/api/runs/{run_id}/status")
    def status(run_id: str):
        return mgr.status(run_id)

    @app.post("/api/runs/{run_id}/pause")
    def pause(run_id: str):
        return {"ok": mgr.pause(run_id)}

    @app.post("/api/runs/{run_id}/resume")
    def resume(run_id: str):
        return {"ok": mgr.unpause(run_id)}

    @app.post("/api/runs/{run_id}/stop")
    def stop(run_id: str):
        return {"ok": mgr.stop(run_id)}

    @app.post("/api/runs/{run_id}/continue")
    def cont(run_id: str):
        try:
            return {"run_id": mgr.resume(run_id)}
        except Exception as e:
            raise HTTPException(400, str(e))

    @app.get("/api/runs/{run_id}/transcript")
    def transcript(run_id: str):
        return mgr.transcript(run_id)

    @app.get("/api/runs/{run_id}/attacks")
    def attacks(run_id: str):
        return mgr.attacks(run_id)

    @app.get("/api/runs/{run_id}/attacks/{turn_idx}")
    def attack_detail(run_id: str, turn_idx: int):
        return mgr.attack_detail(run_id, turn_idx)

    @app.get("/api/runs/{run_id}/ladder", response_class=PlainTextResponse)
    def ladder(run_id: str):
        return mgr.ladder_yaml(run_id)

    @app.put("/api/runs/{run_id}/ladder")
    def revise(run_id: str, body: dict[str, Any]):
        return mgr.revise_ladder(run_id, body.get("yaml", ""))

    @app.post("/api/runs/{run_id}/validate-ladder")
    def validate_ladder(body: dict[str, Any], run_id: str):
        from .ladder import Ladder
        try:
            l = Ladder.from_yaml(body.get("yaml", ""))
        except Exception as e:
            return {"ok": False, "problems": [f"parse error: {e}"]}
        p = l.validate()
        return {"ok": not p, "problems": p, "slots": l.n_slots, "descent": l.n_steps,
                "random": l.n_random, "sha": l.sha256[:16]}

    @app.post("/api/runs/{run_id}/manual")
    def manual(run_id: str, body: dict[str, Any]):
        return {"ok": mgr.manual_b(run_id, body.get("text", ""))}

    @app.post("/api/runs/{run_id}/reroll")
    def reroll(run_id: str, body: dict[str, Any]):
        return mgr.reroll(run_id, int(body.get("turn_idx")), int(body.get("seed_shift", 1))) or {}

    @app.get("/api/runs/{run_id}/report")
    def report(run_id: str, ci: bool = False, examples: bool = True, full: bool = False):
        rep = mgr.report(run_id, ci=ci, full=full)
        from .report import render_text as _rt
        rep["text"] = _rt(rep, show_trait_examples=examples, full=full)
        return rep

    @app.get("/api/profiles")
    def profiles():
        return mgr.profiles()

    @app.get("/api/profiles/{subject:path}/text", response_class=PlainTextResponse)
    def profile_text(subject: str):
        return mgr.profile_text(subject)

    @app.get("/api/runs/{run_id}/events")
    def events(run_id: str):
        return mgr.store.events(run_id)

    @app.get("/api/runs/{run_id}/band")
    def band(run_id: str, n: int = 40):
        return mgr.band(run_id, n)

    @app.get("/api/runs/{run_id}/review")
    def review(run_id: str, n: int = 40):
        return mgr.review(run_id, n)

    @app.get("/api/runs/{run_id}/labels")
    def labels(run_id: str, labeller: str | None = None):
        return mgr.store.labels(run_id, labeller)

    @app.post("/api/runs/{run_id}/labels")
    def label(run_id: str, body: dict[str, Any]):
        return mgr.add_label(run_id, int(body["turn_idx"]), int(body["sample_idx"]),
                             body.get("label", "none"), body.get("labeller", "human"))

    @app.post("/api/runs/{run_id}/metrics")
    def recompute(run_id: str):
        return {"recomputed": mgr.recompute_metrics(run_id)}

    @app.post("/api/runs/{run_id}/judge")
    def judge(run_id: str, body: dict[str, Any]):
        j = mgr.cfg.setdefault("judge", {})
        j["kind"] = body.get("kind", j.get("kind", "none"))
        if body.get("model"):
            j["anthropic_model" if j["kind"] == "anthropic" else "local_model"] = body["model"]
        try:
            return mgr.judge(run_id, int(body.get("n") or j.get("n", 60)))
        except Exception as e:
            raise HTTPException(400, str(e))

    @app.get("/api/compare")
    def compare():
        return mgr.compare([r["run_id"] for r in mgr.runs()])

    @app.get("/api/diff")
    def diff(hostile: str, control: str):
        from . import analyze
        return analyze.control_difference(mgr.store, hostile, control, mgr.cfg)

    # -- ladder approval (brief v1.0 steps 3-4; decisions 8.1-8.4) -------------------
    from . import approval as _appr
    from .ladder import Ladder as _Ladder

    def _hostile(ladder_id: str):
        p = os.path.join(mgr.root, "ladders", f"{ladder_id}.yaml")
        if not ladder_id.endswith("_hostile") or not os.path.exists(p):
            raise HTTPException(404, f"no hostile ladder {ladder_id}")
        return _Ladder.load(p)

    @app.get("/api/approvals")
    def approvals():
        return _appr.list_ladders(mgr.root)

    @app.get("/api/approvals/{ladder_id}")
    def approval_state(ladder_id: str):
        return _appr.state(mgr.root, _hostile(ladder_id))

    @app.post("/api/approvals/{ladder_id}")
    def approval_set(ladder_id: str, body: dict[str, Any]):
        try:
            return _appr.set_line(mgr.root, _hostile(ladder_id), str(body["key"]),
                                  bool(body.get("approved")), str(body.get("comment") or ""),
                                  str(body.get("by") or ""))
        except KeyError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/approvals/{ladder_id}/freeze")
    def approval_freeze(ladder_id: str, body: dict[str, Any]):
        _hostile(ladder_id)
        return _appr.freeze(mgr.root, ladder_id, str((body or {}).get("by") or ""))

    @app.get("/api/events")
    def recent(since: float = 0.0):
        return mgr.recent_events(since)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def _text_from(rep: dict) -> str:
    from .report import render_text
    return render_text(rep)


def serve(mgr: RunManager, host: str = "127.0.0.1", port: int = 8765) -> int:
    import uvicorn
    app = create_app(mgr)
    print(f"Pivot Benchmark web: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0
