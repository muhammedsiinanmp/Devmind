"""
Tests for scripts/providers_check.py (`make providers-check`).

HTTP is mocked with httpx.MockTransport; no provider is contacted.
"""

import httpx
import pytest

from scripts import providers_check

GOOGLE_KEY = "AIzaFAKE-google-key-0123456789"
GROQ_KEY = "gsk_FAKE_groq_key_0123456789"


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
                        {"id": "models/gemini-2.5-flash"},
                        {"id": "openai/gpt-oss-120b"},
                    ]
                },
            )
        status = chat_status.get(host, 200)
        # Echo the auth header back, as a hostile or verbose provider might
        auth = request.headers.get("authorization", "")
        return httpx.Response(status, json={"error": auth, "choices": []})

    return httpx.MockTransport(handler)


def test_reports_each_provider_and_exits_zero_when_one_works(capsys):
    seen: list[httpx.Request] = []
    transport = _transport({"api.groq.com": 404}, seen)

    code = providers_check.main(transport=transport)
    out = capsys.readouterr().out

    assert code == 0
    assert "google" in out and "gemini-2.5-flash" in out
    assert "groq" in out and "openai/gpt-oss-120b" in out
    assert "model_not_found" in out
    assert "Working: google" in out
    # It sent the configured model to each provider
    chat_bodies = [r.content for r in seen if r.url.path.endswith("/chat/completions")]
    assert any(b"gemini-2.5-flash" in b for b in chat_bodies)
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
