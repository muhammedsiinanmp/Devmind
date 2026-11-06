"""
Feedback webhooks (issue #74): pull_request_review_thread,
pull_request_review_comment, and pull_request closed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import pytest
from django.test import Client

from apps.repositories.tests.factories import RepositoryFactory
from apps.repositories.webhooks import WebhookDispatcher

WEBHOOK_SECRET = "test-webhook-secret-32-chars-here"


def _post_signed(
    payload: dict[str, Any], event_type: str, secret: str = WEBHOOK_SECRET
) -> Any:
    """POST a webhook through the real endpoint, signed with ``secret``."""
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return Client().post(
        "/api/v1/webhooks/github/",
        data=body,
        content_type="application/json",
        HTTP_X_HUB_SIGNATURE_256=signature,
        HTTP_X_GITHUB_EVENT=event_type,
    )


@pytest.fixture
def devmind_comment(db: Any) -> Any:
    """A DevMind comment posted on GitHub as review comment 9001."""
    from apps.reviews.tests.factories import ReviewCommentFactory, ReviewFactory

    repo = RepositoryFactory(github_id=123456789, full_name="acme/api")
    review = ReviewFactory(repository=repo, pr_number=42, status="completed")
    return ReviewCommentFactory(review=review, github_comment_id=9001)


def _thread_payload(action: str, comment_ids: list[int]) -> dict[str, Any]:
    return {
        "action": action,
        "thread": {
            "node_id": "PRRT_1",
            "comments": [{"id": comment_id} for comment_id in comment_ids],
        },
        "pull_request": {"number": 42},
        "repository": {"id": 123456789, "full_name": "acme/api"},
    }


def _reply_payload(body: str, in_reply_to_id: int | None = 9001) -> dict[str, Any]:
    comment: dict[str, Any] = {
        "id": 9100,
        "body": body,
        "user": {"login": "dev", "type": "User"},
    }
    if in_reply_to_id is not None:
        comment["in_reply_to_id"] = in_reply_to_id
    return {
        "action": "created",
        "comment": comment,
        "pull_request": {"number": 42},
        "repository": {"id": 123456789, "full_name": "acme/api"},
    }


def _closed_payload(repo_id: int = 123456789) -> dict[str, Any]:
    return {
        "action": "closed",
        "pull_request": {"number": 42, "merged": True},
        "repository": {"id": repo_id, "full_name": "acme/api"},
    }


def _feedback(comment: Any) -> list[tuple[str, str]]:
    return sorted(comment.feedback.values_list("source", "signal"))


FEEDBACK_EVENTS = [
    ("pull_request_review_thread", _thread_payload("resolved", [9001])),
    ("pull_request_review_comment", _reply_payload("False positive")),
]


@pytest.mark.django_db
class TestFeedbackWebhookSignatures:
    """The new events go through the same HMAC check as pull_request."""

    @pytest.mark.parametrize("event_type,payload", FEEDBACK_EVENTS)
    def test_valid_signature_is_accepted_and_recorded(
        self,
        event_type: str,
        payload: dict[str, Any],
        devmind_comment: Any,
        settings: Any,
    ) -> None:
        settings.GITHUB_WEBHOOK_SECRET = WEBHOOK_SECRET

        response = _post_signed(payload, event_type)

        assert response.status_code == 200
        assert devmind_comment.feedback.count() == 1

    @pytest.mark.parametrize("event_type,payload", FEEDBACK_EVENTS)
    def test_wrong_signature_returns_403_and_records_nothing(
        self,
        event_type: str,
        payload: dict[str, Any],
        devmind_comment: Any,
        settings: Any,
    ) -> None:
        settings.GITHUB_WEBHOOK_SECRET = WEBHOOK_SECRET

        response = _post_signed(payload, event_type, secret="attacker-secret")

        assert response.status_code == 403
        assert devmind_comment.feedback.count() == 0

    @pytest.mark.parametrize("event_type,payload", FEEDBACK_EVENTS)
    def test_missing_signature_returns_403_and_records_nothing(
        self,
        event_type: str,
        payload: dict[str, Any],
        devmind_comment: Any,
        settings: Any,
    ) -> None:
        settings.GITHUB_WEBHOOK_SECRET = WEBHOOK_SECRET

        response = Client().post(
            "/api/v1/webhooks/github/",
            data=json.dumps(payload).encode(),
            content_type="application/json",
            HTTP_X_GITHUB_EVENT=event_type,
        )

        assert response.status_code == 403
        assert devmind_comment.feedback.count() == 0

    @pytest.mark.parametrize("event_type,payload", FEEDBACK_EVENTS)
    def test_unset_secret_returns_403_and_records_nothing(
        self,
        event_type: str,
        payload: dict[str, Any],
        devmind_comment: Any,
        settings: Any,
    ) -> None:
        settings.GITHUB_WEBHOOK_SECRET = ""

        response = _post_signed(payload, event_type, secret="")

        assert response.status_code == 403
        assert devmind_comment.feedback.count() == 0

    def test_signed_pr_closed_queues_reaction_fetch(
        self, devmind_comment: Any, settings: Any, mocker: Any
    ) -> None:
        settings.GITHUB_WEBHOOK_SECRET = WEBHOOK_SECRET
        mock_fetch = mocker.patch(
            "apps.repositories.webhooks.fetch_comment_reactions_task"
        )

        response = _post_signed(_closed_payload(), "pull_request")

        assert response.status_code == 200
        mock_fetch.delay.assert_called_once_with(
            repo_id=devmind_comment.review.repository_id, pr_number=42
        )

    def test_wrongly_signed_pr_closed_queues_nothing(
        self, devmind_comment: Any, settings: Any, mocker: Any
    ) -> None:
        settings.GITHUB_WEBHOOK_SECRET = WEBHOOK_SECRET
        mock_fetch = mocker.patch(
            "apps.repositories.webhooks.fetch_comment_reactions_task"
        )

        response = _post_signed(
            _closed_payload(), "pull_request", secret="attacker-secret"
        )

        assert response.status_code == 403
        mock_fetch.delay.assert_not_called()


@pytest.mark.django_db
class TestFeedbackDispatch:
    def test_resolved_thread_is_accepted(self, devmind_comment: Any) -> None:
        WebhookDispatcher().dispatch(
            _thread_payload("resolved", [9001, 9100]), "pull_request_review_thread"
        )
        assert _feedback(devmind_comment) == [("resolved", "accepted")]

    def test_unresolved_thread_removes_the_verdict(self, devmind_comment: Any) -> None:
        dispatcher = WebhookDispatcher()
        dispatcher.dispatch(
            _thread_payload("resolved", [9001]), "pull_request_review_thread"
        )
        dispatcher.dispatch(
            _thread_payload("unresolved", [9001]), "pull_request_review_thread"
        )
        assert _feedback(devmind_comment) == []

    def test_resolving_twice_keeps_one_row(self, devmind_comment: Any) -> None:
        dispatcher = WebhookDispatcher()
        for _ in range(2):
            dispatcher.dispatch(
                _thread_payload("resolved", [9001]), "pull_request_review_thread"
            )
        assert _feedback(devmind_comment) == [("resolved", "accepted")]

    def test_thread_of_another_repository_is_ignored(
        self, devmind_comment: Any
    ) -> None:
        payload = _thread_payload("resolved", [9001])
        payload["repository"] = {"id": 555, "full_name": "evil/repo"}
        WebhookDispatcher().dispatch(payload, "pull_request_review_thread")
        assert _feedback(devmind_comment) == []

    def test_thread_without_devmind_comment_is_ignored(
        self, devmind_comment: Any
    ) -> None:
        WebhookDispatcher().dispatch(
            _thread_payload("resolved", [1, 2]), "pull_request_review_thread"
        )
        assert _feedback(devmind_comment) == []

    def test_thread_of_inactive_repository_is_ignored(
        self, devmind_comment: Any
    ) -> None:
        repo = devmind_comment.review.repository
        repo.is_active = False
        repo.save()
        WebhookDispatcher().dispatch(
            _thread_payload("resolved", [9001]), "pull_request_review_thread"
        )
        assert _feedback(devmind_comment) == []

    @pytest.mark.parametrize(
        "body,expected",
        [
            ("False positive, this input is validated upstream.", "rejected"),
            ("Won’t fix", "rejected"),
            ("not a bug", "rejected"),
            ("Good catch, fixed in abc123", "accepted"),
            ("Fixed.", "accepted"),
        ],
    )
    def test_reply_verdicts(
        self, body: str, expected: str, devmind_comment: Any
    ) -> None:
        WebhookDispatcher().dispatch(
            _reply_payload(body), "pull_request_review_comment"
        )
        assert _feedback(devmind_comment) == [("reply", expected)]

    @pytest.mark.parametrize(
        "body",
        ["Why is this a problem?", "> fixed\nI don't think so", "Doneness check"],
    )
    def test_reply_without_verdict_is_ignored(
        self, body: str, devmind_comment: Any
    ) -> None:
        WebhookDispatcher().dispatch(
            _reply_payload(body), "pull_request_review_comment"
        )
        assert _feedback(devmind_comment) == []

    def test_later_reply_replaces_earlier_one(self, devmind_comment: Any) -> None:
        dispatcher = WebhookDispatcher()
        dispatcher.dispatch(_reply_payload("Fixed"), "pull_request_review_comment")
        dispatcher.dispatch(
            _reply_payload("Actually, false positive"), "pull_request_review_comment"
        )
        # "Actually, ..." has no verdict, so the first reply's stays.
        assert _feedback(devmind_comment) == [("reply", "accepted")]
        dispatcher.dispatch(
            _reply_payload("False positive after all"), "pull_request_review_comment"
        )
        assert _feedback(devmind_comment) == [("reply", "rejected")]

    def test_top_level_comment_is_not_a_reply(self, devmind_comment: Any) -> None:
        WebhookDispatcher().dispatch(
            _reply_payload("False positive", in_reply_to_id=None),
            "pull_request_review_comment",
        )
        assert _feedback(devmind_comment) == []

    def test_bot_reply_is_ignored(self, devmind_comment: Any) -> None:
        payload = _reply_payload("False positive")
        payload["comment"]["user"] = {"login": "ci[bot]", "type": "Bot"}
        WebhookDispatcher().dispatch(payload, "pull_request_review_comment")
        assert _feedback(devmind_comment) == []

    def test_deleted_reply_is_ignored(self, devmind_comment: Any) -> None:
        payload = _reply_payload("False positive")
        payload["action"] = "deleted"
        WebhookDispatcher().dispatch(payload, "pull_request_review_comment")
        assert _feedback(devmind_comment) == []

    def test_malformed_payloads_are_ignored(self, devmind_comment: Any) -> None:
        dispatcher = WebhookDispatcher()
        dispatcher.dispatch(
            {"action": "resolved", "thread": "x", "repository": {"id": 123456789}},
            "pull_request_review_thread",
        )
        dispatcher.dispatch(
            {"action": "created", "comment": None, "repository": "x"},
            "pull_request_review_comment",
        )
        assert _feedback(devmind_comment) == []

    def test_pr_closed_for_unknown_repo_queues_nothing(self, mocker: Any) -> None:
        mock_fetch = mocker.patch(
            "apps.repositories.webhooks.fetch_comment_reactions_task"
        )
        WebhookDispatcher().dispatch(_closed_payload(repo_id=1), "pull_request")
        mock_fetch.delay.assert_not_called()

    def test_pr_closed_does_not_start_a_review(
        self, devmind_comment: Any, mocker: Any
    ) -> None:
        mocker.patch("apps.repositories.webhooks.fetch_comment_reactions_task")
        mock_review = mocker.patch("apps.repositories.webhooks.trigger_review_task")
        WebhookDispatcher().dispatch(_closed_payload(), "pull_request")
        mock_review.delay.assert_not_called()
