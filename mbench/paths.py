"""Where an installed Pivot Benchmark keeps the user's data.

An installed program must never write inside its own install folder (it is
read-only on Windows under Program Files and under /opt on Ubuntu). So the
runs database, the Gemini quota counter, logs and the user's own config.yaml
live in the user's data folder:

    Windows   %APPDATA%\\Pivot Benchmark
    Linux     $XDG_DATA_HOME/pivot-benchmark  (default ~/.local/share/pivot-benchmark)
    macOS     ~/Library/Application Support/Pivot Benchmark

The repository's config.yaml stays the source of defaults. On first start it
is copied into the data folder with the store and quota paths rewritten to
point there; afterwards the user's copy is what the app reads, so settings
survive upgrades. Ladders, personas and lexicons are read from the install
folder (they are part of the frozen, versioned benchmark, not user data).

Developers running from the repository keep the old behaviour (everything
under the repo) unless PIVOT_USER_DATA=1 is set or the app entry point is used.
"""

from __future__ import annotations

import os
import shutil

import yaml

APP_DIRNAME = "Pivot Benchmark"
UNIX_DIRNAME = "pivot-benchmark"


def user_data_dir() -> str:
    override = os.environ.get("PIVOT_DATA_DIR")
    if override:
        return override
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Roaming")
        return os.path.join(base, APP_DIRNAME)
    if sys_platform() == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", APP_DIRNAME)
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, UNIX_DIRNAME)


def sys_platform() -> str:
    import sys
    return sys.platform


def ensure_user_config(root: str, data_dir: str | None = None) -> str:
    """Create the data folder and the user's config.yaml if missing; return the config path.

    The user's copy points store.db and quota paths into the data folder. An
    existing user config is left alone except that missing keys are not
    back-filled (the engine's defaults cover them)."""
    data_dir = data_dir or user_data_dir()
    os.makedirs(os.path.join(data_dir, "runs"), exist_ok=True)
    cfg_path = os.path.join(data_dir, "config.yaml")
    if not os.path.exists(cfg_path):
        with open(os.path.join(root, "config.yaml"), encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        cfg.setdefault("store", {})["db"] = os.path.join(data_dir, "runs", "mbench.sqlite")
        for prov, q in (cfg.get("quota") or {}).items():
            if isinstance(q, dict):
                q["path"] = os.path.join(data_dir, "runs", f"quota_{prov}.json")
        cfg["_user_data_dir"] = data_dir
        with open(cfg_path, "w", encoding="utf-8") as fh:
            fh.write("# Pivot Benchmark user settings. Created from the installed defaults on first start.\n"
                     "# Delete this file to start again from the defaults.\n")
            yaml.safe_dump(cfg, fh, sort_keys=False, allow_unicode=True)
    return cfg_path


def copy_defaults_if_missing(root: str, data_dir: str, names=("canary.yaml",)) -> None:
    """Optional user-editable files that start as copies of the shipped ones."""
    for n in names:
        src, dst = os.path.join(root, n), os.path.join(data_dir, n)
        if os.path.exists(src) and not os.path.exists(dst):
            shutil.copyfile(src, dst)
