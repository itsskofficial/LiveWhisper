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


# Groq retired its Llama models; composing on the old default returned 404.
# The larger gpt-oss writes better, and composing is not on the dictation path.
GROQ_WRITER = "openai/gpt-oss-120b"


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
    # Groq's Cloudflare refuses Python's default user agent (error 1010).
    req.add_header("User-Agent", "LiveWhisper")
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

    def __init__(self, model: str | None = None, host: str = "http://127.0.0.1:11434",
                 keep_alive: str | int = 0):
        self.model = model or self.default_model
        self.host = loopback(host)
        self.keep_alive = keep_alive

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
            # Unload as soon as the text is written. A 7B writing model left
            # resident for Ollama's default half hour held 6 GB of an 8 GB card,
            # the speech models spilled into system memory, and every dictation
            # in that half hour took 12-40 s instead of 1-2. The next Ctrl+Alt+W
            # pays a few seconds to reload; dictation never pays anything.
            "keep_alive": self.keep_alive,
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


class Builtin:
    """The writing model on the app's own runner (livewhisper.llm)."""

    name = "builtin"

    def available(self) -> bool:
        from . import llm
        return llm.server("writer").available()

    def chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        from . import llm
        server = llm.server("writer")
        try:
            return server.chat([{"role": "system", "content": system},
                                {"role": "user", "content": user}],
                               max_tokens=1500, temperature=temperature)
        except llm.LLMError as e:
            raise ProviderError(str(e)) from e
        finally:
            # Unloaded as soon as it has written, for the reason given at
            # Ollama.keep_alive: dictation needs that GPU memory.
            server.stop()


class Chain:
    """The first provider that answers."""

    def __init__(self, *providers):
        self.providers = providers
        self.name = providers[0].name
        self.model = getattr(providers[0], "model", None)

    def available(self) -> bool:
        return any(p.available() for p in self.providers)

    def chat(self, system: str, user: str, temperature: float = 0.3) -> str:
        error = None
        for p in self.providers:
            try:
                return p.chat(system, user, temperature)
            except ProviderError as e:
                error = e
                log.warning("%s could not write (%s); trying the next", p.name, e)
        raise error


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
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "temperature": temperature,
        }
        if self.name == "groq":
            from .llm_format import groq_reasoning_off
            payload.update(groq_reasoning_off(self.model, 1500))
        out = _post(self.url, payload, {"Authorization": f"Bearer {key}"})
        text = out["choices"][0]["message"].get("content") or ""
        return re.sub(r"(?s)<think>.*?</think>", "", text).strip()


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
    name = (cfg or {}).get("provider", "auto")
    model = (cfg or {}).get("model")
    if name == "auto":
        name, model = "builtin", None

    def make(n, model=model):
        if n == "builtin":
            return Builtin()
        if n == "ollama":
            return Ollama(model)
        if n == "groq":
            return OpenAICompatible(
                "groq", "https://api.groq.com/openai/v1/chat/completions",
                "GROQ_API_KEY", model or GROQ_WRITER)
        if n == "openai":
            return OpenAICompatible(
                "openai", "https://api.openai.com/v1/chat/completions",
                "OPENAI_API_KEY", model or "gpt-4o")
        if n == "anthropic":
            return Anthropic(model or "claude-sonnet-5")
        raise ProviderError(f"unknown provider {n!r}")

    primary = make(name)
    if primary.available():
        if name != "builtin" and Builtin().available():
            # Online first, this PC's writing model when the cloud is not
            # reachable - the same promise dictation makes.
            return Chain(primary, Builtin())
        return primary

    for alt in ("builtin", "ollama", "groq", "openai", "anthropic"):
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
    if name in ("builtin", "ollama"):
        raise ProviderError(
            "Writing needs its model: download it in LiveWhisper under AI, "
            "or add a Groq key there.")
    raise ProviderError(
        f"{name} is unavailable and no fallback is configured. "
        "Start Ollama, or set an API key.")
