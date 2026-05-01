"""
factory-boy factories for the repositories app.

Rule: Never call Model.objects.create() directly in tests.
Always use factories — they encapsulate defaults and make tests self-documenting.
"""

from __future__ import annotations

from typing import Any

import factory
from factory.django import DjangoModelFactory

from apps.repositories.models import Repository


class UserFactory(DjangoModelFactory):
    """
    Mirrors the accounts app UserFactory to avoid cross-app import.
    """

    class Meta:
        model = "accounts.CustomUser"

    email = factory.Sequence(lambda n: f"user{n}@devmind.test")
    github_id = factory.Sequence(lambda n: 10_000 + n)
    github_login = factory.Sequence(lambda n: f"devuser{n}")
    avatar_url = factory.LazyAttribute(
        lambda o: f"https://avatars.githubusercontent.com/u/{o.github_id}"
    )
    is_active = True

    @factory.post_generation
    def github_token(self, create: bool, extracted: Any, **kwargs: Any) -> None:
        if not create:
            return
        if extracted is not False:
            GithubTokenFactory(user=self, **kwargs)


class GithubTokenFactory(DjangoModelFactory):
    class Meta:
        model = "accounts.GithubToken"

    user = factory.SubFactory(UserFactory)
    access_token = factory.Sequence(lambda n: f"ghp_test_token_{n}")
    token_type = "bearer"
    scopes = factory.LazyFunction(lambda: ["repo", "user"])


class RepositoryFactory(DjangoModelFactory):
    class Meta:
        model = Repository

    github_id = factory.Sequence(lambda n: 20_000 + n)
    full_name = factory.Sequence(lambda n: f"acme/repo-{n}")
    name = factory.LazyAttribute(lambda o: o.full_name.split("/")[1])
    owner = factory.SubFactory(UserFactory)
    description = factory.Faker("sentence", nb_words=8)
    is_private = False
    default_branch = "main"
    html_url = factory.LazyAttribute(lambda o: f"https://github.com/{o.full_name}")
    clone_url = factory.LazyAttribute(lambda o: f"https://github.com/{o.full_name}.git")
    language = "Python"
    topics = factory.LazyFunction(list)
    stargazers_count = factory.Faker("random_int", min=0, max=5000)
    webhook_id = None
    is_active = True
    review_enabled = True
    last_synced_at = None
