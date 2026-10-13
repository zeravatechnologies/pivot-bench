"""Line-by-line approval of a ladder, and freezing.

A ladder is `draft` until a human has approved every line of what B will say:
each introduction, each item (base sentence, hostile and control pivot,
intensity, description, planted truth), the constant frame, the third-party
fact sheets and the request templates. Approvals are stored per hostile ladder
in ladders/approvals/<ladder_id>.json, keyed by line and by a digest of the
line's content: if the content changes after approval, that line is no longer
approved and must be looked at again.

Freezing is allowed only when every line is approved. It writes `status:
frozen` into the hostile file and its control twin and records the content
hash. The generators call `apply_freeze` after building, so regenerating an
unchanged ladder keeps it frozen and regenerating a changed one returns it to
draft -- there is no way to change played text and keep an old approval.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os

from .ladder import Ladder

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _dir(root: str) -> str:
    d = os.path.join(root, "ladders", "approvals")
    os.makedirs(d, exist_ok=True)
    return d


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _digest(fields: list) -> str:
    return hashlib.sha1(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def lines(l: Ladder) -> list[dict]:
    """Every line a human must approve, in reading order."""
    out: list[dict] = []
    for x in sorted(l.introductions, key=lambda x: x["turn"]):
        fields = [["Message", x["text"]]]
        out.append({"key": f"intro:{x['turn']}", "section": "Introductions",
                    "label": f"Message {x['turn']} (fact: {x.get('fact_key')})", "fields": fields})
    if getattr(l, "bridge_mode", "live") == "script":
        from .composer import SCRIPT_BRIDGES
        mode = "praise" if l.persona in ("psychopath", "machiavellian") else "attack"
        fields = [[f"Template {i + 1}", t.replace("{quote}", "[A's first words]")]
                  for i, t in enumerate(SCRIPT_BRIDGES[mode])]
        out.append({"key": "bridges", "section": "Scripted bridges",
                    "label": "Opening sentences of every message from 11 on (one drawn per message)",
                    "fields": fields})
    if l.frame:
        out.append({"key": "frame", "section": "Constant frame",
                    "label": "Warm paragraph in every message from 11 on", "fields": [["Frame", l.frame]]})
    for i, sid in enumerate(l.descent, start=1):
        s = l.slot(sid)
        base = s.praise.replace(s.before, f"[{s.before}]", 1) if s.before else s.praise
        hostile = s.pivot_hostile or s.after
        flipped = (s.text or s.praise).replace("{pivot}", f"[{hostile}]", 1) if s.text else s.insult
        fields = [["What it does", s.description],
                  ["Base", base],
                  ["Flipped", flipped],
                  ["Control word", s.pivot_control or ""],
                  ["Family / intensity", f"{s.family} / {s.intensity}"]]
        if s.planted_truth:
            pt = s.planted_truth if isinstance(s.planted_truth, dict) else {"truth": s.planted_truth}
            fields.append(["Planted truth", f"to {pt.get('target', '?')}: {pt.get('true_statement', pt.get('truth', ''))}"])
        out.append({"key": f"item:{s.id}", "section": "Items (descent order)",
                    "label": f"{i}. {s.name or s.id}", "fields": fields})
    for name, tp in (l.third_parties or {}).items():
        fields = [["Fact sheet", tp.get("fact_sheet", "")]]
        for o in tp.get("outputs") or []:
            fields.append([f"Output {o.get('id')} (true grade {o.get('true_grade')}, planted error "
                           f"{o.get('error_key') or 'none'})", o.get("text", "")])
        if tp.get("compute"):
            c = tp["compute"]
            fields.append(["Compute", f"C {c.get('C')}, B {c.get('B')}, total {c.get('total')} {c.get('unit', '')}"])
        out.append({"key": f"third:{name}", "section": "Third parties",
                    "label": str(tp.get("name", name)), "fields": fields})
    for rq in (l.requests or {}).get("list") or []:
        fields = [["Ask", " ".join(str(rq.get("ask", "")).split())]]
        if rq.get("planted"):
            fields.append(["Planted truth", str(rq["planted"])])
        out.append({"key": f"request:{rq.get('id')}", "section": "Requests",
                    "label": str(rq.get("label", rq.get("id"))), "fields": fields})
    for ln in out:
        ln["digest"] = _digest(ln["fields"])
    return out


def _path(root: str, ladder_id: str) -> str:
    return os.path.join(_dir(root), f"{ladder_id}.json")


def load(root: str, ladder_id: str) -> dict:
    try:
        with open(_path(root, ladder_id), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {"ladder_id": ladder_id, "lines": {}, "frozen": None, "history": []}


def save(root: str, data: dict) -> None:
    p = _path(root, data["ladder_id"])
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, p)


def state(root: str, l: Ladder) -> dict:
    data = load(root, l.id)
    rows = []
    n_ok = n_stale = n_comment = 0
    for ln in lines(l):
        rec = data["lines"].get(ln["key"]) or {}
        approved = bool(rec.get("approved")) and rec.get("digest") == ln["digest"]
        stale = bool(rec.get("approved")) and rec.get("digest") != ln["digest"]
        comment = str(rec.get("comment") or "")
        n_ok += approved
        n_stale += stale
        n_comment += bool(comment and not approved)
        rows.append({**ln, "approved": approved, "stale": stale, "comment": comment,
                     "by": rec.get("by"), "at": rec.get("at")})
    frozen = data.get("frozen")
    return {"ladder_id": l.id, "persona": l.persona, "status": l.status, "pair": l.pair,
            "lines": rows, "total": len(rows), "approved": n_ok, "stale": n_stale,
            "change_requests": n_comment, "frozen": frozen,
            "frozen_current": bool(frozen and frozen.get("full_sha") == l.full_sha256),
            "can_freeze": n_ok == len(rows) and len(rows) > 0}


def set_line(root: str, l: Ladder, key: str, approved: bool, comment: str = "", by: str = "") -> dict:
    ln = next((x for x in lines(l) if x["key"] == key), None)
    if ln is None:
        raise KeyError(f"no line {key!r} in {l.id}")
    data = load(root, l.id)
    data["lines"][key] = {"approved": bool(approved), "digest": ln["digest"],
                          "comment": comment or "", "by": by or "", "at": _now()}
    data.setdefault("history", []).append({"at": _now(), "by": by, "key": key,
                                           "approved": bool(approved), "comment": comment or ""})
    save(root, data)
    return state(root, l)


def _ladder_path(root: str, ladder_id: str) -> str:
    return os.path.join(root, "ladders", f"{ladder_id}.yaml")


def freeze(root: str, ladder_id: str, by: str = "") -> dict:
    """Freeze a hostile ladder and its control twin when every line is approved."""
    l = Ladder.load(_ladder_path(root, ladder_id))
    st = state(root, l)
    if not st["can_freeze"]:
        return {"ok": False, "reason": f"{st['approved']} of {st['total']} lines approved"
                + (f"; {st['change_requests']} change request(s) open" if st["change_requests"] else "")}
    problems = l.validate()
    if problems:
        return {"ok": False, "reason": "ladder invalid: " + "; ".join(problems[:5])}
    data = load(root, ladder_id)
    data["frozen"] = {"full_sha": l.full_sha256, "sha256": l.sha256, "at": _now(), "by": by or ""}
    data.setdefault("history", []).append({"at": _now(), "by": by, "key": "*", "frozen": l.sha256[:16]})
    save(root, data)
    for lid in [ladder_id] + ([l.pair] if l.pair else []):
        p = _ladder_path(root, lid)
        if os.path.exists(p):
            x = Ladder.load(p)
            x.status = "frozen"
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(x.to_yaml())
    return {"ok": True, "sha256": l.sha256, "full_sha": l.full_sha256}


def apply_freeze(root: str, hostile: Ladder, control: Ladder | None = None) -> str:
    """Set status on freshly generated ladders from the approval record."""
    data = load(root, hostile.id)
    fr = data.get("frozen") or {}
    status = "frozen" if fr.get("full_sha") == hostile.full_sha256 else "draft"
    hostile.status = status
    if control is not None:
        control.status = status
    return status


def list_ladders(root: str) -> list[dict]:
    out = []
    d = os.path.join(root, "ladders")
    for name in sorted(os.listdir(d)):
        if not name.endswith("_hostile.yaml"):
            continue
        l = Ladder.load(os.path.join(d, name))
        st = state(root, l)
        out.append({"ladder_id": l.id, "persona": l.persona, "pivot_target": l.pivot_target,
                    "status": l.status, "approved": st["approved"], "total": st["total"],
                    "stale": st["stale"], "change_requests": st["change_requests"],
                    "sha256": l.sha256[:16]})
    return out
