-- Add code_embeddings.source_ref (issue #65).
--
-- Nothing in the repo creates code_embeddings yet (see "Known limitations" in
-- the README), so apply this by hand to a database where the table already
-- exists:
--
--   psql "$DATABASE_URL" -f backend/fastapi/migrations/sql/0001_code_embeddings_source_ref.sql
--
-- Safe to run more than once.

ALTER TABLE code_embeddings ADD COLUMN IF NOT EXISTS source_ref varchar(100);
