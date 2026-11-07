"""
The embeddings router is internal (called by Django only) and must reject
requests without the shared X-Internal-Secret header.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import get_settings

EMBED_BODY = {
    "repo_full_name": "owner/repo",
    "file_path": "app.py",
    "chunk_text": "def f(): pass",
}

PROTECTED_REQUESTS = [
    ("POST", "/embeddings/store", EMBED_BODY),
    ("POST", "/embeddings/search", {"q": "auth", "repo": "owner/repo"}),
    ("GET", "/embeddings/search?q=auth&repo=owner/repo", None),
    (
        "POST",
        "/feedback/upsert",
        {"comment_id": 1, "repo_full_name": "owner/repo", "signal": None},
    ),
]


def _valid_headers():
    return {"X-Internal-Secret": get_settings().fastapi_internal_secret}


@pytest.mark.asyncio
@pytest.mark.parametrize("method,url,body", PROTECTED_REQUESTS)
async def test_missing_secret_is_rejected(client, method, url, body):
    response = await client.request(method, url, json=body)
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("method,url,body", PROTECTED_REQUESTS)
async def test_wrong_secret_is_rejected(client, method, url, body):
    response = await client.request(
        method, url, json=body, headers={"X-Internal-Secret": "wrong"}
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_embeddings_search_with_secret_succeeds(client):
    with (
        patch("core.database.AsyncSessionLocal") as mock_local,
        patch(
            "routers.embeddings.vector_store.search_similar",
            new=AsyncMock(return_value=[]),
        ),
    ):
        mock_local.return_value.__aenter__.return_value = MagicMock()
        mock_local.return_value.__aexit__.return_value = None
        response = await client.get(
            "/embeddings/search",
            params={"q": "auth", "repo": "owner/repo"},
            headers=_valid_headers(),
        )

    assert response.status_code == 200
    assert response.json() == {"results": []}


def test_empty_configured_secret_rejects_empty_header():
    """An unset server secret must not let a request with an empty header in."""
    import asyncio

    from core import security

    with patch.object(security.settings, "fastapi_internal_secret", ""):
        with pytest.raises(Exception) as exc_info:
            asyncio.run(security.verify_internal_token(""))
    assert exc_info.value.status_code == 403
