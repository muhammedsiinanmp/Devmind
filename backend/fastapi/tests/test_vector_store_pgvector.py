"""
VectorStore queries and migrations/sql against a real pgvector database.

Opt-in: CI has no database for FastAPI, so these run only when
PGVECTOR_TEST_URL points at a Postgres database with the vector extension
installed, e.g.

    PGVECTOR_TEST_URL=postgresql://user:password@localhost:5432/scratch uv run pytest tests/test_vector_store_pgvector.py

Each test works in its own schema, which is dropped afterwards.
"""

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from services.vector_store import VectorStore

PGVECTOR_TEST_URL = os.environ.get("PGVECTOR_TEST_URL", "")

pytestmark = pytest.mark.skipif(
    not PGVECTOR_TEST_URL, reason="PGVECTOR_TEST_URL is not set"
)

SQL_DIR = Path(__file__).resolve().parents[1] / "migrations" / "sql"

# code_embeddings as models/embeddings.py created it before 0001: no
# source_ref, no embedding_model, sha256 unique on its own.
PRE_0001_TABLE = """
CREATE TABLE code_embeddings (
    id BIGSERIAL PRIMARY KEY,
    repo_full_name VARCHAR(200) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    chunk_text TEXT NOT NULL,
    language VARCHAR(20) NOT NULL,
    chunk_type VARCHAR(20) NOT NULL,
    embedding VECTOR(768) NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    UNIQUE (sha256)
);
CREATE INDEX ix_code_embeddings_repo ON code_embeddings (repo_full_name);
CREATE INDEX ix_code_embeddings_language ON code_embeddings (language);
"""

REPO = "owner/repo"
OTHER_REPO = "owner/other-repo"
SHA = "a" * 64
VECTOR = [1.0] + [0.0] * 767


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(v) for v in values) + "]"


async def _apply_sql_files(conn) -> None:
    for path in sorted(SQL_DIR.glob("*.sql")):
        await conn.execute(path.read_text())


@pytest.fixture
async def migrated_schema():
    """A schema holding a pre-0001 code_embeddings table with one row written
    before embeddings were tagged, then every migrations/sql file applied
    twice. Yields (schema, asyncpg connection)."""
    import asyncpg

    schema = f"a8_test_{uuid.uuid4().hex[:8]}"
    conn = await asyncpg.connect(PGVECTOR_TEST_URL)
    try:
        await conn.execute(f"CREATE SCHEMA {schema}")
        await conn.execute(f"SET search_path TO {schema}, public")
        await conn.execute(PRE_0001_TABLE)
        await conn.execute(
            "INSERT INTO code_embeddings (repo_full_name, file_path, chunk_text,"
            " language, chunk_type, embedding, sha256)"
            " VALUES ($1, 'a.py', 'x = 1', 'python', 'hunk', $2::vector, $3)",
            REPO,
            _vector_literal(VECTOR),
            SHA,
        )
        await _apply_sql_files(conn)
        await _apply_sql_files(conn)
        yield schema, conn
    finally:
        await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        await conn.close()


@pytest.fixture
async def session_factory(migrated_schema):
    schema, _ = migrated_schema
    url = PGVECTOR_TEST_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": f"{schema},public"}}
    )
    try:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        await engine.dispose()


def _store() -> VectorStore:
    store = VectorStore()
    store.embedding_model = "gemini-embedding-001"
    return store


async def _insert(store: VectorStore, session, repo: str) -> None:
    await store.insert_code_embedding(
        session, repo, "a.py", "x = 1", VECTOR, SHA, chunk_type="hunk"
    )


class TestMigration0003:
    @pytest.mark.asyncio
    async def test_untagged_rows_are_tagged_as_the_old_model(self, migrated_schema):
        _, conn = migrated_schema

        rows = await conn.fetch("SELECT embedding_model FROM code_embeddings")

        assert [r["embedding_model"] for r in rows] == ["text-embedding-004"]

    @pytest.mark.asyncio
    async def test_sha256_is_unique_per_repo_and_model_only(self, migrated_schema):
        _, conn = migrated_schema

        unique = await conn.fetch(
            "SELECT pg_get_indexdef(indexrelid) AS definition FROM pg_index"
            " WHERE indrelid = 'code_embeddings'::regclass"
            " AND indisunique AND NOT indisprimary"
        )
        nullable = await conn.fetchval(
            "SELECT is_nullable FROM information_schema.columns"
            " WHERE table_schema = current_schema()"
            " AND table_name = 'code_embeddings'"
            " AND column_name = 'embedding_model'"
        )

        assert [r["definition"].split(" USING ")[1] for r in unique] == [
            "btree (repo_full_name, sha256, embedding_model)"
        ]
        assert nullable == "NO"


class TestQueries:
    @pytest.mark.asyncio
    async def test_search_never_returns_rows_from_another_model(self, session_factory):
        store = _store()
        async with session_factory() as session:
            await store.enable_iterative_scan(session)
            results = await store.search_similar_by_embedding(session, VECTOR, REPO)

        # The only row is the untagged one, now tagged text-embedding-004.
        assert results == []

    @pytest.mark.asyncio
    async def test_chunk_stored_with_another_model_is_stored_again(
        self, session_factory
    ):
        store = _store()
        async with session_factory() as session:
            assert await store.existing_hashes(session, REPO, [SHA]) == set()
            await _insert(store, session, REPO)

            results = await store.search_similar_by_embedding(session, VECTOR, REPO)
            assert await store.existing_hashes(session, REPO, [SHA]) == {SHA}

        assert [r.similarity for r in results] == [1.0]

    @pytest.mark.asyncio
    async def test_same_chunk_is_stored_for_two_repos(self, session_factory):
        store = _store()
        async with session_factory() as session:
            await _insert(store, session, REPO)
            assert await store.existing_hashes(session, OTHER_REPO, [SHA]) == set()

            await _insert(store, session, OTHER_REPO)

            found = await store.search_similar_by_embedding(session, VECTOR, OTHER_REPO)
        assert len(found) == 1

    @pytest.mark.asyncio
    async def test_same_chunk_twice_for_one_repo_and_model_is_rejected(
        self, session_factory
    ):
        store = _store()
        async with session_factory() as session:
            await _insert(store, session, REPO)
            with pytest.raises(IntegrityError):
                await _insert(store, session, REPO)
