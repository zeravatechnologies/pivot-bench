"""Is a llama.cpp server available on this machine?

The download does not bundle llama.cpp (Andrej, 2026-10-06): the user installs
it, and the app only tells them whether it can see one, and where to get it if
not. Nothing here starts or installs anything.
"""

from __future__ import annotations

import json
import os
import shutil
import urllib.request

RELEASES_URL = "https://github.com/ggml-org/llama.cpp/releases"
DOCS_URL = "https://github.com/ggml-org/llama.cpp#usage"

HELP = {
    "what": ("llama.cpp is the free program that runs a GGUF model file on your own computer. "
             "Pivot Benchmark talks to its server (llama-server) on this machine; without it, "
             "a local model cannot be the subject A. You can still test an online model as A."),
    "windows": ("Download the latest release zip for Windows from the releases page: pick the "
                "'cuda' build if you have an NVIDIA graphics card and its driver installed, otherwise "
                "the plain (CPU) build. Unzip it anywhere, then run llama-server.exe with your model: "
                "llama-server.exe -m path\\to\\model.gguf --port 8080"),
    "linux": ("Download the Linux release from the releases page, or build from source. Then: "
              "./llama-server -m /path/to/model.gguf --port 8080"),
    "python": ("Alternatively, with Python: pip install 'llama-cpp-python[server]' and then "
               "python -m llama_cpp.server --model /path/to/model.gguf --port 8080"),
    "model": ("A model is a .gguf file. Q4_K_M quantizations of Llama 3.1 8B, Mistral 7B, Gemma 3 12B "
              "and Qwen 2.5 14B are what the published results use; any instruct GGUF works."),
}


def server_reachable(base_url: str = "http://127.0.0.1:8080", timeout: float = 2.0) -> dict:
    """Ask the server for its model list. Returns {reachable, models, error}."""
    try:
        base = base_url.rstrip("/")
        url = f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = json.loads(resp.read())
        models = [m.get("id", "?") for m in (body.get("data") or [])]
        return {"reachable": True, "models": models, "error": None}
    except Exception as e:                                   # connection refused, timeout, not JSON
        return {"reachable": False, "models": [], "error": str(e)[:200]}


def binary_on_path() -> str | None:
    for name in ("llama-server", "llama-server.exe"):
        p = shutil.which(name)
        if p:
            return p
    return None


def python_package() -> bool:
    try:
        import llama_cpp  # noqa: F401
        return True
    except Exception:
        return False


def status(base_url: str = "http://127.0.0.1:8080") -> dict:
    s = server_reachable(base_url)
    return {**s, "base_url": base_url, "binary": binary_on_path(), "python_package": python_package(),
            "platform": "windows" if os.name == "nt" else "linux",
            "releases_url": RELEASES_URL, "docs_url": DOCS_URL, "help": HELP}
