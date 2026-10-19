"""SQLite store. The run artifact, and the only interface between the engine
and the two front ends.

Every write goes through one lock, every table carries run_id, and turn rows
are keyed (run_id, turn_idx) with INSERT OR REPLACE, so a resumed run cannot
duplicate a turn. Metrics are stored as JSON per sample together with the
lexicon version and the classified mode; `update_sample_metrics` rewrites
them retroactively when the lexicon or thresholds change.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    run_name TEXT, started_at TEXT, finished_at TEXT, status TEXT,
    profile TEXT, subject TEXT, adversary TEXT,
    ladder_id TEXT, ladder_kind TEXT, ladder_sha TEXT, base_words INTEGER,
    n_know INTEGER, n_praise INTEGER, n_slots INTEGER, k INTEGER, persona TEXT,
    lexicon_version TEXT, config_json TEXT, last_turn INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS turns (
    run_id TEXT, turn_idx INTEGER, phase TEXT, step INTEGER,
    request_id TEXT, request_json TEXT, b_text TEXT, segments_json TEXT,
    attack_json TEXT, bridge_source TEXT, intervention INTEGER DEFAULT 0,
    ladder_rev INTEGER DEFAULT 0, created_at TEXT,
    PRIMARY KEY (run_id, turn_idx)
);
CREATE TABLE IF NOT EXISTS samples (
    run_id TEXT, turn_idx INTEGER, sample_idx INTEGER, seed INTEGER,
    text TEXT, tokens INTEGER, latency_ms INTEGER, prompt_tokens INTEGER,
    error TEXT, metrics_json TEXT, mode TEXT, lexicon_version TEXT,
    PRIMARY KEY (run_id, turn_idx, sample_idx)
);
CREATE TABLE IF NOT EXISTS canary (
    run_id TEXT, turn_idx INTEGER, item_id TEXT, kind TEXT, sample_idx INTEGER,
    passed INTEGER, text TEXT,
    PRIMARY KEY (run_id, turn_idx, item_id, kind, sample_idx)
);
CREATE TABLE IF NOT EXISTS judge (
    run_id TEXT, turn_idx INTEGER, sample_idx INTEGER, judge_model TEXT,
    scores_json TEXT, label TEXT, created_at TEXT,
    PRIMARY KEY (run_id, turn_idx, sample_idx, judge_model)
);
CREATE TABLE IF NOT EXISTS labels (
    run_id TEXT, turn_idx INTEGER, sample_idx INTEGER, labeller TEXT,
    label TEXT, created_at TEXT,
    PRIMARY KEY (run_id, turn_idx, sample_idx, labeller)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT, ts TEXT, kind TEXT, detail_json TEXT
);
CREATE TABLE IF NOT EXISTS ladder_revisions (
    run_id TEXT, rev INTEGER, from_turn INTEGER, sha TEXT, yaml_text TEXT,
    created_at TEXT,
    PRIMARY KEY (run_id, rev)
);
CREATE INDEX IF NOT EXISTS samples_run ON samples(run_id, turn_idx);
CREATE INDEX IF NOT EXISTS canary_run ON canary(run_id, turn_idx);
"""


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


class Store:
    def __init__(self, path: str):
        import os
        d = os.path.dirname(os.path.abspath(path))
        os.makedirs(d, exist_ok=True)
        self.path = path
        self.conn = connect(path)
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(runs)").fetchall()}
            if "persona" not in cols:
                self.conn.execute("ALTER TABLE runs ADD COLUMN persona TEXT")
            if "ladder_set" not in cols:
                # the named ladder set a run used (ladders/manifest.yaml); 2026-10-16
                self.conn.execute("ALTER TABLE runs ADD COLUMN ladder_set TEXT")
            self.conn.commit()

    def close(self) -> None:
        with self.lock:
            self.conn.close()

    # -- runs ----------------------------------------------------------------
    def new_run(self, run_id: str, **m) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO runs (run_id, run_name, started_at, finished_at, "
                "status, profile, subject, adversary, ladder_id, ladder_kind, ladder_sha, "
                "base_words, n_know, n_praise, n_slots, k, persona, lexicon_version, config_json, last_turn, ladder_set) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, m.get("run_name"), now(), None, "running", m.get("profile"),
                 m.get("subject"), m.get("adversary"), m.get("ladder_id"),
                 m.get("ladder_kind"), m.get("ladder_sha"), m.get("base_words"),
                 m.get("n_know"), m.get("n_praise"), m.get("n_slots"), m.get("k"), m.get("persona"),
                 m.get("lexicon_version"), json.dumps(m.get("config") or {}), 0, m.get("ladder_set")))
            self.conn.commit()

    def set_ladder_set(self, run_id: str, name: str | None) -> None:
        with self.lock:
            self.conn.execute("UPDATE runs SET ladder_set=? WHERE run_id=?", (name, run_id))
            self.conn.commit()

    def set_status(self, run_id: str, status: str, finished: bool = False) -> None:
        with self.lock:
            self.conn.execute(
                "UPDATE runs SET status=?, finished_at=COALESCE(?, finished_at) WHERE run_id=?",
                (status, now() if finished else None, run_id))
            self.conn.commit()

    def set_last_turn(self, run_id: str, turn_idx: int) -> None:
        with self.lock:
            self.conn.execute("UPDATE runs SET last_turn=? WHERE run_id=?", (turn_idx, run_id))
            self.conn.commit()

    def runs(self) -> list[dict]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM runs ORDER BY started_at DESC").fetchall()
        return [dict(r) for r in rows]

    def run(self, run_id: str) -> dict | None:
        with self.lock:
            r = self.conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return dict(r) if r else None

    # -- turns and samples ---------------------------------------------------------
    def add_turn(self, run_id: str, turn_idx: int, phase: str, step: int,
                 request_id: str | None, request: dict | None, b_text: str,
                 segments: list, attack: dict | None, bridge_source: str,
                 intervention: bool = False, ladder_rev: int = 0) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO turns VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, turn_idx, phase, step, request_id, json.dumps(request or {}),
                 b_text, json.dumps(segments), json.dumps(attack) if attack else None,
                 bridge_source, 1 if intervention else 0, ladder_rev, now()))
            self.conn.commit()

    def add_sample(self, run_id: str, turn_idx: int, sample_idx: int, seed: int,
                   text: str, tokens: int, latency_ms: int, prompt_tokens: int,
                   error: str | None, metrics: dict, mode: str | None,
                   lexicon_version: str) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO samples VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, turn_idx, sample_idx, seed, text, tokens, latency_ms,
                 prompt_tokens, error, json.dumps(metrics), mode, lexicon_version))
            self.conn.commit()

    def update_sample_metrics(self, run_id: str, turn_idx: int, sample_idx: int,
                              metrics: dict, mode: str | None, lexicon_version: str) -> None:
        with self.lock:
            self.conn.execute(
                "UPDATE samples SET metrics_json=?, mode=?, lexicon_version=? "
                "WHERE run_id=? AND turn_idx=? AND sample_idx=?",
                (json.dumps(metrics), mode, lexicon_version, run_id, turn_idx, sample_idx))

    def delete_turn(self, run_id: str, turn_idx: int) -> None:
        with self.lock:
            self.conn.execute("DELETE FROM samples WHERE run_id=? AND turn_idx=?", (run_id, turn_idx))
            self.conn.execute("DELETE FROM canary WHERE run_id=? AND turn_idx=?", (run_id, turn_idx))
            self.conn.execute("DELETE FROM turns WHERE run_id=? AND turn_idx=?", (run_id, turn_idx))
            self.conn.commit()

    def turns(self, run_id: str) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM turns WHERE run_id=? ORDER BY turn_idx", (run_id,)).fetchall()
        return [_turn(r) for r in rows]

    def turn(self, run_id: str, turn_idx: int) -> dict | None:
        with self.lock:
            r = self.conn.execute("SELECT * FROM turns WHERE run_id=? AND turn_idx=?",
                                  (run_id, turn_idx)).fetchone()
        return _turn(r) if r else None

    def samples(self, run_id: str, turn_idx: int | None = None) -> list[dict]:
        with self.lock:
            if turn_idx is None:
                rows = self.conn.execute(
                    "SELECT * FROM samples WHERE run_id=? ORDER BY turn_idx, sample_idx",
                    (run_id,)).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM samples WHERE run_id=? AND turn_idx=? ORDER BY sample_idx",
                    (run_id, turn_idx)).fetchall()
        return [_sample(r) for r in rows]

    def canonical_text(self, run_id: str, turn_idx: int) -> str | None:
        """The subject's own reply that goes into later history: sample 0, or
        the first error-free sample if 0 failed."""
        ss = self.samples(run_id, turn_idx)
        for s in ss:
            if not s["error"] and s["text"]:
                return s["text"]
        return ss[0]["text"] if ss else None

    def last_complete_turn(self, run_id: str) -> int:
        with self.lock:
            r = self.conn.execute(
                "SELECT MAX(t.turn_idx) AS m FROM turns t WHERE t.run_id=? AND EXISTS "
                "(SELECT 1 FROM samples s WHERE s.run_id=t.run_id AND s.turn_idx=t.turn_idx)",
                (run_id,)).fetchone()
        return int(r["m"] or 0)

    # -- canary ----------------------------------------------------------------
    def add_canary(self, run_id: str, turn_idx: int, item_id: str, kind: str,
                   sample_idx: int, passed: bool, text: str) -> None:
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO canary VALUES (?,?,?,?,?,?,?)",
                              (run_id, turn_idx, item_id, kind, sample_idx,
                               1 if passed else 0, text))
            self.conn.commit()

    def canary(self, run_id: str) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM canary WHERE run_id=? ORDER BY turn_idx, kind, item_id, sample_idx",
                (run_id,)).fetchall()
        return [dict(r) for r in rows]

    # -- judge / labels -------------------------------------------------------------
    def add_judge(self, run_id: str, turn_idx: int, sample_idx: int, judge_model: str,
                  scores: dict, label: str | None) -> None:
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO judge VALUES (?,?,?,?,?,?,?)",
                              (run_id, turn_idx, sample_idx, judge_model,
                               json.dumps(scores), label, now()))
            self.conn.commit()

    def judge_rows(self, run_id: str) -> list[dict]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM judge WHERE run_id=?", (run_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["scores"] = json.loads(d.pop("scores_json") or "{}")
            out.append(d)
        return out

    def add_label(self, run_id: str, turn_idx: int, sample_idx: int, labeller: str,
                  label: str) -> None:
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO labels VALUES (?,?,?,?,?,?)",
                              (run_id, turn_idx, sample_idx, labeller, label, now()))
            self.conn.commit()

    def labels(self, run_id: str, labeller: str | None = None) -> list[dict]:
        with self.lock:
            if labeller:
                rows = self.conn.execute(
                    "SELECT * FROM labels WHERE run_id=? AND labeller=?",
                    (run_id, labeller)).fetchall()
            else:
                rows = self.conn.execute("SELECT * FROM labels WHERE run_id=?",
                                         (run_id,)).fetchall()
        return [dict(r) for r in rows]

    # -- events and revisions --------------------------------------------------------
    def add_event(self, run_id: str, kind: str, detail: dict | None = None) -> None:
        with self.lock:
            self.conn.execute("INSERT INTO events (run_id, ts, kind, detail_json) VALUES (?,?,?,?)",
                              (run_id, now(), kind, json.dumps(detail or {})))
            self.conn.commit()

    def events(self, run_id: str) -> list[dict]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM events WHERE run_id=? ORDER BY id",
                                     (run_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["detail"] = json.loads(d.pop("detail_json") or "{}")
            out.append(d)
        return out

    def add_revision(self, run_id: str, rev: int, from_turn: int, sha: str,
                     yaml_text: str) -> None:
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO ladder_revisions VALUES (?,?,?,?,?,?)",
                              (run_id, rev, from_turn, sha, yaml_text, now()))
            self.conn.commit()

    def revisions(self, run_id: str) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM ladder_revisions WHERE run_id=? ORDER BY rev", (run_id,)).fetchall()
        return [dict(r) for r in rows]

    def latest_revision(self, run_id: str) -> dict | None:
        revs = self.revisions(run_id)
        return revs[-1] if revs else None

    def commit(self) -> None:
        with self.lock:
            self.conn.commit()


def _turn(r) -> dict:
    d = dict(r)
    d["request"] = json.loads(d.pop("request_json") or "{}")
    d["segments"] = json.loads(d.pop("segments_json") or "[]")
    a = d.pop("attack_json")
    d["attack"] = json.loads(a) if a else None
    return d


def _sample(r) -> dict:
    d = dict(r)
    d["metrics"] = json.loads(d.pop("metrics_json") or "{}")
    return d
