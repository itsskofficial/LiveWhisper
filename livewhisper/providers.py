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
import re
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

TIMEOUT = 120


class ProviderError(RuntimeError):
    pass


def loopback(host: str) -> str:
    """Address a local server by IP, never by the name "localhost".

    On Windows "localhost" resolves to the IPv6 address first. Ollama listens
    on IPv4 only, so every request waited for the IPv6 attempt to fail before
    retrying - measured at 2.3 s on every call, for a model that answered in
    0.13 s. Composing and grammar fixes paid it too.
    """
    return re.sub(r"//localhost(?=[:/]|$)", "//127.0.0.1", host.rstrip("/"))


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

    def __init__(self, model: str | None = None, host: str = "http://127.0.0.1:11434"):
        self.model = model or self.default_model
        self.host = loopback(host)

    def available(self) -> bool:
        """Ollama is running AND has this model - a running server without it
        answered every request with "model not found"."""
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=3) as r:
                names = {m.get("name", "") for m in json.loads(r.read()).get("models", [])}
        except Exception:
            return False
        return self.model in names or f"{self.model}:latest" in names

    def chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "stream": False,
            "keep_alive": "30m",
            # The screen (up to 6000 characters) plus the instruction fits in
            # 4096 tokens; the default larger context only costs VRAM that the
            # speech models need.
            "options": {"temperature": temperature, "num_ctx": 4096},
        }
        if self.model.startswith(("qwen3", "deepseek-r1")):
            # Reasoning models think out loud first: seconds of waiting, and
            # the thinking can leak into the text that gets pasted.
            payload["think"] = False
        out = _post(f"{self.host}/api/chat", payload)
        text = (out.get("message") or {}).get("content", "")
        return re.sub(r"(?s)<think>.*?</think>", "", text).strip()


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

    def make(n, model=model):
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
            # Each fallback with its own default model: the configured one
            # belongs to the configured provider - "qwen2.5:7b" sent to Groq
            # is a 404.
            p = make(alt, model=None)
            if p.available():
                log.warning("%s unavailable, using %s", name, alt)
                return p
        except ProviderError:
            continue
    if name == "ollama":
        want = model or Ollama.default_model
        raise ProviderError(
            f"Writing needs a language model. Start Ollama and run "
            f"'ollama pull {want}', or add a GROQ_API_KEY.")
    raise ProviderError(
        f"{name} is unavailable and no fallback is configured. "
        "Start Ollama, or set an API key.")
