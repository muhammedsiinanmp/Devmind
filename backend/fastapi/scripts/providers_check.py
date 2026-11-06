"""
Check which server LLM providers and models are reachable.

For each provider in the server failover chain (a provider is in the chain
when its key is set), list the provider's models and send one tiny chat
completion to the configured model. Prints provider, model, whether the
model is listed, the chat result and its latency. On a 404 it also prints
the first 150 characters of the provider's error message, with keys
redacted. It never prints keys or other response bodies. Exits 1 if no
provider completes the chat.

A 200 only counts as ok when the reply has text and wasn't cut at
max_tokens. Gemini 3.x reasoning tokens count against max_tokens, so a
small limit can return a 200 with an empty or cut-off reply; that is
reported as a warning ("warn: ...") and doesn't count as working.

The chat request is the authoritative check: a model can be listed yet not
usable (Google lists models that are closed to new keys).

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
# Enough for a thinking model's reasoning plus "OK"; with 64, Gemini 3.x was
# seen to return only the first characters of a reply.
CHAT_MAX_TOKENS = 256


@dataclass
class ProviderResult:
    provider: str
    model: str
    listed: str  # "yes", "no", or an error marker
    chat: str  # "ok", an HTTP status, or an error marker
    latency_ms: int | None
    detail: str = ""  # provider's error message for a 404, truncated

    @property
    def works(self) -> bool:
        return self.chat == "ok"


ERROR_DETAIL_CHARS = 150


def _error_message(response: httpx.Response, secrets: list[str]) -> str:
    """The provider's error message: keys redacted, then truncated.

    Handles OpenAI-style ``{"error": {"message": ...}}``, Google's list-wrapped
    variant, a plain ``{"error": "..."}`` and non-JSON bodies. Redaction comes
    before truncation so a key cut at the limit can't slip through partly.
    """
    try:
        body = response.json()
    except ValueError:
        message = response.text
    else:
        if isinstance(body, list) and body:
            body = body[0]
        error = body.get("error", body) if isinstance(body, dict) else body
        if isinstance(error, dict):
            error = error.get("message", error)
        message = str(error)
    message = _redact(" ".join(message.split()), secrets)
    if len(message) > ERROR_DETAIL_CHARS:
        message = message[:ERROR_DETAIL_CHARS] + "..."
    return message


def _reply_status(response: httpx.Response) -> str:
    """``ok`` for a 200 whose reply has text and wasn't cut, else a warning."""
    try:
        choice = response.json()["choices"][0]
        content = (choice.get("message") or {}).get("content") or ""
        finish_reason = choice.get("finish_reason")
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return "warn: no reply in body"
    if finish_reason == "length":
        return "warn: truncated (length)"
    if not str(content).strip():
        return "warn: empty reply"
    return "ok"


def check_provider(
    config: LLMConfig, client: httpx.Client, secrets: list[str]
) -> ProviderResult:
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
    detail = ""
    started = time.perf_counter()
    try:
        response = client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json={
                "model": config.model,
                "messages": PROMPT,
                "max_tokens": CHAT_MAX_TOKENS,
            },
        )
        latency_ms = round((time.perf_counter() - started) * 1000)
        if response.status_code == 200:
            chat = _reply_status(response)
            if chat != "ok":
                detail = (
                    f"HTTP 200 but the reply is not usable at "
                    f"max_tokens={CHAT_MAX_TOKENS}; reasoning tokens count "
                    "against max_tokens"
                )
        elif response.status_code == 404:
            chat = "http 404 (model_not_found)"
            # e.g. a model that is listed but closed to new keys
            detail = _error_message(response, secrets)
        elif response.status_code == 429:
            chat = "http 429 (rate_limited)"
        else:
            chat = f"http {response.status_code}"
    except httpx.HTTPError as exc:
        chat = type(exc).__name__

    return ProviderResult(
        config.provider.value, config.model, listed, chat, latency_ms, detail
    )


def _redact(line: str, secrets: list[str]) -> str:
    # Every printed line goes through this, including provider error text.
    for secret in secrets:
        if secret:
            line = line.replace(secret, "[redacted]")
    return line


def main(transport: httpx.BaseTransport | None = None) -> int:
    settings = get_settings()
    secrets = [settings.google_ai_api_key, settings.groq_api_key]

    def emit(line: str) -> None:
        print(_redact(line, secrets))

    chain = _init_model_chain()
    if not chain:
        emit("No server LLM provider has a key set.")
        return 1

    with httpx.Client(timeout=30.0, transport=transport) as client:
        results = [check_provider(config, client, secrets) for config in chain]

    emit(f"{'provider':<10} {'model':<28} {'listed':<12} {'chat':<28} latency")
    for r in results:
        latency = f"{r.latency_ms} ms" if r.latency_ms is not None else "-"
        emit(f"{r.provider:<10} {r.model:<28} {r.listed:<12} {r.chat:<28} {latency}")
        if r.detail:
            label = "warning" if r.chat.startswith("warn") else "error"
            emit(f"  {r.provider} {label}: {r.detail}")

    working = [r.provider for r in results if r.works]
    if working:
        emit(f"Working: {', '.join(working)}")
        return 0
    emit("No provider completed a chat request.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
