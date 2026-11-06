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


def _embed_response(request: httpx.Request, dims: int) -> httpx.Response:
    import json

    texts = json.loads(request.content)["requests"]
    return httpx.Response(
        200, json={"embeddings": [{"values": [0.1] * dims} for _ in texts]}
    )


def _transport(
    chat_status: dict[str, int], seen: list[httpx.Request], embed_dims: int = 768
):
    """Google lists its model and answers; Groq answers per chat_status.
    batchEmbedContents returns vectors of embed_dims values."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        host = request.url.host
        if request.url.path.endswith(":batchEmbedContents"):
            return _embed_response(request, embed_dims)
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "models/gemini-3.5-flash"},
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
    assert "google" in out and "gemini-3.5-flash" in out
    assert "groq" in out and "openai/gpt-oss-120b" in out
    assert "model_not_found" in out
    assert "Working: google" in out
    # It sent the configured model to each provider
    chat_bodies = [r.content for r in seen if r.url.path.endswith("/chat/completions")]
    assert any(b"gemini-3.5-flash" in b for b in chat_bodies)
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

    # The keys really were sent, so their absence from output is meaningful.
    # The embedding call sends the Google key in x-goog-api-key.
    sent = " ".join(r.headers.get("authorization", "") for r in seen)
    embed_keys = [
        r.headers["x-goog-api-key"]
        for r in seen
        if r.url.path.endswith(":batchEmbedContents")
    ]
    assert embed_keys == [GOOGLE_KEY]
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
        if request.url.path.endswith(":batchEmbedContents"):
            return _embed_response(request, 768)
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200, json={"data": [{"id": "models/gemini-3.5-flash"}]}
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
        "This model models/gemini-3.5-flash is no longer available to new "
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


def _embedding_lines(out: str) -> list[str]:
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if "embedding model" in line)
    return lines[start : start + 3]


def test_embedding_check_reports_768_dimensions_as_ok(capsys):
    seen: list[httpx.Request] = []

    code = providers_check.main(transport=_transport({}, seen))
    out = capsys.readouterr().out

    assert code == 0
    model, _, status, dims, latency, unit, result = _embedding_lines(out)[1].split()
    assert (model, status, dims, unit, result) == (
        "gemini-embedding-001",
        "200",
        "768/768",
        "ms",
        "ok",
    )
    assert latency.isdigit()
    assert "EMBEDDING CHECK FAILED" not in out
    # One request, through VectorStore's batchEmbedContents call
    [embed] = [r for r in seen if r.url.path.endswith(":batchEmbedContents")]
    assert embed.url.path == "/v1beta/models/gemini-embedding-001:batchEmbedContents"


def test_embedding_dimension_mismatch_fails_the_check(capsys):
    # e.g. the API ignoring outputDimensionality and returning 3072 values
    code = providers_check.main(transport=_transport({}, [], embed_dims=3072))
    out = capsys.readouterr().out

    assert code == 1
    row = _embedding_lines(out)[1]
    assert "http 200" in row
    assert "3072/768" in row
    assert row.endswith("dimension mismatch")
    assert "EMBEDDING CHECK FAILED: dimension mismatch (got 3072" in out
    # The chat providers still worked; only the embedding check failed
    assert "Working: google, groq" in out


def test_embedding_http_error_fails_the_check(capsys):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(":batchEmbedContents"):
            return httpx.Response(400, json={"error": {"message": GOOGLE_KEY}})
        return _transport({}, []).handler(request)

    code = providers_check.main(transport=httpx.MockTransport(handler))
    out = capsys.readouterr().out

    assert code == 1
    assert "http 400" in _embedding_lines(out)[1]
    assert "EMBEDDING CHECK FAILED: failed (http 400)." in out
    assert GOOGLE_KEY not in out


def test_embedding_check_is_skipped_without_a_google_key(monkeypatch, capsys):
    from services import llm_client

    monkeypatch.setattr(llm_client.settings, "google_ai_api_key", "")
    seen: list[httpx.Request] = []

    code = providers_check.main(transport=_transport({}, seen))
    out = capsys.readouterr().out

    assert code == 0
    assert "Embedding check skipped: GOOGLE_AI_API_KEY is not set." in out
    assert not any(r.url.path.endswith(":batchEmbedContents") for r in seen)
