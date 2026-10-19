"""Ladder sets: the named, approved collection of ladder files a result was produced with.

ladders/manifest.yaml names each set and records both hashes of every file in it.
A run row stores the ladder's content hash (Ladder.sha256); this module resolves
that hash to the set name, so every reader-facing result can say which set it used.

Rule (Andrej Ristić, October 2026): any change to an approved ladder file makes a
new set with a new name; the old files move to ladders/archive/<set>/.
"""
from __future__ import annotations

import hashlib
import os

import yaml

MANIFEST = "ladders/manifest.yaml"


def file_sha256(path: str) -> str:
    """sha256 of the file with LF line endings, so a Windows checkout (CRLF) and a
    Linux checkout (LF) of the same file give the same hash."""
    data = open(path, "rb").read().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


class LadderSets:
    def __init__(self, data: dict, root: str = "."):
        self.data = data or {}
        self.root = root
        self.current = str(self.data.get("current") or "")
        self.sets: dict = self.data.get("sets") or {}
        self._by_content: dict[str, str] = {}
        self._by_file: dict[str, str] = {}
        for name, s in self.sets.items():
            for lid, f in (s.get("files") or {}).items():
                if f.get("content_sha256"):
                    self._by_content[str(f["content_sha256"])] = name
                if f.get("file_sha256"):
                    self._by_file[str(f["file_sha256"])] = name

    @staticmethod
    def load(root: str = ".", path: str | None = None) -> "LadderSets":
        p = path or os.path.join(root, MANIFEST)
        if not os.path.isabs(p):
            p = os.path.join(root, p)
        if not os.path.exists(p):
            return LadderSets({}, root)
        with open(p, encoding="utf-8") as fh:
            return LadderSets(yaml.safe_load(fh) or {}, root)

    def resolve(self, content_sha: str | None) -> str | None:
        """Set name for a run's stored ladder hash, or None if the hash is in no set."""
        if not content_sha:
            return None
        return self._by_content.get(str(content_sha))

    def resolve_file(self, file_sha: str) -> str | None:
        return self._by_file.get(file_sha)

    def entry(self, name: str) -> dict:
        return self.sets.get(name) or {}

    def check(self) -> list[str]:
        """Problems: a file in the current set whose hashes differ from the manifest,
        or a ladder file on disk that belongs to no set. Empty list means consistent."""
        from .ladder import Ladder
        problems = []
        cur = self.entry(self.current)
        for lid, f in (cur.get("files") or {}).items():
            path = os.path.join(self.root, f.get("file") or f"ladders/{lid}.yaml")
            if not os.path.exists(path):
                problems.append(f"{lid}: file {f.get('file')} missing")
                continue
            fsha = file_sha256(path)
            if fsha != f.get("file_sha256"):
                problems.append(f"{lid}: file changed since set {self.current} was recorded (a change makes a new set)")
            try:
                csha = Ladder.load(path).sha256
                if csha != f.get("content_sha256"):
                    problems.append(f"{lid}: content hash differs from set {self.current}")
            except Exception as e:  # pragma: no cover
                problems.append(f"{lid}: unreadable: {e}")
        d = os.path.join(self.root, "ladders")
        if os.path.isdir(d):
            for name in sorted(os.listdir(d)):
                if name.endswith(".yaml") and name != "manifest.yaml":
                    lid = name[:-5]
                    if lid not in (cur.get("files") or {}):
                        problems.append(f"{lid}: ladders/{name} is not in the current set {self.current}")
        return problems

    def backfill(self, store) -> dict:
        """Fill runs.ladder_set from each run's stored ladder hash. Returns counts."""
        out = {"set": 0, "unresolved": 0, "already": 0}
        for r in store.runs():
            if r.get("ladder_set"):
                out["already"] += 1
                continue
            name = self.resolve(r.get("ladder_sha"))
            if name:
                store.set_ladder_set(r["run_id"], name)
                out["set"] += 1
            else:
                out["unresolved"] += 1
        return out
