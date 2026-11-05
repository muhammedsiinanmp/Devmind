# DevMind

AI pull-request reviewer: Django (API, webhooks, Celery) + FastAPI (LangGraph review agent, pgvector) + React.

## Work tracking
- Work is planned as vertical-slice issues (label `slice`) on the GitHub Project in `.claude/board.json`. Each issue is the spec: Outcome, Scope, Acceptance criteria, Blocked by.
- `/next-slices` shows what's unblocked. `/ship-slice <n>` runs the `slice-implementer` agent in a worktree and reviews the PR.
- Branches: `slice/<key>-<name>` off `dev`, PR into `dev`. Never push to `dev`/`main`, never merge without the owner.

## Commands
- FastAPI: `cd backend/fastapi && uv sync --frozen && uvx ruff@0.17.3 check . && uv run black --check . && uv run pytest`
- Django (needs Postgres + Redis, `docker compose up -d postgres redis`): same tools, plus `DJANGO_SETTINGS_MODULE=devmind.settings.test uv run python manage.py makemigrations --check --dry-run`
- Frontend: `cd frontend && pnpm install --frozen-lockfile && pnpm build && pnpm lint`
- Evals (after E1): `make eval`

## Rules
- Bug-fix tests must fail before the fix. Never skip or weaken a test.
- Quality claims (README, PRs) must come from eval output or a committed results file.
- Never commit `.env`, `graphify-out/` or AI attribution. Hooks in `.claude/hooks/` enforce this.
