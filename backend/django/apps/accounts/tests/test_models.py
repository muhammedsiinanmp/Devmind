import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection

from apps.accounts.models import GithubToken

User = get_user_model()


@pytest.mark.django_db
class TestCustomUserCreation:
    def test_create_user_with_email(self) -> None:
        user = User.objects.create_user(
            email="user@example.com",
            password="securepass123",
        )
        assert user.email == "user@example.com"
        assert user.check_password("securepass123")
        assert user.is_active is True
        assert user.is_staff is False
        assert user.is_superuser is False

    def test_email_is_username_field(self) -> None:
        assert User.USERNAME_FIELD == "email"

    def test_create_user_without_email_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Email is required"):
            User.objects.create_user(email="", password="pass123")

    def test_create_superuser_sets_staff_and_superuser(self) -> None:
        admin = User.objects.create_superuser(
            email="admin@example.com",
            password="adminpass123",
        )
        assert admin.is_staff is True
        assert admin.is_superuser is True

    def test_user_str_returns_email(self) -> None:
        user = User.objects.create_user(
            email="str@example.com",
            password="pass123",
        )
        assert str(user) == "str@example.com"


@pytest.mark.django_db
class TestCustomUserConstraints:
    def test_duplicate_github_id_raises_integrity_error(self) -> None:
        User.objects.create_user(
            email="first@example.com",
            password="pass123",
            github_id=99999,
        )
        with pytest.raises(IntegrityError):
            User.objects.create_user(
                email="second@example.com",
                password="pass123",
                github_id=99999,
            )


@pytest.mark.django_db
class TestGithubToken:
    def test_access_token_encrypted_at_rest(self) -> None:
        user = User.objects.create_user(
            email="encrypt@example.com",
            password="pass123",
        )
        plaintext = "gho_super_secret_token_12345"
        token = GithubToken.objects.create(
            user=user,
            access_token=plaintext,
            token_type="bearer",
        )

        # After refresh, the Python object should return plaintext
        token.refresh_from_db()
        assert token.access_token == plaintext

        # But the RAW database value must NOT be plaintext
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT access_token FROM accounts_githubtoken WHERE id = %s",
                [token.id],
            )
            raw_value = cursor.fetchone()[0]

        assert raw_value != plaintext
        assert len(raw_value) > len(plaintext)

    def test_github_token_str(self) -> None:
        user = User.objects.create_user(
            email="tokenstr@example.com",
            password="pass123",
        )
        token = GithubToken.objects.create(
            user=user,
            access_token="test_token",
        )
        assert str(token) == "GithubToken for tokenstr@example.com"
