"""Text generation, local first.

Ollama is the default so that composing and grammar work with nothing leaving
the machine. Groq, OpenAI and Anthropic are available when you want speed or
quality and are willing to send the text.

Honest note carried into the UI: local models are genuinely fine for grammar
and short rewrites. For longer composition a frontier model is noticeably
better. Ollama support is a real capability, not parity.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

TIMEOUT = 120


class ProviderError(RuntimeError):
    pass


def _post(url: str, payload: dict, headers: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ProviderError(f"{e.code}: {e.read()[:300].decode('utf-8', 'replace')}")
    except Exception as e:
        raise ProviderError(str(e)) from e


class Ollama:
    name = "ollama"
    default_model = "qwen2.5:7b"

    def __init__(self, model: str | None = None, host: str = "http://localhost:11434"):
        self.model = model or self.default_model
        self.host = host.rstrip("/")

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=3) as r:
                return r.status == 200
        except Exception:
            return False

    def chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        out = _post(f"{self.host}/api/chat", {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "stream": False,
            "options": {"temperature": temperature},
        })
        return (out.get("message") or {}).get("content", "").strip()


class OpenAICompatible:
    """Groq, OpenAI, and anything speaking the same protocol."""

    def __init__(self, name: str, url: str, key_env: str, model: str):
        self.name = name
        self.url = url
        self.key_env = key_env
        self.model = model

    def available(self) -> bool:
        return bool(os.environ.get(self.key_env))

    def chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        key = os.environ.get(self.key_env)
        if not key:
            raise ProviderError(f"{self.key_env} is not set")
        out = _post(self.url, {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature,
        }, {"Authorization": f"Bearer {key}"})
        return out["choices"][0]["message"]["content"].strip()


class Anthropic:
    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-5"):
        self.model = model

    def available(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    def chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ProviderError("ANTHROPIC_API_KEY is not set")
        out = _post("https://api.anthropic.com/v1/messages", {
            "model": self.model,
            "max_tokens": 1500,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "temperature": temperature,
        }, {"x-api-key": key, "anthropic-version": "2023-06-01"})
        return "".join(b.get("text", "") for b in out.get("content", [])).strip()


def build(cfg: dict):
    """Construct the configured provider, falling back to whatever works."""
    name = (cfg or {}).get("provider", "ollama")
    model = (cfg or {}).get("model")

    def make(n):
        if n == "ollama":
            return Ollama(model)
        if n == "groq":
            return OpenAICompatible(
                "groq", "https://api.groq.com/openai/v1/chat/completions",
                "GROQ_API_KEY", model or "llama-3.3-70b-versatile")
        if n == "openai":
            return OpenAICompatible(
                "openai", "https://api.openai.com/v1/chat/completions",
                "OPENAI_API_KEY", model or "gpt-4o")
        if n == "anthropic":
            return Anthropic(model or "claude-sonnet-5")
        raise ProviderError(f"unknown provider {n!r}")

    primary = make(name)
    if primary.available():
        return primary

    for alt in ("ollama", "groq", "openai", "anthropic"):
        if alt == name:
            continue
        try:
            p = make(alt)
            if p.available():
                log.warning("%s unavailable, using %s", name, alt)
                return p
        except ProviderError:
            continue
    raise ProviderError(
        f"{name} is unavailable and no fallback is configured. "
        "Start Ollama, or set an API key.")
