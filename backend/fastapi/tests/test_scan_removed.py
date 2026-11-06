"""
The regex repository scan was removed (issue #75). Its routes must not exist,
even for a caller holding the internal secret.
"""

import pytest

from core.config import get_settings

REMOVED_ROUTES = [
    ("POST", "/scan/full"),
    ("GET", "/scan/status/1"),
    ("GET", "/scan/report/1"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,url", REMOVED_ROUTES)
async def test_scan_routes_are_gone(client, method, url):
    headers = {"X-Internal-Secret": get_settings().fastapi_internal_secret}
    response = await client.request(method, url, json={}, headers=headers)
    assert response.status_code == 404


def test_scan_routes_absent_from_openapi():
    from main import app

    paths = app.openapi()["paths"]
    assert not [p for p in paths if p.startswith("/scan")]
