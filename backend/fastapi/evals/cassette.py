"""
Record and replay model responses for the eval harness.

A cassette is one JSON file per case. It stores, for each model call, the
SHA-256 of the prompt, the response text, the model name and provider the
client reported, and token counts, plus the recording time. It never stores
the prompt itself, request headers or keys. (Cassettes recorded before the
provider and recording time were added still load.)

Replay looks responses up by prompt hash, in call order per hash, so it does
not depend on the order in which the parallel analyzer nodes run. A prompt
with no recorded response raises CassetteMiss: the agent's prompts have
changed and the cassettes must be re-recorded with ``make eval-record``.
"""

import hashlib
import json
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Awaitable, Callable

CASSETTE_VERSION = 1
CALL_KEYS = {
    "prompt_sha256",
    "response",
    "model_used",
    "prompt_tokens",
    "completion_tokens",
}
# Optional keys: absent from cassettes recorded by earlier harness versions.
OPTIONAL_CALL_KEYS = {"provider"}
CASSETTE_KEYS = {"version", "case_id", "case_sha256", "latency_ms", "calls"}
OPTIONAL_CASSETTE_KEYS = {"recorded_utc"}
# Shorter values are too likely to occur by chance in normal text.
_MIN_SECRET_LEN = 8


class CassetteMiss(Exception):
    """No recorded response for this prompt (or the case changed)."""


class SecretInResponse(Exception):
    """A configured secret appeared in a model response; refuse to record."""


def prompt_hash(messages: list[dict[str, Any]], kwargs: dict[str, Any]) -> str:
    payload = json.dumps(
        {"messages": messages, "kwargs": kwargs},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class Recorder:
    """Wraps a live ``generate`` coroutine and keeps what a cassette needs."""

    def __init__(
        self,
        generate: Callable[..., Awaitable[Any]],
        secrets: list[str] | None = None,
    ):
        self._generate = generate
        self._secrets = [s for s in (secrets or []) if len(s) >= _MIN_SECRET_LEN]
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, messages, *, user_id=None, **kwargs):
        response = await self._generate(messages, user_id=user_id, **kwargs)
        content = response.content or ""
        provider = getattr(response, "provider", "")
        if any(secret in content for secret in self._secrets):
            raise SecretInResponse("model response contains a configured secret")
        self.calls.append(
            {
                "prompt_sha256": prompt_hash(messages, kwargs),
                "response": content,
                "model_used": str(response.model_used),
                "prompt_tokens": int(getattr(response, "prompt_tokens", 0) or 0),
                "completion_tokens": int(
                    getattr(response, "completion_tokens", 0) or 0
                ),
                "provider": str(getattr(provider, "value", provider) or ""),
            }
        )
        return response


class Player:
    """Async stand-in for ``llm_client.generate`` backed by recorded calls."""

    def __init__(self, calls: list[dict[str, Any]], make_response: Callable):
        self._queues: dict[str, deque] = defaultdict(deque)
        for call in calls:
            self._queues[call["prompt_sha256"]].append(call)
        self._make_response = make_response
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, messages, *, user_id=None, **kwargs):
        key = prompt_hash(messages, kwargs)
        queue = self._queues.get(key)
        if not queue:
            raise CassetteMiss(
                f"no recorded response for prompt {key[:12]}; "
                "re-record with `make eval-record`"
            )
        call = queue.popleft()
        self.calls.append(call)
        return self._make_response(call)


def _check_call_keys(call: dict, name: str) -> None:
    keys = set(call)
    if not CALL_KEYS <= keys <= CALL_KEYS | OPTIONAL_CALL_KEYS:
        raise ValueError(f"{name}: unexpected cassette call keys {sorted(call)}")


def save_cassette(
    path: Path,
    case_id: str,
    case_sha256: str,
    calls: list[dict[str, Any]],
    latency_ms: int,
    recorded_utc: str | None = None,
) -> None:
    for call in calls:
        _check_call_keys(call, path.name)
    data = {
        "version": CASSETTE_VERSION,
        "case_id": case_id,
        "case_sha256": case_sha256,
        "latency_ms": int(latency_ms),
        "calls": calls,
    }
    if recorded_utc:
        data["recorded_utc"] = recorded_utc
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def load_cassette(path: Path, case_id: str, case_sha256: str) -> dict[str, Any]:
    if not path.exists():
        raise CassetteMiss(f"no cassette for case {case_id!r}")
    data = json.loads(path.read_text())
    keys = set(data)
    if (
        not CASSETTE_KEYS <= keys <= CASSETTE_KEYS | OPTIONAL_CASSETTE_KEYS
        or data.get("version") != CASSETTE_VERSION
    ):
        raise ValueError(f"{path.name}: unsupported cassette format")
    for call in data["calls"]:
        _check_call_keys(call, path.name)
    if data["case_sha256"] != case_sha256:
        raise CassetteMiss(
            f"case {case_id!r} changed since it was recorded; "
            "re-record with `make eval-record`"
        )
    return data
