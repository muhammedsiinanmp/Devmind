from django.contrib.admin.sites import AdminSite

from apps.repositories.admin import RepositoryAdmin
from apps.repositories.models import Repository


def _admin() -> RepositoryAdmin:
    return RepositoryAdmin(Repository, AdminSite())


def test_webhook_status_shows_installed_id() -> None:
    html = _admin().webhook_status(Repository(webhook_id=987654))
    assert "Installed (987654)" in html


def test_webhook_status_shows_not_installed() -> None:
    html = _admin().webhook_status(Repository(webhook_id=None))
    assert "Not installed" in html


def test_webhook_status_escapes_value() -> None:
    # webhook_id is an integer column, but the rendered value must still be
    # escaped rather than trusted as HTML.
    html = _admin().webhook_status(Repository(webhook_id="<script>x</script>"))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
