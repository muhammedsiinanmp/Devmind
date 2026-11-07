"""
Feedback learning (issue #74): reaction polling with a mocked GitHub API,
verdict precedence, hunk extraction, the FastAPI sync, GitHub comment ids
and the review detail API.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import responses
from rest_framework.test import APIClient

from apps.repositories.exceptions import (
    GitHubAuthError,
    GitHubNotFoundError,
    GitHubPermissionError,
    GitHubRateLimitError,
)
from apps.reviews.models import CommentFeedback
from apps.reviews.services.feedback import (
    FeedbackSyncError,
    classify_reactions,
    extract_hunk,
    feedback_payload,
    fetch_reaction_feedback,
    record_feedback,
    sync_comment_feedback,
)
from apps.reviews.services.github_poster import (
    CommentPayload,
    GitHubPoster,
    match_posted_comments,
    post_github_comments,
)
from apps.reviews.tasks import fetch_comment_reactions_task, rate_limit_countdown
from apps.reviews.tests.factories import (
    CommentFeedbackFactory,
    ReviewCommentFactory,
    ReviewFactory,
    ReviewRunFactory,
)

PR_COMMENTS_URL = "https://api.github.com/repos/acme/api/pulls/42/comments"
REACTIONS_URL = "https://api.github.com/repos/acme/api/pulls/comments/{}/reactions"
PERMISSION_URL = "https://api.github.com/repos/acme/api/collaborators/{}/permission"
PR_AUTHOR = "pr-author"
KNOWN_IDS: dict[str, int] = {PR_AUTHOR: 777}


def _gh_comment(comment_id: int, plus: int = 0, minus: int = 0) -> dict[str, Any]:
    return {
        "id": comment_id,
        "path": "app.py",
        "body": "msg",
        "reactions": {"+1": plus, "-1": minus, "heart": 3, "total_count": plus + minus},
    }


def _reactions(comment_id: int, votes: list[tuple[str, str]]) -> None:
    """Register GitHub's reaction list for one comment: (login, content)."""
    responses.add(
        responses.GET,
        REACTIONS_URL.format(comment_id),
        json=[
            {
                "content": content,
                "user": {
                    "login": login,
                    "id": KNOWN_IDS.get(login, 50_000),
                    "type": "User",
                },
            }
            for login, content in votes
        ],
    )


def _permission(login: str, permission: str) -> None:
    responses.add(
        responses.GET, PERMISSION_URL.format(login), json={"permission": permission}
    )


@pytest.fixture
def review(db: Any) -> Any:
    from apps.repositories.tests.factories import RepositoryFactory

    repo = RepositoryFactory(full_name="acme/api")
    return ReviewFactory(repository=repo, pr_number=42, status="completed")


@pytest.fixture
def owner(review: Any) -> str:
    user = review.repository.owner
    KNOWN_IDS[user.github_login] = user.github_id
    return user.github_login


def _fetch(review: Any) -> int:
    return fetch_reaction_feedback(review.repository_id, 42, PR_AUTHOR)


def _signals(review: Any) -> dict[int, list[tuple[str, str]]]:
    """Verdicts in force; rows cleared to no signal are ordering markers."""
    return {
        c.github_comment_id: sorted(
            c.feedback.exclude(signal__isnull=True).values_list("source", "signal")
        )
        for c in review.comments.all()
    }


class TestClassifyReactions:
    @pytest.mark.parametrize(
        "plus,minus,expected",
        [(2, 1, "accepted"), (1, 2, "rejected"), (1, 1, None), (0, 0, None)],
    )
    def test_majority_decides_and_a_tie_is_no_signal(
        self, plus: int, minus: int, expected: str | None
    ) -> None:
        assert classify_reactions(plus, minus) == expected


@pytest.mark.django_db
class TestFetchReactionFeedback:
    @responses.activate
    def test_records_trusted_reactions_with_the_owner_token(
        self, review: Any, owner: str
    ) -> None:
        ReviewCommentFactory(review=review, github_comment_id=1)
        ReviewCommentFactory(review=review, github_comment_id=2)
        ReviewCommentFactory(review=review, github_comment_id=3)
        responses.add(
            responses.GET,
            PR_COMMENTS_URL,
            json=[_gh_comment(1, plus=1), _gh_comment(2, minus=1), _gh_comment(3)],
        )
        _reactions(1, [(owner, "+1"), (owner, "heart")])
        _reactions(2, [(owner, "-1")])

        checked = _fetch(review)

        assert checked == 3
        assert _signals(review) == {
            1: [("reaction", "accepted")],
            2: [("reaction", "rejected")],
            3: [],
        }
        token = review.repository.owner.github_token.access_token
        assert all(
            call.request.headers["Authorization"] == f"Bearer {token}"
            for call in responses.calls
        )
        # Comment 3 has no 👍/👎, so its reactions aren't listed.
        assert not any("/comments/3/" in call.request.url for call in responses.calls)

    @responses.activate
    def test_running_again_updates_instead_of_duplicating(
        self, review: Any, owner: str
    ) -> None:
        ReviewCommentFactory(review=review, github_comment_id=1)
        responses.add(responses.GET, PR_COMMENTS_URL, json=[_gh_comment(1, plus=1)])
        _reactions(1, [(owner, "+1")])
        _fetch(review)
        responses.replace(
            responses.GET, PR_COMMENTS_URL, json=[_gh_comment(1, minus=1)]
        )
        responses.replace(
            responses.GET,
            REACTIONS_URL.format(1),
            json=[
                {
                    "content": "-1",
                    "user": {"login": owner, "id": KNOWN_IDS[owner], "type": "User"},
                }
            ],
        )

        _fetch(review)

        assert _signals(review) == {1: [("reaction", "rejected")]}

    @responses.activate
    def test_no_reactions_left_removes_an_earlier_verdict(self, review: Any) -> None:
        comment = ReviewCommentFactory(review=review, github_comment_id=1)
        CommentFeedbackFactory(comment=comment, source="reaction", signal="accepted")
        responses.add(responses.GET, PR_COMMENTS_URL, json=[_gh_comment(1)])

        _fetch(review)

        assert _signals(review) == {1: []}

    @responses.activate
    def test_comment_deleted_on_github_keeps_its_verdict(self, review: Any) -> None:
        comment = ReviewCommentFactory(review=review, github_comment_id=1)
        CommentFeedbackFactory(comment=comment, source="reaction", signal="accepted")
        responses.add(responses.GET, PR_COMMENTS_URL, json=[])

        assert _fetch(review) == 0
        assert _signals(review) == {1: [("reaction", "accepted")]}

    @responses.activate
    def test_owner_without_token_makes_no_github_call(self, review: Any) -> None:
        ReviewCommentFactory(review=review, github_comment_id=1)
        review.repository.owner.github_token.delete()

        assert _fetch(review) == 0
        assert len(responses.calls) == 0

    @responses.activate
    def test_no_posted_comments_makes_no_github_call(self, review: Any) -> None:
        ReviewCommentFactory(review=review, github_comment_id=None)

        assert _fetch(review) == 0
        assert len(responses.calls) == 0

    @responses.activate
    def test_reads_every_page(self, review: Any, owner: str) -> None:
        ReviewCommentFactory(review=review, github_comment_id=1)
        ReviewCommentFactory(review=review, github_comment_id=2)
        page2 = PR_COMMENTS_URL + "?per_page=100&page=2"
        responses.add(
            responses.GET,
            PR_COMMENTS_URL,
            json=[_gh_comment(1, plus=1)],
            headers={
                "Link": f'<{page2}>; rel="next"',
                "X-RateLimit-Remaining": "4000",
            },
            match=[responses.matchers.query_param_matcher({"per_page": "100"})],
        )
        responses.add(
            responses.GET,
            PR_COMMENTS_URL,
            json=[_gh_comment(2, minus=1)],
            match=[
                responses.matchers.query_param_matcher({"per_page": "100", "page": "2"})
            ],
        )
        _reactions(1, [(owner, "+1")])
        _reactions(2, [(owner, "-1")])

        _fetch(review)

        assert _signals(review) == {
            1: [("reaction", "accepted")],
            2: [("reaction", "rejected")],
        }

    @responses.activate
    def test_stops_before_next_page_when_quota_is_low(self, review: Any) -> None:
        ReviewCommentFactory(review=review, github_comment_id=1)
        responses.add(
            responses.GET,
            PR_COMMENTS_URL,
            json=[_gh_comment(1, plus=1)],
            headers={
                "Link": f'<{PR_COMMENTS_URL}?page=2>; rel="next"',
                "X-RateLimit-Remaining": "5",
                "X-RateLimit-Reset": "1900000000",
            },
        )

        with pytest.raises(GitHubRateLimitError) as exc_info:
            _fetch(review)

        assert exc_info.value.reset_at == 1900000000
        assert len(responses.calls) == 1
        assert _signals(review) == {1: []}

    @responses.activate
    @pytest.mark.parametrize(
        "status,headers",
        [
            (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1900000000"}),
            (403, {"Retry-After": "60"}),
            (429, {"Retry-After": "120"}),
        ],
    )
    def test_rate_limit_responses_raise(
        self, review: Any, status: int, headers: dict[str, str]
    ) -> None:
        ReviewCommentFactory(review=review, github_comment_id=1)
        responses.add(
            responses.GET, PR_COMMENTS_URL, json={}, status=status, headers=headers
        )

        with pytest.raises(GitHubRateLimitError):
            _fetch(review)


@pytest.mark.django_db
class TestOnlyTrustedReactionsCount:
    """Security review of #109, rules 1b, 1c and 5."""

    @responses.activate
    def test_outsider_downvotes_do_not_count(self, review: Any, owner: str) -> None:
        ReviewCommentFactory(review=review, github_comment_id=1)
        responses.add(
            responses.GET, PR_COMMENTS_URL, json=[_gh_comment(1, plus=1, minus=3)]
        )
        _reactions(1, [(owner, "+1"), ("a", "-1"), ("b", "-1"), ("c", "-1")])
        for login in ("a", "b", "c"):
            _permission(login, "read")

        _fetch(review)

        assert _signals(review) == {1: [("reaction", "accepted")]}

    @responses.activate
    def test_writers_count(self, review: Any) -> None:
        ReviewCommentFactory(review=review, github_comment_id=1)
        responses.add(responses.GET, PR_COMMENTS_URL, json=[_gh_comment(1, minus=1)])
        _reactions(1, [("maintainer", "-1")])
        _permission("maintainer", "write")

        _fetch(review)

        assert _signals(review) == {1: [("reaction", "rejected")]}

    @responses.activate
    def test_pr_author_reaction_never_counts(self, review: Any) -> None:
        ReviewCommentFactory(review=review, github_comment_id=1)
        responses.add(responses.GET, PR_COMMENTS_URL, json=[_gh_comment(1, minus=1)])
        _reactions(1, [(PR_AUTHOR, "-1")])

        _fetch(review)

        assert _signals(review) == {1: []}
        # Excluded before any permission lookup.
        assert not any("/permission" in call.request.url for call in responses.calls)

    @responses.activate
    def test_bot_reactions_never_count(self, review: Any) -> None:
        ReviewCommentFactory(review=review, github_comment_id=1)
        responses.add(responses.GET, PR_COMMENTS_URL, json=[_gh_comment(1, minus=1)])
        responses.add(
            responses.GET,
            REACTIONS_URL.format(1),
            json=[{"content": "-1", "user": {"login": "x[bot]", "type": "Bot"}}],
        )

        _fetch(review)

        assert _signals(review) == {1: []}

    @responses.activate
    def test_permission_is_looked_up_once_per_user(self, review: Any) -> None:
        ReviewCommentFactory(review=review, github_comment_id=1)
        ReviewCommentFactory(review=review, github_comment_id=2)
        responses.add(
            responses.GET,
            PR_COMMENTS_URL,
            json=[_gh_comment(1, minus=1), _gh_comment(2, minus=1)],
        )
        _reactions(1, [("maintainer", "-1")])
        _reactions(2, [("maintainer", "-1")])
        _permission("maintainer", "write")

        _fetch(review)

        lookups = [c for c in responses.calls if "/permission" in c.request.url]
        assert len(lookups) == 1

    @responses.activate
    def test_pr_author_is_fetched_when_not_given(self, review: Any) -> None:
        ReviewCommentFactory(review=review, github_comment_id=1)
        responses.add(
            responses.GET,
            "https://api.github.com/repos/acme/api/pulls/42",
            json={"user": {"login": PR_AUTHOR, "id": 777}},
        )
        responses.add(responses.GET, PR_COMMENTS_URL, json=[_gh_comment(1, minus=1)])
        _reactions(1, [(PR_AUTHOR, "-1")])

        fetch_reaction_feedback(review.repository_id, 42)

        assert _signals(review) == {1: []}

    @responses.activate
    def test_quota_floor_applies_to_per_comment_calls(self, review: Any) -> None:
        ReviewCommentFactory(review=review, github_comment_id=1)
        responses.add(
            responses.GET,
            PR_COMMENTS_URL,
            json=[_gh_comment(1, minus=1)],
            headers={"X-RateLimit-Remaining": "3", "X-RateLimit-Reset": "1900000000"},
        )

        with pytest.raises(GitHubRateLimitError):
            _fetch(review)

        assert len(responses.calls) == 1

    @responses.activate
    def test_inactive_repository_is_skipped_at_run_time(self, review: Any) -> None:
        ReviewCommentFactory(review=review, github_comment_id=1)
        repo = review.repository
        repo.is_active = False
        repo.save()

        assert _fetch(review) == 0
        assert len(responses.calls) == 0

    @responses.activate
    def test_pagination_never_leaves_api_github_com(
        self, review: Any, owner: str
    ) -> None:
        ReviewCommentFactory(review=review, github_comment_id=1)
        responses.add(
            responses.GET,
            PR_COMMENTS_URL,
            json=[_gh_comment(1, plus=1)],
            headers={"Link": '<https://evil.example/steal?page=2>; rel="next"'},
        )
        _reactions(1, [(owner, "+1")])

        _fetch(review)

        assert not any("evil.example" in c.request.url for c in responses.calls)
        assert _signals(review) == {1: [("reaction", "accepted")]}


class TestReactionTask:
    def test_countdown_waits_for_reset_within_bounds(self) -> None:
        assert rate_limit_countdown(reset_at=1300, now=1000) == 300
        assert rate_limit_countdown(reset_at=0, now=1000) == 60
        assert rate_limit_countdown(reset_at=100_000, now=1000) == 3600

    def test_rate_limit_retries_after_the_reset(self, mocker: Any) -> None:
        mocker.patch(
            "apps.reviews.services.feedback.fetch_reaction_feedback",
            side_effect=GitHubRateLimitError(reset_at=1300),
        )
        mocker.patch("time.time", return_value=1000)
        retry = mocker.patch.object(
            fetch_comment_reactions_task, "retry", side_effect=RuntimeError("retry")
        )

        with pytest.raises(RuntimeError):
            fetch_comment_reactions_task.run(1, 42)

        assert retry.call_args.kwargs["countdown"] == 300

    @pytest.mark.parametrize(
        "error",
        [
            GitHubAuthError("401"),
            GitHubNotFoundError("404"),
            GitHubPermissionError("403"),
        ],
    )
    def test_permanent_errors_are_not_retried(self, mocker: Any, error) -> None:
        mocker.patch(
            "apps.reviews.services.feedback.fetch_reaction_feedback",
            side_effect=error,
        )
        retry = mocker.patch.object(fetch_comment_reactions_task, "retry")

        assert fetch_comment_reactions_task.run(1, 42) == 0
        retry.assert_not_called()


@pytest.mark.django_db
class TestGitHubErrorMapping:
    """Rule 4: 403 is a rate limit only with Remaining 0 or Retry-After."""

    @responses.activate
    def test_plain_403_is_a_permission_error(self, review: Any) -> None:
        ReviewCommentFactory(review=review, github_comment_id=1)
        responses.add(
            responses.GET,
            PR_COMMENTS_URL,
            json={"message": "Resource not accessible"},
            status=403,
            headers={"X-RateLimit-Remaining": "4000"},
        )

        with pytest.raises(GitHubPermissionError):
            _fetch(review)

    @responses.activate
    def test_404_is_not_found(self, review: Any) -> None:
        ReviewCommentFactory(review=review, github_comment_id=1)
        responses.add(responses.GET, PR_COMMENTS_URL, json={}, status=404)

        with pytest.raises(GitHubNotFoundError):
            _fetch(review)


@pytest.mark.django_db
class TestRecordFeedback:
    def test_reaction_beats_reply_beats_resolved(self, review: Any) -> None:
        comment = ReviewCommentFactory(review=review)
        record_feedback(comment, "resolved", "accepted")
        record_feedback(comment, "reply", "rejected")
        state = CommentFeedback.effective(comment.feedback.all())
        assert (state.source, state.signal) == ("reply", "rejected")

        record_feedback(comment, "reaction", "accepted")
        state = CommentFeedback.effective(comment.feedback.all())
        assert (state.source, state.signal) == ("reaction", "accepted")

    def test_queues_sync_only_when_the_verdict_changes(
        self, review: Any, mocker: Any, django_capture_on_commit_callbacks: Any
    ) -> None:
        sync = mocker.patch("apps.reviews.tasks.sync_comment_feedback_task")
        comment = ReviewCommentFactory(review=review)

        with django_capture_on_commit_callbacks(execute=True):
            assert record_feedback(comment, "resolved", "accepted") is True
        with django_capture_on_commit_callbacks(execute=True):
            # Same effective verdict from another source: nothing to resend.
            assert record_feedback(comment, "reply", "accepted") is False
        with django_capture_on_commit_callbacks(execute=True):
            assert record_feedback(comment, "reaction", "rejected") is True

        assert sync.delay.call_count == 2
        sync.delay.assert_called_with(comment.pk)


DIFF = """\
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,3 +1,4 @@
 import os
+import sys
 x = 1
 y = 2
@@ -20,2 +21,3 @@ def f():
     a = 1
+    b = eval(user_input)
     return a
diff --git a/other.py b/other.py
--- a/other.py
+++ b/other.py
@@ -1 +1,2 @@
 z = 3
+w = 4
"""


class TestExtractHunk:
    def test_returns_the_hunk_holding_the_line(self) -> None:
        hunk = extract_hunk(DIFF, "app.py", 22)
        assert hunk.splitlines() == [
            "@@ -20,2 +21,3 @@ def f():",
            "     a = 1",
            "+    b = eval(user_input)",
            "     return a",
        ]

    def test_first_hunk_and_other_file(self) -> None:
        assert extract_hunk(DIFF, "app.py", 2).splitlines()[2] == "+import sys"
        assert extract_hunk(DIFF, "other.py", 2).splitlines()[-1] == "+w = 4"

    def test_no_hunk_is_empty(self) -> None:
        assert extract_hunk(DIFF, "app.py", 10) == ""
        assert extract_hunk(DIFF, "missing.py", 1) == ""
        assert extract_hunk("", "app.py", 1) == ""


@pytest.mark.django_db
class TestSyncCommentFeedback:
    def test_posts_the_verdict_and_hunk_with_the_internal_secret(
        self, review: Any, mocker: Any, settings: Any
    ) -> None:
        settings.FASTAPI_INTERNAL_SECRET = "s3cret"
        settings.FASTAPI_BASE_URL = "http://fastapi:8001/"
        ReviewRunFactory(review=review, diff_text=DIFF)
        comment = ReviewCommentFactory(
            review=review, file_path="app.py", line_number=22, body="eval is unsafe"
        )
        CommentFeedbackFactory(comment=comment, source="reply", signal="rejected")
        post = mocker.patch(
            "apps.reviews.services.feedback.httpx.post",
            return_value=httpx.Response(200, json={"stored": True}),
        )

        sync_comment_feedback(comment.pk)

        url = post.call_args.args[0]
        body = post.call_args.kwargs["json"]
        assert url == "http://fastapi:8001/feedback/upsert"
        assert post.call_args.kwargs["headers"] == {"X-Internal-Secret": "s3cret"}
        assert body["signal"] == "rejected"
        assert body["repo_full_name"] == "acme/api"
        assert body["comment_id"] == comment.pk
        assert body["pr_number"] == 42
        assert "+    b = eval(user_input)" in body["code_hunk"]
        json.dumps(body)  # serializable

    def test_no_verdict_sends_null_signal(self, review: Any) -> None:
        comment = ReviewCommentFactory(review=review)
        assert feedback_payload(comment)["signal"] is None
        assert feedback_payload(comment)["code_hunk"] == ""

    def test_fastapi_error_raises_for_retry(
        self, review: Any, mocker: Any, settings: Any
    ) -> None:
        settings.FASTAPI_INTERNAL_SECRET = "s3cret"
        comment = ReviewCommentFactory(review=review)
        mocker.patch(
            "apps.reviews.services.feedback.httpx.post",
            return_value=httpx.Response(503),
        )
        with pytest.raises(FeedbackSyncError):
            sync_comment_feedback(comment.pk)

    def test_missing_secret_raises(self, review: Any, settings: Any) -> None:
        settings.FASTAPI_INTERNAL_SECRET = ""
        comment = ReviewCommentFactory(review=review)
        with pytest.raises(FeedbackSyncError):
            sync_comment_feedback(comment.pk)


class TestMatchPostedComments:
    def test_matches_by_path_and_body_in_order(self) -> None:
        sent = [
            CommentPayload(path="a.py", line=1, body="🟡 same", comment_id=10),
            CommentPayload(path="a.py", line=5, body="🟡 same", comment_id=11),
            CommentPayload(path="b.py", line=2, body="🔴 other", comment_id=12),
            CommentPayload(path="c.py", line=2, body="no id"),
        ]
        posted = [
            {"id": 900, "path": "a.py", "body": "🟡 same"},
            {"id": 901, "path": "a.py", "body": "🟡 same\r\n"},
            {"id": 902, "path": "b.py", "body": "🔴 other"},
        ]
        assert match_posted_comments(sent, posted) == {10: 900, 11: 901, 12: 902}

    def test_unmatched_comment_gets_no_id(self) -> None:
        sent = [CommentPayload(path="a.py", line=1, body="x", comment_id=10)]
        assert (
            match_posted_comments(sent, [{"id": 1, "path": "b.py", "body": "x"}]) == {}
        )


@pytest.mark.django_db
class TestPostGithubCommentsStoresIds:
    REVIEWS_URL = "https://api.github.com/repos/acme/api/pulls/42/reviews"

    @responses.activate
    def test_stores_github_ids_of_posted_inline_comments(self, review: Any) -> None:
        first = ReviewCommentFactory(
            review=review, file_path="app.py", line_number=3, body="first"
        )
        second = ReviewCommentFactory(
            review=review, file_path="app.py", line_number=9, body="second"
        )
        body_only = ReviewCommentFactory(
            review=review, file_path="app.py", line_number=0, body="no line"
        )
        poster = GitHubPoster("x")
        responses.add(responses.POST, self.REVIEWS_URL, json={"id": 77}, status=200)
        responses.add(
            responses.GET,
            f"{self.REVIEWS_URL}/77/comments",
            json=[
                {
                    "id": 5002,
                    "path": "app.py",
                    "body": poster._format_comment(
                        {"severity": "warning", "body": "second"}
                    ).body,
                },
                {
                    "id": 5001,
                    "path": "app.py",
                    "body": poster._format_comment(
                        {"severity": "warning", "body": "first"}
                    ).body,
                },
            ],
        )

        assert post_github_comments(review.pk) == [200]

        for comment in (first, second, body_only):
            comment.refresh_from_db()
        assert (first.github_comment_id, second.github_comment_id) == (5001, 5002)
        assert body_only.github_comment_id is None

    @responses.activate
    def test_id_lookup_failure_still_posts(self, review: Any) -> None:
        comment = ReviewCommentFactory(review=review, line_number=3)
        responses.add(responses.POST, self.REVIEWS_URL, json={"id": 77}, status=200)
        responses.add(responses.GET, f"{self.REVIEWS_URL}/77/comments", status=500)

        assert post_github_comments(review.pk) == [200]
        comment.refresh_from_db()
        assert comment.github_comment_id is None

    @responses.activate
    def test_body_only_fallback_stores_no_ids(self, review: Any) -> None:
        comment = ReviewCommentFactory(review=review, line_number=3)
        responses.add(responses.POST, self.REVIEWS_URL, status=422)
        responses.add(responses.POST, self.REVIEWS_URL, json={"id": 78}, status=200)

        assert post_github_comments(review.pk) == [200]
        comment.refresh_from_db()
        assert comment.github_comment_id is None
        assert not any(call.request.method == "GET" for call in responses.calls)


@pytest.mark.django_db
class TestReviewDetailFeedback:
    def test_each_comment_shows_its_effective_feedback(self, review: Any) -> None:
        client = APIClient()
        client.force_authenticate(user=review.repository.owner)
        voted = ReviewCommentFactory(review=review)
        CommentFeedbackFactory(comment=voted, source="resolved", signal="accepted")
        CommentFeedbackFactory(comment=voted, source="reaction", signal="rejected")
        silent = ReviewCommentFactory(review=review)

        response = client.get(f"/api/v1/reviews/{review.pk}/")

        assert response.status_code == 200
        by_id = {c["id"]: c["feedback"] for c in response.json()["comments"]}
        assert by_id[voted.pk]["signal"] == "rejected"
        assert by_id[voted.pk]["source"] == "reaction"
        assert by_id[silent.pk] is None


@pytest.mark.django_db
class TestReactionOwnerById:
    """Re-review fix 1 for reactions."""

    @responses.activate
    def test_owners_old_login_with_another_id_is_not_the_owner(
        self, review: Any, owner: str
    ) -> None:
        ReviewCommentFactory(review=review, github_comment_id=1)
        responses.add(responses.GET, PR_COMMENTS_URL, json=[_gh_comment(1, minus=1)])
        responses.add(
            responses.GET,
            REACTIONS_URL.format(1),
            json=[
                {
                    "content": "-1",
                    "user": {"login": owner, "id": 424242, "type": "User"},
                }
            ],
        )
        _permission(owner, "read")

        _fetch(review)

        assert _signals(review) == {1: []}

    @responses.activate
    def test_renamed_owner_still_counts(self, review: Any) -> None:
        ReviewCommentFactory(review=review, github_comment_id=1)
        responses.add(responses.GET, PR_COMMENTS_URL, json=[_gh_comment(1, minus=1)])
        owner_id = review.repository.owner.github_id
        responses.add(
            responses.GET,
            REACTIONS_URL.format(1),
            json=[
                {
                    "content": "-1",
                    "user": {"login": "new-login", "id": owner_id, "type": "User"},
                }
            ],
        )

        _fetch(review)

        assert _signals(review) == {1: [("reaction", "rejected")]}
