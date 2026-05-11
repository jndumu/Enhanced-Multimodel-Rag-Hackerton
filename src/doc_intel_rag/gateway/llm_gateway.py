"""LLM Gateway — Bifrost-style provider routing with automatic fallback.

Routes requests across multiple OpenAI-compatible providers in priority order.
If the primary provider returns 429 (rate limit), 503 (unavailable), or times out,
the gateway retries the next provider transparently — the caller never sees the failure.

Provider priority (configured via LLM_GATEWAY_PROVIDERS env var, comma-separated):
  1. Requesty   — primary (multi-provider aggregator)
  2. Fireworks  — secondary (fast, cheap)
  3. Novita     — tertiary (broad model support)

Each provider entry: base_url|api_key_env|model_prefix
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx
from loguru import logger


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str
    healthy: bool = True
    failures: int = 0
    last_failure: float = 0.0
    # After 3 failures, back off for 60 seconds before retrying
    _BACKOFF_SECS: float = 60.0
    _MAX_FAILURES: int = 3

    def is_available(self) -> bool:
        if self.healthy:
            return True
        # Allow retry after backoff window
        if time.monotonic() - self.last_failure > self._BACKOFF_SECS:
            self.healthy = True
            self.failures = 0
            return True
        return False

    def mark_failure(self) -> None:
        self.failures += 1
        self.last_failure = time.monotonic()
        if self.failures >= self._MAX_FAILURES:
            self.healthy = False
            logger.warning("LLM Gateway: provider marked unhealthy", provider=self.name)

    def mark_success(self) -> None:
        self.failures = 0
        self.healthy = True


@dataclass
class LLMGateway:
    """Bifrost-style gateway that fans out across providers with automatic failover.

    Usage::

        gw = LLMGateway.from_env()
        response = await gw.chat(model="alibaba/qwen-turbo", messages=[...])
        embedding = await gw.embed(model="openai/text-embedding-3-small", texts=[...])
    """

    providers: list[ProviderConfig] = field(default_factory=list)
    timeout: float = 60.0

    @classmethod
    def from_env(cls) -> "LLMGateway":
        """Build gateway from environment variables.

        Reads LLM_GATEWAY_PROVIDERS (pipe-separated provider specs) or falls
        back to the single Mesh API provider from MESH_* variables.
        """
        providers: list[ProviderConfig] = []

        raw = os.getenv("LLM_GATEWAY_PROVIDERS", "")
        if raw:
            for spec in raw.split(","):
                parts = spec.strip().split("|")
                if len(parts) == 3:
                    name, base_url, key_env = parts
                    key = os.getenv(key_env, "")
                    if key:
                        providers.append(ProviderConfig(name=name, base_url=base_url.rstrip("/"), api_key=key))

        # Always include the primary Mesh/Requesty provider
        mesh_key = os.getenv("MESH_API_KEY", "")
        mesh_url = os.getenv("MESH_API_BASE_URL", "https://router.requesty.ai/v1").rstrip("/")
        if mesh_key and not any(p.base_url == mesh_url for p in providers):
            providers.insert(0, ProviderConfig(name="requesty", base_url=mesh_url, api_key=mesh_key))

        if not providers:
            raise RuntimeError("LLM Gateway: no providers configured — set MESH_API_KEY")

        logger.info("LLM Gateway initialised", providers=[p.name for p in providers])
        return cls(providers=providers)

    def _available_providers(self) -> list[ProviderConfig]:
        return [p for p in self.providers if p.is_available()]

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 1024,
        temperature: float = 0.2,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a chat completion request, failing over across providers."""
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
            **kwargs,
        }
        last_error: Exception | None = None

        for provider in self._available_providers():
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    r = await client.post(
                        f"{provider.base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {provider.api_key}"},
                        json=payload,
                    )
                if r.status_code in (429, 503, 502, 504):
                    provider.mark_failure()
                    logger.warning(
                        "LLM Gateway: provider returned error, trying next",
                        provider=provider.name, status=r.status_code,
                    )
                    continue
                r.raise_for_status()
                provider.mark_success()
                logger.debug("LLM Gateway: chat routed", provider=provider.name, model=model)
                return r.json()
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                provider.mark_failure()
                last_error = exc
                logger.warning(
                    "LLM Gateway: provider timeout/connect error",
                    provider=provider.name, error=str(exc),
                )
                continue

        raise RuntimeError(
            f"LLM Gateway: all providers exhausted. Last error: {last_error}"
        )

    async def embed(
        self,
        model: str,
        texts: list[str],
    ) -> list[list[float]]:
        """Get embeddings, failing over across providers."""
        payload = {"model": model, "input": texts}
        last_error: Exception | None = None

        for provider in self._available_providers():
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    r = await client.post(
                        f"{provider.base_url}/embeddings",
                        headers={"Authorization": f"Bearer {provider.api_key}"},
                        json=payload,
                    )
                if r.status_code in (429, 503, 502, 504):
                    provider.mark_failure()
                    continue
                r.raise_for_status()
                provider.mark_success()
                data = r.json()
                return [item["embedding"] for item in data["data"]]
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                provider.mark_failure()
                last_error = exc
                continue

        raise RuntimeError(
            f"LLM Gateway: all providers exhausted for embeddings. Last error: {last_error}"
        )

    async def health(self) -> dict[str, Any]:
        """Return health status of all configured providers."""
        results: dict[str, Any] = {}
        for p in self.providers:
            results[p.name] = {
                "healthy": p.healthy,
                "failures": p.failures,
                "available": p.is_available(),
                "base_url": p.base_url,
            }
        return results


# Module-level singleton — initialised lazily
_gateway: LLMGateway | None = None


def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway.from_env()
    return _gateway
