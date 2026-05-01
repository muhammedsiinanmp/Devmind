from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import pytest
from django.test import RequestFactory

from apps.repositories.exceptions import WebhookVerificationError
from apps.repositories.tests.factories import RepositoryFactory
from apps.repositories.webhooks import (
    WebhookDispatcher,
    verify_webhook_signature,
)

WEBHOOK_SECRET = "test-webhook-secret-32-chars-here"


def _make_signed_request(
    factory: RequestFactory,
    payload: dict[str, Any],
    secret: str = WEBHOOK_SECRET,
    event_type: str = "pull_request",
) -> Any:
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return factory.post(
        "/api/v1/webhooks/github/",
        data=body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=signature,
        HTTP_X_GITHUB_EVENT=event_type,
    )


@pytest.fixture
def rf() -> RequestFactory:
    return RequestFactory()


@pytest.fixture
def pr_opened_payload() -> dict[str, Any]:
    return {
        "action": "opened",
        "number": 42,
        "pull_request": {
            "number": 42,
            "title": "feat: add new endpoint",
            "head": {"sha": "a" * 40},
            "base": {"sha": "b" * 40},
            "diff_url": "https://github.com/acme/api/pull/42.diff",
        },
        "repository": {
            "id": 123456789,
            "full_name": "acme/api",
        },
    }


class TestVerifyWebhookSignature:
    def test_valid_signature_passes(
        self, rf: RequestFactory, pr_opened_payload: dict[str, Any], settings: Any
    ) -> None:
        settings.GITHUB_WEBHOOK_SECRET = WEBHOOK_SECRET
        request = _make_signed_request(rf, pr_opened_payload)
        # Should not raise
        verify_webhook_signature(request)

    def test_tampered_body_raises(
        self, rf: RequestFactory, pr_opened_payload: dict[str, Any], settings: Any
    ) -> None:
        settings.GITHUB_WEBHOOK_SECRET = WEBHOOK_SECRET
        request = _make_signed_request(rf, pr_opened_payload)
        # Overwrite Django's cached body to simulate tampering
        request._body = b'{"action": "malicious"}'
        with pytest.raises(WebhookVerificationError):
            verify_webhook_signature(request)

    def test_missing_signature_header_raises(
        self, rf: RequestFactory, pr_opened_payload: dict[str, Any]
    ) -> None:
        body = json.dumps(pr_opened_payload).encode()
        request = rf.post(
            "/api/v1/webhooks/github/",
            data=body,
            content_type="application/json",
            # No HTTP_X_HUB_SIGNATURE_256
        )
        with pytest.raises(WebhookVerificationError):
            verify_webhook_signature(request)

    def test_wrong_secret_raises(
        self, rf: RequestFactory, pr_opened_payload: dict[str, Any], settings: Any
    ) -> None:
        settings.GITHUB_WEBHOOK_SECRET = WEBHOOK_SECRET
        # Signed with wrong secret
        request = _make_signed_request(rf, pr_opened_payload, secret="wrong-secret")
        with pytest.raises(WebhookVerificationError):
            verify_webhook_signature(request)

    def test_malformed_signature_format_raises(
        self, rf: RequestFactory, settings: Any
    ) -> None:
        settings.GITHUB_WEBHOOK_SECRET = WEBHOOK_SECRET
        body = b'{"action": "opened"}'
        request = rf.post(
            "/api/v1/webhooks/github/",
            data=body,
            content_type="application/json",
            HTTP_X_HUB_SIGNATURE_256="not-sha256-format",
        )
        with pytest.raises(WebhookVerificationError):
            verify_webhook_signature(request)


@pytest.mark.django_db
class TestWebhookDispatcher:
    def test_pr_opened_creates_celery_task(
        self,
        rf: RequestFactory,
        pr_opened_payload: dict[str, Any],
        settings: Any,
        mocker: Any,
    ) -> None:
        settings.GITHUB_WEBHOOK_SECRET = WEBHOOK_SECRET
        RepositoryFactory(github_id=123456789, full_name="acme/api")
        mock_task = mocker.patch("apps.repositories.webhooks.trigger_review_task.delay")
        dispatcher = WebhookDispatcher()
        dispatcher.dispatch(pr_opened_payload, event_type="pull_request")
        mock_task.assert_called_once()

    def test_pr_closed_action_is_ignored(
        self,
        rf: RequestFactory,
        pr_opened_payload: dict[str, Any],
        mocker: Any,
    ) -> None:
        payload = {**pr_opened_payload, **{"action": "closed"}}
        mock_task = mocker.patch("apps.repositories.webhooks.trigger_review_task.delay")
        dispatcher = WebhookDispatcher()
        dispatcher.dispatch(payload, event_type="pull_request")
        mock_task.assert_not_called()

    def test_push_event_is_silently_ignored(
        self,
        pr_opened_payload: dict[str, Any],
        mocker: Any,
    ) -> None:
        mock_task = mocker.patch("apps.repositories.webhooks.trigger_review_task.delay")
        dispatcher = WebhookDispatcher()
        dispatcher.dispatch(pr_opened_payload, event_type="push")
        mock_task.assert_not_called()

    def test_unknown_repo_logs_warning_and_skips(
        self,
        pr_opened_payload: dict[str, Any],
        mocker: Any,
    ) -> None:
        mock_task = mocker.patch("apps.repositories.webhooks.trigger_review_task.delay")
        # No RepositoryFactory call — repo doesn't exist in DB
        dispatcher = WebhookDispatcher()
        dispatcher.dispatch(pr_opened_payload, event_type="pull_request")
        mock_task.assert_not_called()

    def test_ping_event_is_handled(self, mocker: Any) -> None:
        dispatcher = WebhookDispatcher()
        # Should not raise — ping is a no-op
        dispatcher.dispatch({}, event_type="ping")

    def test_review_disabled_skips(
        self,
        pr_opened_payload: dict[str, Any],
        mocker: Any,
    ) -> None:
        RepositoryFactory(
            github_id=123456789, full_name="acme/api", review_enabled=False
        )
        mock_task = mocker.patch("apps.repositories.webhooks.trigger_review_task.delay")
        dispatcher = WebhookDispatcher()
        dispatcher.dispatch(pr_opened_payload, event_type="pull_request")
        mock_task.assert_not_called()

    def test_invalid_repository_payload_skips(self, mocker: Any) -> None:
        payload = {
            "action": "opened",
            "number": 1,
            "repository": "not-a-dict",
            "pull_request": {"number": 1, "head": {"sha": "a" * 40}},
        }
        mock_task = mocker.patch("apps.repositories.webhooks.trigger_review_task.delay")
        dispatcher = WebhookDispatcher()
        dispatcher.dispatch(payload, event_type="pull_request")
        mock_task.assert_not_called()

    def test_invalid_pr_payload_skips(self, mocker: Any) -> None:
        RepositoryFactory(github_id=123456789, full_name="acme/api")
        payload = {
            "action": "opened",
            "number": 1,
            "repository": {"id": 123456789, "full_name": "acme/api"},
            "pull_request": "not-a-dict",
        }
        mock_task = mocker.patch("apps.repositories.webhooks.trigger_review_task.delay")
        dispatcher = WebhookDispatcher()
        dispatcher.dispatch(payload, event_type="pull_request")
        mock_task.assert_not_called()
