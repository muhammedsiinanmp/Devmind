import pytest

from apps.repositories.models import Repository
from apps.repositories.tests.factories import RepositoryFactory, UserFactory


@pytest.mark.django_db
class TestRepositoryQuerySet:
    def test_active_excludes_inactive(self) -> None:
        RepositoryFactory(is_active=True)
        RepositoryFactory(is_active=False)
        assert Repository.objects.active().count() == 1

    def test_for_user_filters_by_owner(self) -> None:
        user_a = UserFactory()
        user_b = UserFactory()
        RepositoryFactory(owner=user_a)
        RepositoryFactory(owner=user_a)
        RepositoryFactory(owner=user_b)
        assert Repository.objects.for_user(user_a).count() == 2

    def test_with_webhook_filters_installed(self) -> None:
        RepositoryFactory(webhook_id=None)
        RepositoryFactory(webhook_id=12345)
        assert Repository.objects.with_webhook().count() == 1

    def test_review_enabled_combined_filter(self) -> None:
        RepositoryFactory(is_active=True, review_enabled=True)
        RepositoryFactory(is_active=True, review_enabled=False)
        RepositoryFactory(is_active=False, review_enabled=True)
        result = Repository.objects.active().review_enabled()
        assert result.count() == 1
