"""Provider-agnostic LLM wrapper. Default provider "offline" makes no calls.

Configure with env vars LLM_PROVIDER (offline|anthropic), LLM_MODEL, LLM_API_KEY,
optional LLM_PRICE_IN / LLM_PRICE_OUT (USD per million tokens) for cost logging.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request


def load_env(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


class LLM:
    def __init__(self, provider=None, model=None, api_key=None, timeout=30, retries=3):
        self.provider = (provider or os.getenv("LLM_PROVIDER") or "offline").lower()
        self.model = model or os.getenv("LLM_MODEL", "")
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.timeout, self.retries = timeout, retries
        self.tokens_in = self.tokens_out = self.calls = 0
        self.price_in = float(os.getenv("LLM_PRICE_IN", "0"))
        self.price_out = float(os.getenv("LLM_PRICE_OUT", "0"))

    @property
    def available(self) -> bool:
        return self.provider != "offline" and bool(self.api_key and self.model)

    @property
    def cost_usd(self) -> float:
        return (self.tokens_in * self.price_in + self.tokens_out * self.price_out) / 1e6

    def complete(self, system: str, prompt: str, max_tokens: int = 400):
        """Return text, or None when unavailable/failed (callers must have a fallback)."""
        if not self.available:
            return None
        for attempt in range(self.retries):
            try:
                body = json.dumps({"model": self.model, "max_tokens": max_tokens, "temperature": 0,
                                   "system": system, "messages": [{"role": "user", "content": prompt}]}).encode()
                req = urllib.request.Request("https://api.anthropic.com/v1/messages", body, {
                    "x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    out = json.load(r)
                self.calls += 1
                self.tokens_in += out["usage"]["input_tokens"]
                self.tokens_out += out["usage"]["output_tokens"]
                return "".join(b.get("text", "") for b in out["content"])
            except Exception:
                time.sleep(2 ** attempt * 0.5)
        return None
