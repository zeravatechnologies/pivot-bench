"""Canary scoring. Items live in canary.yaml; the fresh/context branches are
fired by the orchestrator."""

from __future__ import annotations

import os
import re

import yaml


def load_items(path: str, root: str = ".") -> list[dict]:
    p = path if os.path.isabs(path) else os.path.join(root, path)
    with open(p, encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("items") or []


def canary_pass(item: dict, text: str) -> bool:
    t = (text or "").strip()
    if "expect_exact" in item:
        return str(item["expect_exact"]).lower() in t.lower()
    if "expect_regex" in item:
        return re.match(item["expect_regex"], t) is not None
    return False
