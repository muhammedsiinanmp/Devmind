"""
Tests for GitHub Comment Poster.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from apps.reviews.models import Review, ReviewComment
from apps.reviews.tests.factories import ReviewFactory, ReviewCommentFactory
from apps.repositories.tests.factories import UserFactory, GithubTokenFactory
from apps.reviews.services.github_poster import (
    GitHubPoster,
    group_by_file,
    format_suggestion_block,
    MAX_COMMENTS_PER_REVIEW,
)


class TestGroupByFile:
    def test_groups_comments_by_file(self):
        comments = [
            {"file_path": "app.py", "line_number": 10, "severity": "warning"},
            {"file_path": "utils.py", "line_number": 5, "severity": "error"},
            {"file_path": "app.py", "line_number": 20, "severity": "critical"},
        ]

        result = group_by_file(comments)

        assert len(result) == 2
        assert len(result["app.py"]) == 2
        assert len(result["utils.py"]) == 1
        assert result["app.py"][0]["line_number"] == 10
        assert result["app.py"][1]["line_number"] == 20

    def test_empty_list_returns_empty_dict(self):
        result = group_by_file([])
        assert result == {}

    def test_single_file_multiple_comments(self):
        comments = [{"file_path": "app.py", "line_number": i} for i in range(1, 6)]

        result = group_by_file(comments)

        assert len(result) == 1
        assert len(result["app.py"]) == 5


class TestFormatSuggestionBlock:
    def test_wraps_suggested_fix_in_suggestion_block(self):
        result = format_suggestion_block(
            severity="error",
            body="Use parameterized query",
            suggested_fix="cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))",
        )

        assert "🟠" in result
        assert "Use parameterized query" in result
        assert "```suggestion" in result
        assert "cursor.execute" in result
        assert "```" in result

    def test_critical_severity_emoji(self):
        result = format_suggestion_block(
            severity="critical", body="SQL Injection", suggested_fix="fix here"
        )
        assert "🔴" in result

    def test_warning_severity_emoji(self):
        result = format_suggestion_block(
            severity="warning", body="Unused variable", suggested_fix="remove it"
        )
        assert "🟡" in result

    def test_info_severity_emoji(self):
        result = format_suggestion_block(
            severity="info", body="Consider using", suggested_fix="use this"
        )
        assert "🔵" in result


class TestGitHubPosterInit:
    def test_sets_authorization_header(self):
        poster = GitHubPoster("test_token")

        assert "Authorization" in poster._session.headers
        assert poster._session.headers["Authorization"] == "Bearer test_token"
        assert poster._session.headers["Accept"] == "application/vnd.github+json"


class TestGitHubPosterGroupByFile:
    def test_group_by_file_delegates_to_function(self):
        poster = GitHubPoster("token")
        comments = [
            {"file_path": "a.py", "line_number": 1},
            {"file_path": "b.py", "line_number": 2},
            {"file_path": "a.py", "line_number": 3},
        ]

        result = poster.group_by_file(comments)

        assert len(result["a.py"]) == 2
        assert len(result["b.py"]) == 1


class TestGitHubPosterPostReview:
    def test_posts_to_github_api(self):
        poster = GitHubPoster("token")
        poster._session = Mock()

        mock_response = Mock()
        mock_response.status_code = 200
        poster._session.post.return_value = mock_response

        from apps.reviews.services.github_poster import CommentPayload

        status = poster._post_review(
            repo_full_name="owner/repo",
            pr_number=1,
            head_sha="abc123",
            comments=[CommentPayload(path="app.py", line=10, body="Fix this")],
            summary="AI Review Complete",
        )

        assert status == 200
        poster._session.post.assert_called_once()
        call_args = poster._session.post.call_args
        assert "owner/repo" in call_args[0][0]
        assert call_args[1]["json"]["commit_id"] == "abc123"
        assert call_args[1]["json"]["event"] == "COMMENT"

    def test_returns_status_code_on_error(self):
        poster = GitHubPoster("token")
        poster._session = Mock()

        mock_response = Mock()
        mock_response.status_code = 422
        poster._session.post.return_value = mock_response

        from apps.reviews.services.github_poster import CommentPayload

        status = poster._post_review(
            repo_full_name="owner/repo",
            pr_number=1,
            head_sha="abc123",
            comments=[CommentPayload(path="app.py", line=10, body="Fix this")],
            summary="Test",
        )

        assert status == 422


class TestGitHubPosterBatchComments:
    def test_splits_55_comments_into_2_batches(self):
        poster = GitHubPoster("token")

        comments = [
            {
                "file_path": f"file{i}.py",
                "line_number": i,
                "severity": "info",
                "body": "msg",
            }
            for i in range(1, 56)
        ]

        grouped = poster.group_by_file(comments)
        batches = poster._create_batches(grouped)

        assert len(batches) == 2
        assert len(batches[0]) == 50
        assert len(batches[1]) == 5

    def test_10_comments_under_limit_single_batch(self):
        poster = GitHubPoster("token")

        comments = [
            {
                "file_path": "app.py",
                "line_number": i,
                "severity": "warning",
                "body": "msg",
            }
            for i in range(1, 11)
        ]

        grouped = poster.group_by_file(comments)
        batches = poster._create_batches(grouped)

        assert len(batches) == 1
        assert len(batches[0]) == 10


class TestGitHubPosterFormatComment:
    def test_formats_comment_with_emoji(self):
        poster = GitHubPoster("token")

        comment = {
            "file_path": "app.py",
            "line_number": 10,
            "severity": "warning",
            "body": "Consider using f-string",
        }

        result = poster._format_comment(comment)

        assert result.path == "app.py"
        assert result.line == 10
        assert "🟡" in result.body
        assert "Consider using f-string" in result.body

    def test_formats_comment_with_suggestion(self):
        poster = GitHubPoster("token")

        comment = {
            "file_path": "app.py",
            "line_number": 10,
            "severity": "error",
            "body": "Use parameterized query",
            "suggested_fix": "cursor.execute(...)",
        }

        result = poster._format_comment(comment)

        assert "🟠" in result.body
        assert "```suggestion" in result.body
        assert "cursor.execute" in result.body


class TestGitHubPosterPostReviewComments:
    def test_calls_api_for_each_batch(self):
        poster = GitHubPoster("token")
        poster._session = Mock()

        mock_response = Mock()
        mock_response.status_code = 200
        poster._session.post.return_value = mock_response

        comments = [
            {
                "file_path": "app.py",
                "line_number": i,
                "severity": "warning",
                "body": "msg",
            }
            for i in range(1, 51)
        ]

        status_codes = poster.post_review_comments(
            repo_full_name="owner/repo",
            pr_number=1,
            head_sha="abc123",
            comments=comments,
            summary="Review Complete",
        )

        assert len(status_codes) == 1
        assert poster._session.post.call_count == 1

    def test_empty_comments_returns_empty(self):
        poster = GitHubPoster("token")
        poster._session = Mock()

        status_codes = poster.post_review_comments(
            repo_full_name="owner/repo",
            pr_number=1,
            head_sha="abc123",
            comments=[],
            summary="Review",
        )

        assert status_codes == []
        poster._session.post.assert_not_called()


class TestPostGithubCommentsFunction:
    @pytest.mark.django_db
    @patch("apps.reviews.services.github_poster.GitHubPoster")
    def test_posts_comments_for_completed_review(self, mock_poster_class):
        # Using factories ensures proper CustomUser and GithubToken creation
        review = ReviewFactory(status="completed", summary="2 critical")
        ReviewCommentFactory(
            review=review,
            severity="critical",
            body="SQL Injection vulnerability",
            suggested_fix="Use parameterized queries",
        )

        mock_poster = MagicMock()
        mock_poster.post_review_comments.return_value = [200]
        mock_poster_class.return_value = mock_poster

        from apps.reviews.services.github_poster import post_github_comments

        result = post_github_comments(review.pk)

        assert result == [200]
        mock_poster_class.assert_called_once()
        mock_poster.post_review_comments.assert_called_once()

    @pytest.mark.django_db
    @patch("apps.reviews.services.github_poster.GitHubPoster")
    def test_skips_non_completed_review(self, mock_poster_class):
        review = ReviewFactory(status="pending")

        from apps.reviews.services.github_poster import post_github_comments

        result = post_github_comments(review.pk)

        assert result == []
        mock_poster_class.assert_not_called()

    @pytest.mark.django_db
    @patch("apps.reviews.services.github_poster.GitHubPoster")
    def test_returns_empty_when_no_comments(self, mock_poster_class):
        review = ReviewFactory(status="completed")

        from apps.reviews.services.github_poster import post_github_comments

        result = post_github_comments(review.pk)

        assert result == []
        mock_poster_class.assert_not_called()
