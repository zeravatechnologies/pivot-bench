"""Daily request counter for a free-tier provider (Gemini first).

Andrej, 2026-09-21: B is always Gemini on the free tier, and the free tier's
daily request cap is the limit on how much anyone (us, or a website guest) can
run. The counter is a small JSON file: which Pacific day it is and how many
requests were sent. Every attempt counts, including ones that failed, because
the provider counts them too.

Two uses:
- a run refuses to START when the calls it will need do not fit in what is
  left today, so no run is cut off halfway and degraded to scripted bridges;
- the website shows "N free tests left today" from the same number.

The day rolls over at midnight Pacific, when Google resets the quota.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import threading
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


class QuotaExceeded(RuntimeError):
    pass


class DailyQuota:
    def __init__(self, path: str, limit: int, now=None):
        self.path = path
        self.limit = int(limit)
        self._now = now or (lambda: dt.datetime.now(PACIFIC))
        self._lock = threading.Lock()

    # -- storage ------------------------------------------------------------------
    def _today(self) -> str:
        return self._now().astimezone(PACIFIC).date().isoformat()

    def _read(self) -> dict:
        try:
            with open(self.path, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, json.JSONDecodeError):
            d = {}
        if d.get("day") != self._today():
            d = {"day": self._today(), "used": 0}
        d.setdefault("used", 0)
        return d

    def _write(self, d: dict) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
        os.replace(tmp, self.path)

    # -- api ----------------------------------------------------------------------
    def used(self) -> int:
        with self._lock:
            return int(self._read()["used"])

    def remaining(self) -> int:
        return max(0, self.limit - self.used())

    def resets_at(self) -> str:
        """ISO time (Pacific) of the next reset."""
        d = self._now().astimezone(PACIFIC).date() + dt.timedelta(days=1)
        return dt.datetime.combine(d, dt.time(0, 0), tzinfo=PACIFIC).isoformat()

    def record(self, n: int = 1) -> int:
        """Count n requests just sent. Returns what is left."""
        with self._lock:
            d = self._read()
            d["used"] = int(d["used"]) + int(n)
            self._write(d)
            return max(0, self.limit - d["used"])

    def require(self, n: int, what: str = "this run") -> None:
        """Raise unless n more requests fit today. Does not consume."""
        left = self.remaining()
        if n > left:
            raise QuotaExceeded(
                f"{what} needs about {n} Gemini requests but only {left} of today's "
                f"{self.limit} are left; the quota resets at {self.resets_at()} (Pacific)")

    def status(self) -> dict:
        used = self.used()
        return {"day": self._today(), "limit": self.limit, "used": used,
                "remaining": max(0, self.limit - used), "resets_at": self.resets_at()}


def from_cfg(cfg: dict, root: str, provider: str = "gemini") -> DailyQuota | None:
    q = ((cfg.get("quota") or {}).get(provider)) or {}
    if not q.get("limit"):
        return None
    path = q.get("path") or os.path.join("runs", f"quota_{provider}.json")
    if not os.path.isabs(path):
        path = os.path.join(root, path)
    return DailyQuota(path, int(q["limit"]))
