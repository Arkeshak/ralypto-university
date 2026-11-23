"""Provider-agnostic LLM wrapper.

Configuration (environment variables, see .env.example):
  LLM_PROVIDER   offline | anthropic | openai      (default: offline -> no calls are made)
  LLM_MODEL      model id, e.g. claude-sonnet-5-5, gpt-4o-mini, qwen2.5-coder
  LLM_API_KEY    key for the provider (not needed for a local OpenAI-compatible server)
  LLM_BASE_URL   optional base URL for OpenAI-compatible servers (e.g. http://localhost:11434/v1 for Ollama)
  LLM_TEMPERATURE  default 0
  LLM_TIMEOUT    seconds per request (default 60)
  LLM_PRICE_IN / LLM_PRICE_OUT  USD per million tokens, for cost logging

Without a provider the wrapper runs in a clearly labelled *deterministic / offline* mode:
`complete()` returns None and every caller has a deterministic fallback. Nothing is ever
mocked to look like a real model answer.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Optional, Type

from pydantic import BaseModel, ValidationError

OFFLINE_LABEL = "deterministic (offline, no LLM)"


def load_env(path: str = ".env") -> None:
    """Minimal .env loader; existing environment variables win."""
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.split(" #")[0].strip())


class LLMError(Exception):
    pass


class LLM:
    """One instance per system run, so token/cost counters are per run."""

    def __init__(self, provider=None, model=None, api_key=None, base_url=None, timeout=None, retries=3,
                 temperature=None, fault: Optional[str] = None):
        self.provider = (provider or os.getenv("LLM_PROVIDER") or "offline").lower().strip()
        self.model = model or os.getenv("LLM_MODEL", "")
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.base_url = (base_url or os.getenv("LLM_BASE_URL", "")).rstrip("/")
        self.timeout = float(timeout or os.getenv("LLM_TIMEOUT", "60"))
        self.retries = retries
        self.temperature = float(temperature if temperature is not None else os.getenv("LLM_TEMPERATURE", "0"))
        self.price_in = float(os.getenv("LLM_PRICE_IN", "0") or 0)
        self.price_out = float(os.getenv("LLM_PRICE_OUT", "0") or 0)
        # fault injection for the benchmark: None | "timeout" | "garbage"
        self.fault = fault
        self._lock = threading.Lock()
        self.tokens_in = self.tokens_out = self.calls = self.failures = self.repairs = 0
        self.latency_s = 0.0

    # ------------------------------------------------------------------ status
    @property
    def available(self) -> bool:
        if self.provider == "anthropic":
            return bool(self.api_key and self.model)
        if self.provider == "openai":
            return bool(self.model and (self.api_key or self.base_url))
        return False

    @property
    def mode(self) -> str:
        return f"llm:{self.provider}/{self.model}" if self.available else OFFLINE_LABEL

    @property
    def cost_usd(self) -> float:
        return (self.tokens_in * self.price_in + self.tokens_out * self.price_out) / 1e6

    def counters(self) -> dict:
        return {"mode": self.mode, "calls": self.calls, "failures": self.failures, "repairs": self.repairs,
                "tokens_in": self.tokens_in, "tokens_out": self.tokens_out,
                "tokens": self.tokens_in + self.tokens_out, "cost_usd": round(self.cost_usd, 6),
                "llm_latency_s": round(self.latency_s, 3)}

    def fork(self, fault: Optional[str] = None) -> "LLM":
        """Fresh counters, same configuration."""
        return LLM(self.provider, self.model, self.api_key, self.base_url, self.timeout, self.retries,
                   self.temperature, fault if fault is not None else self.fault)

    # ------------------------------------------------------------------ transport
    def _request(self, system: str, prompt: str, max_tokens: int) -> tuple[str, int, int]:
        if self.fault == "timeout":
            raise TimeoutError("injected LLM timeout")
        if self.provider == "anthropic":
            url = (self.base_url or "https://api.anthropic.com") + "/v1/messages"
            body = {"model": self.model, "max_tokens": max_tokens, "temperature": self.temperature,
                    "system": system, "messages": [{"role": "user", "content": prompt}]}
            headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                       "content-type": "application/json"}
        else:
            url = (self.base_url or "https://api.openai.com/v1") + "/chat/completions"
            body = {"model": self.model, "max_tokens": max_tokens, "temperature": self.temperature,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
            headers = {"content-type": "application/json"}
            if self.api_key:
                headers["authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, json.dumps(body).encode(), headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            out = json.load(r)
        if self.provider == "anthropic":
            text = "".join(b.get("text", "") for b in out.get("content", []))
            u = out.get("usage", {})
            tin, tout = u.get("input_tokens", 0), u.get("output_tokens", 0)
        else:
            text = out["choices"][0]["message"].get("content") or ""
            u = out.get("usage", {}) or {}
            tin, tout = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
        if self.fault == "garbage":
            text = "<<garbled output>> " + text[::-1]
        return text, tin, tout

    def complete(self, system: str, prompt: str, max_tokens: int = 400) -> Optional[str]:
        """Text, or None when offline or every retry failed. Callers must have a deterministic fallback."""
        if not self.available:
            return None
        for attempt in range(self.retries):
            t0 = time.perf_counter()
            try:
                text, tin, tout = self._request(system, prompt, max_tokens)
                with self._lock:
                    self.calls += 1
                    self.tokens_in += tin
                    self.tokens_out += tout
                    self.latency_s += time.perf_counter() - t0
                return text
            except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError, json.JSONDecodeError):
                with self._lock:
                    self.failures += 1
                    self.latency_s += time.perf_counter() - t0
                if self.fault == "timeout":
                    break  # do not sleep through injected faults
                time.sleep(min(8.0, 0.5 * 2 ** attempt))  # exponential back-off
        return None

    def complete_json(self, system: str, prompt: str, schema: Type[BaseModel], max_tokens: int = 400,
                      max_repairs: int = 2) -> Optional[BaseModel]:
        """Schema-validated output with a bounded repair loop. None if it never validates."""
        msg = prompt
        for attempt in range(max_repairs + 1):
            text = self.complete(system + " Reply with one JSON object only.", msg, max_tokens)
            if text is None:
                return None
            try:
                obj = json.loads(text[text.index("{"): text.rindex("}") + 1])
                return schema.model_validate(obj)
            except (ValueError, ValidationError) as e:
                if attempt < max_repairs:
                    with self._lock:
                        self.repairs += 1
                    msg = (f"{prompt}\n\nYour previous reply was invalid ({str(e)[:200]}). "
                           f"Return JSON matching this schema: {json.dumps(schema.model_json_schema())}")
        return None
