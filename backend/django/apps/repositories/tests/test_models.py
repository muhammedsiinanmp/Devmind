import pytest
from django.db import IntegrityError

from apps.repositories.tests.factories import RepositoryFactory, UserFactory


@pytest.mark.django_db
class TestRepositoryModel:
    def test_str_returns_full_name(self) -> None:
        repo = RepositoryFactory(full_name="acme/api")
        assert str(repo) == "acme/api"

    def test_github_id_is_unique(self) -> None:
        repo = RepositoryFactory()
        with pytest.raises(IntegrityError):
            RepositoryFactory(github_id=repo.github_id)

    def test_default_is_active_true(self) -> None:
        repo = RepositoryFactory()
        assert repo.is_active is True

    def test_default_review_enabled_true(self) -> None:
        repo = RepositoryFactory()
        assert repo.review_enabled is True

    def test_webhook_id_nullable_by_default(self) -> None:
        repo = RepositoryFactory()
        assert repo.webhook_id is None

    def test_owner_fk_cascades_on_user_delete(self) -> None:
        from apps.repositories.models import Repository

        user = UserFactory()
        RepositoryFactory(owner=user)
        user.delete()
        assert Repository.objects.count() == 0

    def test_timestamps_auto_set(self) -> None:
        repo = RepositoryFactory()
        assert repo.created_at is not None
        assert repo.updated_at is not None

    def test_updated_at_changes_on_save(self) -> None:
        import time

        repo = RepositoryFactory()
        original_updated = repo.updated_at
        time.sleep(0.01)
        repo.default_branch = "develop"
        repo.save(update_fields=["default_branch", "updated_at"])
        repo.refresh_from_db()
        assert repo.updated_at > original_updated
