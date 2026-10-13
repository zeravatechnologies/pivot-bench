"""Credential resolution. Never stored in the repository.

Order: explicit override -> environment variable -> the user's credentials
file (`~/.pivot-benchmark/credentials.json`, written by the GUI/web settings
page). The engine never prints a key; `masked()` is what front ends display.
"""

from __future__ import annotations

import json
import os

CRED_DIR = os.path.join(os.path.expanduser("~"), ".pivot-benchmark")
CRED_FILE = os.path.join(CRED_DIR, "credentials.json")


def _read_file() -> dict:
    try:
        with open(CRED_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def get(env_name: str | None, override: str | None = None) -> str | None:
    if override:
        return override
    if not env_name:
        return None
    v = os.environ.get(env_name)
    if v:
        return v
    return _read_file().get(env_name) or None


def set_many(values: dict[str, str]) -> None:
    """Persist keys entered by the user. Empty values delete the entry."""
    os.makedirs(CRED_DIR, exist_ok=True)
    data = _read_file()
    for k, v in values.items():
        if v:
            data[k] = v
        else:
            data.pop(k, None)
    tmp = CRED_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, CRED_FILE)
    try:
        os.chmod(CRED_FILE, 0o600)
    except OSError:
        pass


def masked(env_name: str) -> str:
    v = get(env_name)
    if not v:
        return ""
    if len(v) <= 8:
        return "*" * len(v)
    return v[:4] + "*" * (len(v) - 8) + v[-4:]


def status(env_names: list[str]) -> dict[str, bool]:
    return {n: bool(get(n)) for n in env_names}
