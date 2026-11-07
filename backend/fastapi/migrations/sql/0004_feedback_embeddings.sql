-- Create feedback_embeddings: DevMind comments that developers accepted or
-- rejected, embedded with their code hunk (issue #74).
--
-- Django sends each comment's verdict to POST /feedback/upsert when it
-- changes; reviews of the same repository retrieve the most similar ones as
-- "Previously accepted findings" and "Previously rejected findings". Apply it
-- by hand, like 0001-0003 (it doesn't depend on them):
--
--   psql -v ON_ERROR_STOP=1 "$DATABASE_URL" -f backend/fastapi/migrations/sql/0004_feedback_embeddings.sql
--
-- Until it is applied, storing feedback fails (FastAPI returns 500 and the
-- Django task retries, then gives up) and reviews run without feedback
-- examples; the failed search is logged as review.feedback_context_failed.
--
-- One row per comment and embedding model: vectors from different models
-- aren't comparable, so search only reads rows of the configured
-- EMBEDDING_MODEL. comment_id is Django's ReviewComment id. There is no HNSW
-- index: a repository has few feedback rows, and search filters on
-- repo_full_name first. Needs the vector extension (a Django migration
-- enables it). Runs in one transaction and is safe to run more than once.

BEGIN;

CREATE TABLE IF NOT EXISTS feedback_embeddings (
    id BIGSERIAL PRIMARY KEY,
    repo_full_name varchar(200) NOT NULL,
    comment_id bigint NOT NULL,
    signal varchar(10) NOT NULL CHECK (signal IN ('accepted', 'rejected')),
    file_path varchar(500) NOT NULL,
    category varchar(20) NOT NULL,
    severity varchar(20) NOT NULL,
    body text NOT NULL,
    code_hunk text NOT NULL DEFAULT '',
    embedding vector(768) NOT NULL,
    embedding_model varchar(100) NOT NULL,
    source_ref varchar(100),
    created_at timestamp with time zone NOT NULL DEFAULT now()
);

-- source_ref ("PR#<n>") is the PR the comment was on; reviews of that PR
-- leave its rows out. Added here too for a table created by an earlier
-- draft of this file.
ALTER TABLE feedback_embeddings ADD COLUMN IF NOT EXISTS source_ref varchar(100);

CREATE UNIQUE INDEX IF NOT EXISTS ux_feedback_embeddings_comment_model
    ON feedback_embeddings (comment_id, embedding_model);

CREATE INDEX IF NOT EXISTS ix_feedback_embeddings_repo_model
    ON feedback_embeddings (repo_full_name, embedding_model);

COMMIT;
