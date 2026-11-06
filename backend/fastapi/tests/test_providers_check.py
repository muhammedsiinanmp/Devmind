"""
Tests for scripts/providers_check.py (`make providers-check`).

HTTP is mocked with httpx.MockTransport; no provider is contacted.
"""

import json

import httpx
import pytest

from scripts import providers_check

GOOGLE_KEY = "AIzaFAKE-google-key-0123456789"
GROQ_KEY = "gsk_FAKE_groq_key_0123456789"
OK_CHOICE = {"message": {"content": "OK"}, "finish_reason": "stop"}


@pytest.fixture(autouse=True)
def fake_keys(monkeypatch):
    from services import llm_client

    monkeypatch.setattr(llm_client.settings, "google_ai_api_key", GOOGLE_KEY)
    monkeypatch.setattr(llm_client.settings, "groq_api_key", GROQ_KEY)


def _transport(chat_status: dict[str, int], seen: list[httpx.Request]):
    """Google lists its model and answers; Groq answers per chat_status."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        host = request.url.host
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "models/gemini-3.6-flash"},
                        {"id": "openai/gpt-oss-120b"},
                    ]
                },
            )
        status = chat_status.get(host, 200)
        # Echo the auth header back, as a hostile or verbose provider might
        auth = request.headers.get("authorization", "")
        return httpx.Response(status, json={"error": auth, "choices": [OK_CHOICE]})

    return httpx.MockTransport(handler)


def test_reports_each_provider_and_exits_zero_when_one_works(capsys):
    seen: list[httpx.Request] = []
    transport = _transport({"api.groq.com": 404}, seen)

    code = providers_check.main(transport=transport)
    out = capsys.readouterr().out

    assert code == 0
    assert "google" in out and "gemini-3.6-flash" in out
    assert "groq" in out and "openai/gpt-oss-120b" in out
    assert "model_not_found" in out
    assert "Working: google" in out
    # It sent the configured model to each provider
    chat_bodies = [r.content for r in seen if r.url.path.endswith("/chat/completions")]
    assert any(b"gemini-3.6-flash" in b for b in chat_bodies)
    assert any(b"openai/gpt-oss-120b" in b for b in chat_bodies)


def test_exits_nonzero_when_no_provider_works(capsys):
    transport = _transport(
        {"generativelanguage.googleapis.com": 429, "api.groq.com": 500}, []
    )

    code = providers_check.main(transport=transport)
    out = capsys.readouterr().out

    assert code == 1
    assert "No provider completed a chat request." in out


def test_exits_nonzero_without_keys(monkeypatch, capsys):
    from services import llm_client

    monkeypatch.setattr(llm_client.settings, "google_ai_api_key", "")
    monkeypatch.setattr(llm_client.settings, "groq_api_key", "")

    assert providers_check.main(transport=_transport({}, [])) == 1
    assert "No server LLM provider has a key set." in capsys.readouterr().out


def test_never_prints_keys(capsys, caplog):
    seen: list[httpx.Request] = []
    transport = _transport({"api.groq.com": 401}, seen)

    with caplog.at_level("DEBUG"):
        providers_check.main(transport=transport)
    captured = capsys.readouterr()
    output = captured.out + captured.err + caplog.text

    # The keys really were sent, so their absence from output is meaningful
    sent = " ".join(r.headers["authorization"] for r in seen)
    for key in (GOOGLE_KEY, GROQ_KEY):
        assert key in sent
        assert key not in output


def test_github_models_is_not_checked(capsys):
    seen: list[httpx.Request] = []

    providers_check.main(transport=_transport({}, seen))

    assert {r.url.host for r in seen} == {
        "generativelanguage.googleapis.com",
        "api.groq.com",
    }
    assert "github" not in capsys.readouterr().out


def _google_404(message: str) -> httpx.MockTransport:
    """Google lists its model but rejects the chat with a 404 and `message`."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200, json={"data": [{"id": "models/gemini-3.6-flash"}]}
            )
        if request.url.host == "generativelanguage.googleapis.com":
            # Google's OpenAI-compatible endpoint wraps the error in a list
            return httpx.Response(
                404, json=[{"error": {"code": 404, "message": message}}]
            )
        return httpx.Response(200, json={"choices": []})

    return httpx.MockTransport(handler)


def test_404_prints_the_providers_error_message(capsys):
    message = (
        "This model models/gemini-3.6-flash is no longer available to new "
        "users. Please update your code to use a newer model."
    )

    providers_check.main(transport=_google_404(message))
    out = capsys.readouterr().out

    google_line = next(line for line in out.splitlines() if "listed" not in line)
    assert "yes" in google_line  # listed, yet the chat fails
    assert "model_not_found" in google_line
    assert f"google error: {message}" in out


def test_404_error_message_is_truncated(capsys):
    providers_check.main(transport=_google_404("x" * 400))
    out = capsys.readouterr().out

    detail = next(line for line in out.splitlines() if "google error:" in line)
    assert detail.endswith("x" * 150 + "...")
    assert "x" * 151 not in detail


def test_404_error_message_never_shows_a_key(capsys):
    # The key straddles the truncation limit, so redaction must come first
    prefix = "y" * (150 - len(GOOGLE_KEY) // 2)

    providers_check.main(transport=_google_404(f"{prefix}{GOOGLE_KEY} tail"))
    out = capsys.readouterr().out

    assert "google error:" in out
    assert GOOGLE_KEY not in out
    assert GOOGLE_KEY[: len(GOOGLE_KEY) // 2] not in out


def _google_replies(choice: dict) -> httpx.MockTransport:
    """Google answers the chat 200 with ``choice``; Groq is down."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200, json={"data": [{"id": "models/gemini-3.6-flash"}]}
            )
        if request.url.host == "generativelanguage.googleapis.com":
            return httpx.Response(200, json={"choices": [choice]})
        return httpx.Response(503, json={})

    return httpx.MockTransport(handler)


@pytest.mark.parametrize(
    ("choice", "status"),
    [
        (
            {"message": {"content": '{"'}, "finish_reason": "length"},
            "warn: truncated (length)",
        ),
        ({"message": {"content": ""}, "finish_reason": "stop"}, "warn: empty reply"),
        ({"message": {"content": None}, "finish_reason": "stop"}, "warn: empty reply"),
        ({"finish_reason": "stop"}, "warn: empty reply"),
    ],
    ids=["cut_by_max_tokens", "empty", "null", "no_message"],
)
def test_a_200_without_a_usable_reply_is_a_warning_not_working(capsys, choice, status):
    code = providers_check.main(transport=_google_replies(choice))
    out = capsys.readouterr().out

    assert code == 1
    assert status in out
    assert "google warning: HTTP 200 but the reply is not usable" in out
    assert "Working:" not in out


def test_a_full_reply_is_ok():
    assert providers_check.main(transport=_google_replies(OK_CHOICE)) == 0


def test_chat_probe_leaves_room_for_reasoning_tokens():
    seen: list[httpx.Request] = []

    providers_check.main(transport=_transport({}, seen))

    chats = [r for r in seen if r.url.path.endswith("/chat/completions")]
    assert chats
    for request in chats:
        assert json.loads(request.content)["max_tokens"] == 256
