"""
Check which server LLM providers and models are reachable.

For each provider in the server failover chain (a provider is in the chain
when its key is set), list the provider's models and send one tiny chat
completion to the configured model. Prints provider, model, whether the
model is listed, the chat result and its latency. Never prints keys or
response bodies. Exits 1 if no provider completes the chat.

Run from backend/fastapi:  uv run python -m scripts.providers_check
(or `make providers-check` from the repo root).
"""

import sys
import time
from dataclasses import dataclass

import httpx

from core.config import get_settings
from services.llm_client import LLMConfig, _init_model_chain, model_ids

PROMPT = [{"role": "user", "content": "Reply with the single word OK."}]


@dataclass
class ProviderResult:
    provider: str
    model: str
    listed: str  # "yes", "no", or an error marker
    chat: str  # "ok", an HTTP status, or an error marker
    latency_ms: int | None

    @property
    def works(self) -> bool:
        return self.chat == "ok"


def check_provider(config: LLMConfig, client: httpx.Client) -> ProviderResult:
    base_url = config.base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {config.api_key}"}

    try:
        response = client.get(f"{base_url}/models", headers=headers)
        if response.status_code == 200:
            listed = "yes" if config.model in model_ids(response.json()) else "no"
        else:
            listed = f"http {response.status_code}"
    except httpx.HTTPError as exc:
        listed = type(exc).__name__

    latency_ms = None
    started = time.perf_counter()
    try:
        response = client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json={"model": config.model, "messages": PROMPT, "max_tokens": 32},
        )
        latency_ms = round((time.perf_counter() - started) * 1000)
        if response.status_code == 200:
            chat = "ok"
        elif response.status_code == 404:
            chat = "http 404 (model_not_found)"
        elif response.status_code == 429:
            chat = "http 429 (rate_limited)"
        else:
            chat = f"http {response.status_code}"
    except httpx.HTTPError as exc:
        chat = type(exc).__name__

    return ProviderResult(config.provider.value, config.model, listed, chat, latency_ms)


def _redact(line: str, secrets: list[str]) -> str:
    # Belt and braces: nothing above formats a key, but never let one out.
    for secret in secrets:
        if secret:
            line = line.replace(secret, "[redacted]")
    return line


def main(transport: httpx.BaseTransport | None = None) -> int:
    settings = get_settings()
    secrets = [
        settings.google_ai_api_key,
        settings.groq_api_key,
        settings.github_token,
    ]

    def emit(line: str) -> None:
        print(_redact(line, secrets))

    chain = _init_model_chain()
    if settings.github_token and not settings.github_models_enabled:
        emit("github: skipped (GITHUB_MODELS_ENABLED is false)")
    if not chain:
        emit("No server LLM provider has a key set.")
        return 1

    with httpx.Client(timeout=30.0, transport=transport) as client:
        results = [check_provider(config, client) for config in chain]

    emit(f"{'provider':<10} {'model':<28} {'listed':<12} {'chat':<28} latency")
    for r in results:
        latency = f"{r.latency_ms} ms" if r.latency_ms is not None else "-"
        emit(f"{r.provider:<10} {r.model:<28} {r.listed:<12} {r.chat:<28} {latency}")

    working = [r.provider for r in results if r.works]
    if working:
        emit(f"Working: {', '.join(working)}")
        return 0
    emit("No provider completed a chat request.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
