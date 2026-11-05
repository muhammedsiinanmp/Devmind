import pytest
from django.core.management import call_command
from django.db import connection


def _vector_extension_installed() -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        return cursor.fetchone() is not None


@pytest.mark.django_db
def test_migrations_enable_pgvector_extension():
    assert _vector_extension_installed()


@pytest.mark.django_db(transaction=True)
def test_reversing_pgvector_migration_keeps_extension():
    # The reverse is a no-op: FastAPI's embedding tables depend on the
    # extension, so rolling back Django migrations must not drop it.
    call_command("migrate", "core", "zero", verbosity=0)
    try:
        assert _vector_extension_installed()
    finally:
        call_command("migrate", "core", verbosity=0)
    assert _vector_extension_installed()
