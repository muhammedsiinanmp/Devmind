"""
factory-boy factories for the reviews app.

Rule: Never call Model.objects.create() directly in tests.
Always use factories — they encapsulate defaults and make tests self-documenting.
"""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from apps.repositories.tests.factories import UserFactory, RepositoryFactory
from apps.reviews.models import RepoScan, Review, ReviewComment, ReviewRun


class ReviewFactory(DjangoModelFactory):
    class Meta:
        model = Review

    repository = factory.SubFactory(RepositoryFactory)
    pr_number = factory.Sequence(lambda n: n + 1)
    pr_title = factory.Faker("sentence", nb_words=6)
    head_sha = factory.Faker("sha1")
    base_sha = factory.Faker("sha1")
    diff_url = factory.LazyAttribute(
        lambda o: f"https://github.com/{o.repository.full_name}/pull/{o.pr_number}"
    )
    status = "pending"
    risk_score = None
    summary = ""
    completed_at = None


class ReviewCommentFactory(DjangoModelFactory):
    class Meta:
        model = ReviewComment

    review = factory.SubFactory(ReviewFactory)
    file_path = factory.Faker("file_path", extension="py")
    line_number = factory.Faker("random_int", min=1, max=1000)
    body = factory.Faker("paragraph")
    severity = "warning"
    category = "quality"
    suggested_fix = ""


class ReviewRunFactory(DjangoModelFactory):
    class Meta:
        model = ReviewRun

    review = factory.SubFactory(ReviewFactory)
    agent_iterations = 1
    model_used = "google/gemini-2.0-flash"
    prompt_tokens = factory.Faker("random_int", min=500, max=2000)
    completion_tokens = factory.Faker("random_int", min=100, max=500)
    latency_ms = factory.Faker("random_int", min=500, max=5000)


class RepoScanFactory(DjangoModelFactory):
    class Meta:
        model = RepoScan

    repository = factory.SubFactory(RepositoryFactory)
    triggered_by = factory.SubFactory(UserFactory)
    status = "queued"
    progress = 0
    total_files = factory.Faker("random_int", min=10, max=100)
    files_scanned = 0
    total_issues = 0
    critical_count = 0
    warning_count = 0
    info_count = 0
    scan_duration_ms = None
    completed_at = None
