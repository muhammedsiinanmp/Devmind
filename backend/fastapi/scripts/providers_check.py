"""
Check which server LLM providers and models are reachable.

For each provider in the server failover chain (a provider is in the chain
when its key is set), list the provider's models and send one short chat
completion (CHAT_MAX_TOKENS) to the configured model. Prints provider,
model, whether the model is listed, the chat result and its latency. On a
404 it also prints
the first 150 characters of the provider's error message, with keys
redacted. It never prints keys or other response bodies. Exits 1 if no
provider completes the chat.

A 200 only counts as ok when the reply has text and wasn't cut at
max_tokens. Gemini 3.x reasoning tokens count against max_tokens, so a
small limit can return a 200 with an empty or cut-off reply; that is
reported as a warning ("warn: ...") and doesn't count as working.

The chat request is the authoritative check: a model can be listed yet not
usable (Google lists models that are closed to new keys).

When GOOGLE_AI_API_KEY is set it also embeds one short text through
VectorStore, the code path reviews use, and prints the embedding model, HTTP
status, returned dimension against the expected one, and latency. A failed
embedding check (any error, or a dimension other than VectorStore's
embedding_dims) also makes it exit 1. On 2026-11-06 the API accepted a
request shape that it then didn't apply, returning 3072 values instead of
768, so the dimension is checked, not just the status.

Run from backend/fastapi:  uv run python -m scripts.providers_check
(or `make providers-check` from the repo root).
"""

import asyncio
import sys
import time
from dataclasses import dataclass

import httpx

from core.config import get_settings
from services.llm_client import LLMConfig, _init_model_chain, model_ids
from services.vector_store import VectorStore, VectorStoreError

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


EMBED_TEXT = "def add(a, b): return a + b"


@dataclass
class EmbeddingResult:
    model: str
    status: str  # "http 200", another HTTP status, or an error marker
    dims: int | None  # length of the first returned vector
    expected_dims: int
    latency_ms: int | None
    result: str  # "ok", "dimension mismatch", or why it failed

    @property
    def works(self) -> bool:
        return self.result == "ok"


async def _check_embedding(transport) -> EmbeddingResult:
    """One batchEmbedContents call with one text, through VectorStore."""
    store = VectorStore()
    seen: dict = {}

    async def record(response: httpx.Response) -> None:
        # Status and returned dimension, read before VectorStore's own
        # dimension check can raise.
        await response.aread()
        seen["status"] = response.status_code
        if response.status_code != 200:
            return
        try:
            embeddings = response.json().get("embeddings")
            seen["dims"] = len(embeddings[0]["values"])
        except (ValueError, AttributeError, TypeError, IndexError, KeyError):
            pass

    store._client = httpx.AsyncClient(
        timeout=30.0, transport=transport, event_hooks={"response": [record]}
    )
    latency_ms = None
    started = time.perf_counter()
    try:
        await store.generate_embeddings(
            [EMBED_TEXT], use_cache=False, task_type="RETRIEVAL_QUERY"
        )
        result = "ok"
    except VectorStoreError:
        if seen.get("dims") not in (None, store.embedding_dims):
            result = "dimension mismatch"
        else:
            result = "failed"
    except httpx.HTTPError as exc:
        result = type(exc).__name__
    finally:
        latency_ms = round((time.perf_counter() - started) * 1000)
        await store.aclose()

    status = seen.get("status")
    return EmbeddingResult(
        model=store.embedding_model,
        status=f"http {status}" if status is not None else "-",
        dims=seen.get("dims"),
        expected_dims=store.embedding_dims,
        latency_ms=latency_ms,
        result=result,
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

    embedding = None
    if settings.google_ai_api_key:
        embedding = asyncio.run(_check_embedding(transport))

    emit(f"{'provider':<10} {'model':<28} {'listed':<12} {'chat':<28} latency")
    for r in results:
        latency = f"{r.latency_ms} ms" if r.latency_ms is not None else "-"
        emit(f"{r.provider:<10} {r.model:<28} {r.listed:<12} {r.chat:<28} {latency}")
        if r.detail:
            label = "warning" if r.chat.startswith("warn") else "error"
            emit(f"  {r.provider} {label}: {r.detail}")

    emit("")
    if embedding is None:
        emit("Embedding check skipped: GOOGLE_AI_API_KEY is not set.")
    else:
        e = embedding
        dims = f"{e.dims if e.dims is not None else '-'}/{e.expected_dims}"
        latency = f"{e.latency_ms} ms" if e.latency_ms is not None else "-"
        emit(
            f"{'embedding model':<28} {'status':<10} {'dims':<10} {'latency':<10} result"
        )
        emit(f"{e.model:<28} {e.status:<10} {dims:<10} {latency:<10} {e.result}")
        if not e.works:
            emit(
                f"EMBEDDING CHECK FAILED: {e.result} (got {e.dims} values, "
                f"expected {e.expected_dims}). Retrieval would stop working."
                if e.result == "dimension mismatch"
                else f"EMBEDDING CHECK FAILED: {e.result} ({e.status})."
            )

    code = 0
    working = [r.provider for r in results if r.works]
    if working:
        emit(f"Working: {', '.join(working)}")
    else:
        emit("No provider completed a chat request.")
        code = 1
    if embedding is not None and not embedding.works:
        code = 1
    return code


if __name__ == "__main__":
    sys.exit(main())
