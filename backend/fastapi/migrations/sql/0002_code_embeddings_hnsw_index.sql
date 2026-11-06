-- HNSW index for cosine similarity search on code_embeddings (issue #87).
--
-- search_similar orders by `embedding <=> query` (cosine distance) with a
-- LIMIT, which this index serves instead of a sequential scan. Like 0001,
-- apply it by hand to a database where the table already exists:
--
--   psql "$DATABASE_URL" -f backend/fastapi/migrations/sql/0002_code_embeddings_hnsw_index.sql
--
-- Building the index locks the table against writes until it finishes. Safe to
-- run more than once.

CREATE INDEX IF NOT EXISTS ix_code_embeddings_embedding_hnsw
    ON code_embeddings USING hnsw (embedding vector_cosine_ops);
