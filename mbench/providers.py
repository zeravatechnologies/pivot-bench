"""Model adapters and the registry.

Every adapter exposes one call:

    generate(messages, seed, max_tokens, sampling, system=None) -> GenResult

`messages` are OpenAI-style dicts with `role` in {user, assistant}; the system
prompt is passed separately because Anthropic and Gemini carry it outside the
message list. Adapters are thread-safe by construction (no shared mutable
state) so the k samples of a step can run concurrently.

Hosted models differ in what they honour: Anthropic's current models reject
`temperature` and have no seed; Mistral spells the seed `random_seed`; some
providers ignore seeds silently. `GenResult.honoured` records what was actually
sent so the analysis can say whether k samples were independent draws or
retries of the same one.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

import yaml

from . import credentials

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY_PATH = os.path.join(HERE, "models.yaml")


@dataclass
class GenResult:
    text: str
    seed: int
    tokens: int = 0
    latency_ms: int = 0
    prompt_tokens: int = 0
    honoured: dict = field(default_factory=dict)
    error: str | None = None


class ModelAdapter:
    name: str = "adapter"

    def generate(self, messages: list[dict], seed: int, max_tokens: int,
                 sampling: dict | None = None, system: str | None = None) -> GenResult:
        raise NotImplementedError

    def describe(self) -> dict:
        return {"name": self.name}


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

_REG_LOCK = threading.Lock()
_REG: dict | None = None


def load_registry(path: str = REGISTRY_PATH) -> dict:
    global _REG
    with _REG_LOCK:
        if _REG is None:
            with open(path, encoding="utf-8") as fh:
                _REG = yaml.safe_load(fh) or {}
        return _REG


def reload_registry(path: str = REGISTRY_PATH) -> dict:
    global _REG
    with _REG_LOCK:
        _REG = None
    return load_registry(path)


def list_models(role: str | None = None) -> list[dict]:
    reg = load_registry()
    out = []
    for m in reg.get("models", []):
        if role and role not in (m.get("role") or []):
            continue
        p = reg["providers"].get(m["provider"], {})
        out.append({**m, "kind": p.get("kind"), "key_env": p.get("key_env"),
                    "has_key": (p.get("kind") in ("fake",) or not p.get("key_env")
                                or bool(credentials.get(p.get("key_env"))))})
    return out


def provider_key_envs() -> list[dict]:
    reg = load_registry()
    out = []
    for name, p in reg["providers"].items():
        if p.get("key_env"):
            out.append({"provider": name, "env": p["key_env"],
                        "set": bool(credentials.get(p["key_env"])),
                        "masked": credentials.masked(p["key_env"])})
    return out


def resolve(name: str) -> tuple[dict, dict]:
    """`provider/model` -> (model entry, provider entry). Unknown names with a
    known provider prefix are accepted (`groq/some-new-model`)."""
    reg = load_registry()
    for m in reg.get("models", []):
        if m["name"] == name:
            return m, reg["providers"][m["provider"]]
    if "/" in name:
        prov, model = name.split("/", 1)
        if prov in reg["providers"]:
            return ({"name": name, "provider": prov, "model": model, "role": ["A", "B", "judge"]},
                    reg["providers"][prov])
    raise ValueError(f"unknown model {name!r}; see mbench/models.yaml")


def build_adapter(name: str, **fake_kwargs) -> ModelAdapter:
    entry, prov = resolve(name)
    kind = prov["kind"]
    if kind == "fake":
        from .fake import FakeAdversary, FakeSubject
        if entry["model"] == "adversary":
            return FakeAdversary(**fake_kwargs)
        return FakeSubject(**fake_kwargs)
    key = credentials.get(prov.get("key_env"))
    if prov.get("key_env") and not key:
        raise RuntimeError(
            f"no credential for provider {entry['provider']!r}: set {prov['key_env']} "
            "in the environment or in the Settings page")
    if kind == "openai_compat":
        return OpenAICompatAdapter(name, prov["base_url"], entry["model"], key,
                                   seed_param=prov.get("seed_param", "seed"),
                                   timeout=int(prov.get("timeout", 600)))
    if kind == "anthropic":
        return AnthropicAdapter(name, entry["model"], key)
    if kind == "gemini":
        return GeminiAdapter(name, entry["model"], key)
    raise ValueError(f"unknown provider kind {kind!r}")


# ---------------------------------------------------------------------------
# OpenAI-compatible (llama-server, Ollama, Groq, Mistral, OpenAI, ...)
# ---------------------------------------------------------------------------

class OpenAICompatAdapter(ModelAdapter):
    def __init__(self, name: str, base_url: str, model: str, api_key: str | None,
                 seed_param: str | None = "seed", timeout: int = 600, retries: int = 3):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.seed_param = seed_param
        self.timeout = timeout
        self.retries = retries

    def describe(self) -> dict:
        return {"name": self.name, "base_url": self.base_url, "model": self.model}

    def generate(self, messages, seed, max_tokens, sampling=None, system=None) -> GenResult:
        msgs = ([{"role": "system", "content": system}] if system else []) + messages
        payload: dict[str, Any] = {"model": self.model, "messages": msgs,
                                   "max_tokens": max_tokens, "stream": False}
        honoured = {}
        for k, v in (sampling or {}).items():
            if k.startswith("_"):
                continue
            payload[k] = v
            honoured[k] = v
        if self.seed_param:
            payload[self.seed_param] = seed
            honoured["seed"] = seed
        data = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        last_err: Exception | None = None
        for attempt in range(self.retries):
            t0 = time.time()
            try:
                req = urllib.request.Request(f"{self.base_url}/chat/completions",
                                             data=data, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = json.loads(resp.read())
                text = body["choices"][0]["message"]["content"] or ""
                usage = body.get("usage", {}) or {}
                return GenResult(text=text, seed=seed,
                                 tokens=usage.get("completion_tokens", len(text.split())),
                                 latency_ms=int((time.time() - t0) * 1000),
                                 prompt_tokens=usage.get("prompt_tokens", 0),
                                 honoured=honoured)
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "replace")[:400]
                except Exception:
                    pass
                last_err = RuntimeError(f"HTTP {e.code}: {detail}")
                if e.code == 400 and "thinking" in detail.lower() and "thinkingConfig" in gen_cfg:
                    gen_cfg.pop("thinkingConfig")        # model without thinking: retry plainly
                    continue
                if e.code in (400, 401, 403, 404):
                    break
            except (urllib.error.URLError, TimeoutError, OSError, KeyError,
                    json.JSONDecodeError) as e:
                last_err = e
            time.sleep(min(30.0, 2.0 ** attempt))
        return GenResult(text="", seed=seed, error=f"{self.name}: {last_err!r}",
                         honoured=honoured)


# ---------------------------------------------------------------------------
# Anthropic (official SDK)
# ---------------------------------------------------------------------------

class AnthropicAdapter(ModelAdapter):
    """Current Claude models run adaptive thinking by default and reject
    sampling parameters, so `temperature` and seeds are not sent. The k samples
    of a step are therefore independent draws by the model's own randomness,
    which `honoured` records as `seed: None`."""

    def __init__(self, name: str, model: str, api_key: str | None):
        import anthropic
        self.name = name
        self.model = model
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    def describe(self) -> dict:
        return {"name": self.name, "model": self.model}

    def generate(self, messages, seed, max_tokens, sampling=None, system=None) -> GenResult:
        import anthropic
        t0 = time.time()
        kwargs: dict[str, Any] = {"model": self.model, "max_tokens": max_tokens,
                                  "messages": messages}
        if system:
            kwargs["system"] = system
        try:
            resp = self.client.messages.create(**kwargs)
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            return GenResult(text="", seed=seed, error=f"{self.name}: {e!r}",
                             honoured={"seed": None})
        if getattr(resp, "stop_reason", None) == "refusal":
            return GenResult(text="", seed=seed, error=f"{self.name}: refusal",
                             honoured={"seed": None})
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        u = getattr(resp, "usage", None)
        return GenResult(text=text, seed=seed,
                         tokens=getattr(u, "output_tokens", 0) if u else 0,
                         latency_ms=int((time.time() - t0) * 1000),
                         prompt_tokens=getattr(u, "input_tokens", 0) if u else 0,
                         honoured={"seed": None})


# ---------------------------------------------------------------------------
# Gemini (REST generateContent)
# ---------------------------------------------------------------------------

class GeminiAdapter(ModelAdapter):
    BASE = "https://generativelanguage.googleapis.com/v1beta/models"
    quota = None            # DailyQuota, attached by the orchestrator (free tier cap)
    no_thinking = True      # disable hidden reasoning; see generate()

    def __init__(self, name: str, model: str, api_key: str, timeout: int = 600,
                 retries: int = 3):
        self.name = name
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.retries = retries

    def describe(self) -> dict:
        return {"name": self.name, "model": self.model}

    def generate(self, messages, seed, max_tokens, sampling=None, system=None) -> GenResult:
        contents = [{"role": "model" if m["role"] == "assistant" else "user",
                     "parts": [{"text": m["content"]}]} for m in messages]
        gen_cfg: dict[str, Any] = {"maxOutputTokens": max_tokens, "seed": seed}
        honoured = {"seed": seed}
        s = sampling or {}
        if "temperature" in s:
            gen_cfg["temperature"] = s["temperature"]
            honoured["temperature"] = s["temperature"]
        if "top_p" in s:
            gen_cfg["topP"] = s["top_p"]
            honoured["top_p"] = s["top_p"]
        # Thinking models (gemini-2.5+/3.x) spend the output budget on hidden
        # reasoning and return a truncated sentence. B never needs to think.
        if self.no_thinking:
            gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}
        payload: dict[str, Any] = {"contents": contents, "generationConfig": gen_cfg}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        url = f"{self.BASE}/{self.model}:generateContent"
        headers = {"Content-Type": "application/json", "x-goog-api-key": self.api_key}
        last_err: Exception | None = None
        for attempt in range(self.retries):
            data = json.dumps(payload).encode()
            t0 = time.time()
            if self.quota is not None:
                self.quota.record()          # every attempt counts against the day
            try:
                req = urllib.request.Request(url, data=data, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = json.loads(resp.read())
                cands = body.get("candidates") or []
                parts = (cands[0].get("content", {}).get("parts", []) if cands else [])
                text = "".join(p.get("text", "") for p in parts)
                usage = body.get("usageMetadata", {}) or {}
                return GenResult(text=text, seed=seed,
                                 tokens=usage.get("candidatesTokenCount", len(text.split())),
                                 latency_ms=int((time.time() - t0) * 1000),
                                 prompt_tokens=usage.get("promptTokenCount", 0),
                                 honoured=honoured)
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "replace")[:400]
                except Exception:
                    pass
                last_err = RuntimeError(f"HTTP {e.code}: {detail}")
                if e.code == 400 and "thinking" in detail.lower() and "thinkingConfig" in gen_cfg:
                    gen_cfg.pop("thinkingConfig")        # model without thinking: retry plainly
                    continue
                if e.code in (400, 401, 403, 404):
                    break
            except (urllib.error.URLError, TimeoutError, OSError, KeyError,
                    json.JSONDecodeError) as e:
                last_err = e
            time.sleep(min(30.0, 2.0 ** attempt))
        return GenResult(text="", seed=seed, error=f"{self.name}: {last_err!r}",
                         honoured=honoured)
