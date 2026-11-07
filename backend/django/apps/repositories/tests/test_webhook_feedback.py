"""
Feedback webhooks (issue #74): pull_request_review_thread,
pull_request_review_comment, and pull_request closed.

Celery runs eagerly in tests, so the queued record_feedback_event_task runs
inside the request. GitHub permission lookups are mocked with `responses`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import pytest
import responses
from django.test import Client

from apps.repositories.tests.factories import RepositoryFactory
from apps.repositories.webhooks import WebhookDispatcher

WEBHOOK_SECRET = "test-webhook-secret-32-chars-here"
PERMISSION_URL = "https://api.github.com/repos/acme/api/collaborators/{}/permission"
PR_AUTHOR = "pr-author"


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


@pytest.fixture
def owner(devmind_comment: Any) -> str:
    """Login of the DevMind user who connected the repository."""
    return devmind_comment.review.repository.owner.github_login


def _pr(author: str = PR_AUTHOR) -> dict[str, Any]:
    return {"number": 42, "user": {"login": author, "type": "User"}}


def _thread_payload(
    action: str, comment_ids: list[int], sender: str, pr_author: str = PR_AUTHOR
) -> dict[str, Any]:
    return {
        "action": action,
        "thread": {
            "node_id": "PRRT_1",
            "comments": [{"id": comment_id} for comment_id in comment_ids],
        },
        "pull_request": _pr(pr_author),
        "repository": {"id": 123456789, "full_name": "acme/api"},
        "sender": {"login": sender, "type": "User"},
    }


def _reply_payload(
    body: str,
    user: str,
    association: str = "COLLABORATOR",
    in_reply_to_id: int | None = 9001,
    action: str = "created",
    reply_id: int = 9100,
    pr_author: str = PR_AUTHOR,
) -> dict[str, Any]:
    comment: dict[str, Any] = {
        "id": reply_id,
        "body": body,
        "user": {"login": user, "type": "User"},
        "author_association": association,
    }
    if in_reply_to_id is not None:
        comment["in_reply_to_id"] = in_reply_to_id
    return {
        "action": action,
        "comment": comment,
        "pull_request": _pr(pr_author),
        "repository": {"id": 123456789, "full_name": "acme/api"},
    }


def _closed_payload(repo_id: int = 123456789) -> dict[str, Any]:
    return {
        "action": "closed",
        "pull_request": {**_pr(), "merged": True},
        "repository": {"id": repo_id, "full_name": "acme/api"},
    }


def _feedback(comment: Any) -> list[tuple[str, str]]:
    return sorted(comment.feedback.values_list("source", "signal"))


def _permission(login: str, permission: str) -> None:
    responses.add(
        responses.GET, PERMISSION_URL.format(login), json={"permission": permission}
    )


def _events(owner: str) -> list[tuple[str, dict[str, Any]]]:
    return [
        ("pull_request_review_thread", _thread_payload("resolved", [9001], owner)),
        ("pull_request_review_comment", _reply_payload("False positive", owner)),
    ]


@pytest.mark.django_db
class TestFeedbackWebhookSignatures:
    """The new events go through the same HMAC check as pull_request."""

    @pytest.mark.parametrize("index", [0, 1])
    def test_valid_signature_is_accepted_and_recorded(
        self, index: int, owner: str, devmind_comment: Any, settings: Any
    ) -> None:
        settings.GITHUB_WEBHOOK_SECRET = WEBHOOK_SECRET
        event_type, payload = _events(owner)[index]

        response = _post_signed(payload, event_type)

        assert response.status_code == 200
        assert devmind_comment.feedback.count() == 1

    @pytest.mark.parametrize("index", [0, 1])
    def test_wrong_signature_returns_403_and_records_nothing(
        self, index: int, owner: str, devmind_comment: Any, settings: Any
    ) -> None:
        settings.GITHUB_WEBHOOK_SECRET = WEBHOOK_SECRET
        event_type, payload = _events(owner)[index]

        response = _post_signed(payload, event_type, secret="attacker-secret")

        assert response.status_code == 403
        assert devmind_comment.feedback.count() == 0

    @pytest.mark.parametrize("index", [0, 1])
    def test_missing_signature_returns_403_and_records_nothing(
        self, index: int, owner: str, devmind_comment: Any, settings: Any
    ) -> None:
        settings.GITHUB_WEBHOOK_SECRET = WEBHOOK_SECRET
        event_type, payload = _events(owner)[index]

        response = Client().post(
            "/api/v1/webhooks/github/",
            data=json.dumps(payload).encode(),
            content_type="application/json",
            HTTP_X_GITHUB_EVENT=event_type,
        )

        assert response.status_code == 403
        assert devmind_comment.feedback.count() == 0

    @pytest.mark.parametrize("index", [0, 1])
    def test_unset_secret_returns_403_and_records_nothing(
        self, index: int, owner: str, devmind_comment: Any, settings: Any
    ) -> None:
        settings.GITHUB_WEBHOOK_SECRET = ""
        event_type, payload = _events(owner)[index]

        response = _post_signed(payload, event_type, secret="")

        assert response.status_code == 403
        assert devmind_comment.feedback.count() == 0

    def test_signed_pr_closed_queues_reaction_fetch_with_the_pr_author(
        self, devmind_comment: Any, settings: Any, mocker: Any
    ) -> None:
        settings.GITHUB_WEBHOOK_SECRET = WEBHOOK_SECRET
        mock_fetch = mocker.patch(
            "apps.repositories.webhooks.fetch_comment_reactions_task"
        )

        response = _post_signed(_closed_payload(), "pull_request")

        assert response.status_code == 200
        mock_fetch.delay.assert_called_once_with(
            repo_id=devmind_comment.review.repository_id,
            pr_number=42,
            pr_author=PR_AUTHOR,
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
    def test_resolved_thread_is_accepted(
        self, devmind_comment: Any, owner: str
    ) -> None:
        WebhookDispatcher().dispatch(
            _thread_payload("resolved", [9001, 9100], owner),
            "pull_request_review_thread",
        )
        assert _feedback(devmind_comment) == [("resolved", "accepted")]

    def test_unresolved_thread_removes_the_verdict(
        self, devmind_comment: Any, owner: str
    ) -> None:
        dispatcher = WebhookDispatcher()
        dispatcher.dispatch(
            _thread_payload("resolved", [9001], owner), "pull_request_review_thread"
        )
        dispatcher.dispatch(
            _thread_payload("unresolved", [9001], owner), "pull_request_review_thread"
        )
        assert _feedback(devmind_comment) == []

    def test_resolving_twice_keeps_one_row(
        self, devmind_comment: Any, owner: str
    ) -> None:
        dispatcher = WebhookDispatcher()
        for _ in range(2):
            dispatcher.dispatch(
                _thread_payload("resolved", [9001], owner),
                "pull_request_review_thread",
            )
        assert _feedback(devmind_comment) == [("resolved", "accepted")]

    def test_thread_of_another_repository_is_ignored(
        self, devmind_comment: Any, owner: str
    ) -> None:
        payload = _thread_payload("resolved", [9001], owner)
        payload["repository"] = {"id": 555, "full_name": "evil/repo"}
        WebhookDispatcher().dispatch(payload, "pull_request_review_thread")
        assert _feedback(devmind_comment) == []

    def test_thread_without_devmind_comment_is_ignored(
        self, devmind_comment: Any, owner: str
    ) -> None:
        WebhookDispatcher().dispatch(
            _thread_payload("resolved", [1, 2], owner), "pull_request_review_thread"
        )
        assert _feedback(devmind_comment) == []

    def test_thread_of_inactive_repository_is_ignored(
        self, devmind_comment: Any, owner: str
    ) -> None:
        repo = devmind_comment.review.repository
        repo.is_active = False
        repo.save()
        WebhookDispatcher().dispatch(
            _thread_payload("resolved", [9001], owner), "pull_request_review_thread"
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
        self, body: str, expected: str, devmind_comment: Any, owner: str
    ) -> None:
        WebhookDispatcher().dispatch(
            _reply_payload(body, owner), "pull_request_review_comment"
        )
        assert _feedback(devmind_comment) == [("reply", expected)]

    @pytest.mark.parametrize(
        "body",
        ["Why is this a problem?", "> fixed\nI don't think so", "Doneness check"],
    )
    def test_reply_without_verdict_is_ignored(
        self, body: str, devmind_comment: Any, owner: str
    ) -> None:
        WebhookDispatcher().dispatch(
            _reply_payload(body, owner), "pull_request_review_comment"
        )
        assert _feedback(devmind_comment) == []

    def test_later_reply_replaces_earlier_one(
        self, devmind_comment: Any, owner: str
    ) -> None:
        dispatcher = WebhookDispatcher()
        dispatcher.dispatch(
            _reply_payload("Fixed", owner, reply_id=1), "pull_request_review_comment"
        )
        dispatcher.dispatch(
            _reply_payload("Actually, false positive", owner, reply_id=2),
            "pull_request_review_comment",
        )
        # "Actually, ..." has no verdict, so the first reply's stays.
        assert _feedback(devmind_comment) == [("reply", "accepted")]
        dispatcher.dispatch(
            _reply_payload("False positive after all", owner, reply_id=3),
            "pull_request_review_comment",
        )
        assert _feedback(devmind_comment) == [("reply", "rejected")]

    def test_top_level_comment_is_not_a_reply(
        self, devmind_comment: Any, owner: str
    ) -> None:
        WebhookDispatcher().dispatch(
            _reply_payload("False positive", owner, in_reply_to_id=None),
            "pull_request_review_comment",
        )
        assert _feedback(devmind_comment) == []

    def test_bot_reply_is_ignored(self, devmind_comment: Any, owner: str) -> None:
        payload = _reply_payload("False positive", owner)
        payload["comment"]["user"] = {"login": "ci[bot]", "type": "Bot"}
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


@pytest.mark.django_db
class TestOnlyTrustedUsersCount:
    """Security review of #109, rule 1a: untrusted users can't poison feedback."""

    @responses.activate
    @pytest.mark.parametrize(
        "association", ["NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "MANNEQUIN"]
    )
    def test_reply_from_outsider_is_ignored_without_a_github_call(
        self, association: str, devmind_comment: Any
    ) -> None:
        WebhookDispatcher().dispatch(
            _reply_payload("False positive", "stranger", association),
            "pull_request_review_comment",
        )
        assert _feedback(devmind_comment) == []
        assert len(responses.calls) == 0

    @responses.activate
    @pytest.mark.parametrize("association", ["MEMBER", "COLLABORATOR"])
    def test_read_only_member_or_collaborator_is_ignored(
        self, association: str, devmind_comment: Any
    ) -> None:
        _permission("reader", "read")
        WebhookDispatcher().dispatch(
            _reply_payload("False positive", "reader", association),
            "pull_request_review_comment",
        )
        assert _feedback(devmind_comment) == []
        assert len(responses.calls) == 1

    @responses.activate
    @pytest.mark.parametrize("permission", ["write", "admin"])
    def test_collaborator_with_write_access_counts(
        self, permission: str, devmind_comment: Any
    ) -> None:
        _permission("maintainer", permission)
        WebhookDispatcher().dispatch(
            _reply_payload("False positive", "maintainer", "MEMBER"),
            "pull_request_review_comment",
        )
        assert _feedback(devmind_comment) == [("reply", "rejected")]
        token = devmind_comment.review.repository.owner.github_token.access_token
        assert responses.calls[0].request.headers["Authorization"] == f"Bearer {token}"

    @responses.activate
    def test_repository_owner_association_counts_without_a_call(
        self, devmind_comment: Any
    ) -> None:
        WebhookDispatcher().dispatch(
            _reply_payload("False positive", "repo-owner", "OWNER"),
            "pull_request_review_comment",
        )
        assert _feedback(devmind_comment) == [("reply", "rejected")]
        assert len(responses.calls) == 0

    @responses.activate
    def test_thread_resolved_by_read_only_user_is_ignored(
        self, devmind_comment: Any
    ) -> None:
        _permission("reader", "read")
        WebhookDispatcher().dispatch(
            _thread_payload("resolved", [9001], "reader"),
            "pull_request_review_thread",
        )
        assert _feedback(devmind_comment) == []

    @responses.activate
    def test_thread_resolved_by_writer_counts(self, devmind_comment: Any) -> None:
        _permission("maintainer", "write")
        WebhookDispatcher().dispatch(
            _thread_payload("resolved", [9001], "maintainer"),
            "pull_request_review_thread",
        )
        assert _feedback(devmind_comment) == [("resolved", "accepted")]

    @responses.activate
    def test_unknown_user_is_not_trusted(self, devmind_comment: Any) -> None:
        responses.add(
            responses.GET, PERMISSION_URL.format("ghost"), json={}, status=404
        )
        WebhookDispatcher().dispatch(
            _reply_payload("False positive", "ghost", "COLLABORATOR"),
            "pull_request_review_comment",
        )
        assert _feedback(devmind_comment) == []

    def test_untrusted_user_cannot_unresolve(
        self, devmind_comment: Any, owner: str, mocker: Any
    ) -> None:
        dispatcher = WebhookDispatcher()
        dispatcher.dispatch(
            _thread_payload("resolved", [9001], owner), "pull_request_review_thread"
        )
        mocker.patch(
            "apps.repositories.services.GitHubService.get_collaborator_permission",
            return_value="read",
        )
        dispatcher.dispatch(
            _thread_payload("unresolved", [9001], "reader"),
            "pull_request_review_thread",
        )
        assert _feedback(devmind_comment) == [("resolved", "accepted")]


@pytest.mark.django_db
class TestPullRequestAuthorIsIgnored:
    """Rule 1c: the person being reviewed can't silence the findings."""

    def test_pr_author_reply_is_ignored_even_as_owner(
        self, devmind_comment: Any, owner: str
    ) -> None:
        WebhookDispatcher().dispatch(
            _reply_payload("False positive", owner, "OWNER", pr_author=owner),
            "pull_request_review_comment",
        )
        assert _feedback(devmind_comment) == []

    def test_pr_author_resolving_the_thread_is_ignored(
        self, devmind_comment: Any, mocker: Any
    ) -> None:
        mocker.patch(
            "apps.repositories.services.GitHubService.get_collaborator_permission",
            return_value="admin",
        )
        WebhookDispatcher().dispatch(
            _thread_payload("resolved", [9001], PR_AUTHOR),
            "pull_request_review_thread",
        )
        assert _feedback(devmind_comment) == []

    def test_author_match_ignores_case(self, devmind_comment: Any, owner: str) -> None:
        WebhookDispatcher().dispatch(
            _reply_payload("False positive", owner.upper(), pr_author=owner),
            "pull_request_review_comment",
        )
        assert _feedback(devmind_comment) == []

    def test_unknown_pr_author_counts_nothing(
        self, devmind_comment: Any, owner: str
    ) -> None:
        payload = _reply_payload("False positive", owner)
        del payload["pull_request"]
        WebhookDispatcher().dispatch(payload, "pull_request_review_comment")
        assert _feedback(devmind_comment) == []


@pytest.mark.django_db
class TestReplyDeleteAndEdit:
    """Rule 1d: deleting a reply removes its verdict; edits re-evaluate."""

    def test_deleting_the_reply_removes_its_verdict(
        self, devmind_comment: Any, owner: str
    ) -> None:
        dispatcher = WebhookDispatcher()
        dispatcher.dispatch(
            _reply_payload("False positive", owner, reply_id=7),
            "pull_request_review_comment",
        )
        dispatcher.dispatch(
            _reply_payload("False positive", owner, reply_id=7, action="deleted"),
            "pull_request_review_comment",
        )
        assert _feedback(devmind_comment) == []

    def test_deleting_another_reply_keeps_the_verdict(
        self, devmind_comment: Any, owner: str
    ) -> None:
        dispatcher = WebhookDispatcher()
        dispatcher.dispatch(
            _reply_payload("False positive", owner, reply_id=7),
            "pull_request_review_comment",
        )
        dispatcher.dispatch(
            _reply_payload("Fixed", owner, reply_id=8, action="deleted"),
            "pull_request_review_comment",
        )
        assert _feedback(devmind_comment) == [("reply", "rejected")]

    def test_editing_the_verdict_away_removes_it(
        self, devmind_comment: Any, owner: str
    ) -> None:
        dispatcher = WebhookDispatcher()
        dispatcher.dispatch(
            _reply_payload("False positive", owner, reply_id=7),
            "pull_request_review_comment",
        )
        dispatcher.dispatch(
            _reply_payload("Hmm, let me check", owner, reply_id=7, action="edited"),
            "pull_request_review_comment",
        )
        assert _feedback(devmind_comment) == []

    def test_editing_to_another_verdict_updates_it(
        self, devmind_comment: Any, owner: str
    ) -> None:
        dispatcher = WebhookDispatcher()
        dispatcher.dispatch(
            _reply_payload("False positive", owner, reply_id=7),
            "pull_request_review_comment",
        )
        dispatcher.dispatch(
            _reply_payload("Fixed now", owner, reply_id=7, action="edited"),
            "pull_request_review_comment",
        )
        assert _feedback(devmind_comment) == [("reply", "accepted")]
