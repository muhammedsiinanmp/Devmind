-- Tag code_embeddings rows with their embedding model, and make the sha256
-- duplicate key per repository and model instead of global (issue #100).
--
-- Vectors from different embedding models aren't comparable, so search only
-- reads rows whose embedding_model is the configured EMBEDDING_MODEL, and a
-- chunk is stored again when it was only stored for another repository or
-- with another model. Apply it by hand after 0001 and 0002, like them:
--
--   psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f backend/fastapi/migrations/sql/0003_code_embeddings_model_tag.sql
--
-- Apply it before deploying the code that reads embedding_model. Until then,
-- the running code's inserts fail on the NOT NULL column; the store task logs
-- each one (store_review.chunk_error) and the review itself is unaffected.
--
-- Existing rows: their model isn't recorded, so every existing row gets
-- 'text-embedding-004', the model used before gemini-embedding-001. That
-- is the safe guess. Rows that really are text-embedding-004 vectors must
-- never be compared with gemini-embedding-001 queries; tagged as the old
-- model, they are left out of search, and a chunk is no longer blocked from
-- being stored with the current model when a later review's diff contains
-- it. If some of them were in fact written by gemini-embedding-001, the cost
-- is only that they aren't retrieved. Nothing re-embeds old rows. Once this
-- has run, delete them:
--
--   DELETE FROM code_embeddings WHERE embedding_model = 'text-embedding-004';
--
-- Until then they stay in the HNSW graph, where filtered searches still visit
-- them and iterative scans take longer.
--
-- The tag is applied as the column's default when it is added, so no row is
-- rewritten (Postgres 11+ stores a constant default without touching rows),
-- and the default is then dropped so new rows must name their model. ADD
-- COLUMN takes an ACCESS EXCLUSIVE lock, held until COMMIT, so reads and
-- searches on code_embeddings wait too, not only writes, while the unique
-- index below is built. Runs in one transaction and is safe to run more than
-- once.

BEGIN;

ALTER TABLE code_embeddings
    ADD COLUMN IF NOT EXISTS embedding_model varchar(100) NOT NULL
    DEFAULT 'text-embedding-004';

ALTER TABLE code_embeddings ALTER COLUMN embedding_model DROP DEFAULT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_code_embeddings_repo_sha256_model
    ON code_embeddings (repo_full_name, sha256, embedding_model);

-- Drop the old global uniqueness on sha256 alone. Its name depends on how the
-- table was created (code_embeddings_sha256_key when created from
-- models/embeddings.py), so find it by its column instead.
DO $$
DECLARE
    sha256_attnum int2;
    item record;
BEGIN
    SELECT attnum INTO sha256_attnum
    FROM pg_attribute
    WHERE attrelid = 'code_embeddings'::regclass
      AND attname = 'sha256'
      AND NOT attisdropped;

    FOR item IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'code_embeddings'::regclass
          AND contype = 'u'
          AND conkey = ARRAY[sha256_attnum]
    LOOP
        EXECUTE format(
            'ALTER TABLE code_embeddings DROP CONSTRAINT %I', item.conname
        );
    END LOOP;

    -- A unique index on sha256 alone that backs no constraint.
    FOR item IN
        SELECT i.indexrelid::regclass AS index_name
        FROM pg_index i
        WHERE i.indrelid = 'code_embeddings'::regclass
          AND i.indisunique
          AND NOT i.indisprimary
          AND i.indnatts = 1
          AND i.indkey[0] = sha256_attnum
          AND i.indexprs IS NULL
          AND i.indpred IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM pg_constraint c WHERE c.conindid = i.indexrelid
          )
    LOOP
        EXECUTE format('DROP INDEX %s', item.index_name);
    END LOOP;
END
$$;

COMMIT;
