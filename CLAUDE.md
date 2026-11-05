# DevMind

AI pull-request reviewer: Django (API, webhooks, Celery) + FastAPI (LangGraph review agent, pgvector) + React.

## Work tracking
- Work is planned as vertical-slice issues (label `slice`) on the GitHub Project in `.claude/board.json`. Each issue is the spec: Outcome, Scope, Acceptance criteria, Blocked by.
- `/next-slices` shows what's unblocked. `/ship-slice <n>` runs the `slice-implementer` agent in a worktree and reviews the PR.
- Branches: `slice/<key>-<name>` off `dev`, PR into `dev`. Never push to `dev`/`main`. Only the main session merges into `dev`, after a verifier or ai-pipeline-reviewer PASS and green CI. Subagents never merge.

## Commands
- FastAPI: `cd backend/fastapi && uv sync --frozen && uvx ruff@0.17.3 check . && uv run black --check . && uv run pytest`
- Django (needs Postgres + Redis, `docker compose up -d postgres redis`): same tools, plus `DJANGO_SETTINGS_MODULE=devmind.settings.test uv run python manage.py makemigrations --check --dry-run`
- Frontend: `cd frontend && pnpm install --frozen-lockfile && pnpm build && pnpm lint`
- Evals (after E1): `make eval`

## Tools
- **graphify:** read `graphify-out/GRAPH_REPORT.md` first, then `graphify query|path|explain` before searching by hand. Open the source before stating a fact. Never commit `graphify-out/`.
- **ast-grep:** use for structural search and codemods (`ast-grep -p 'from channels.$X import $Y' -l python`) instead of regex when removing or renaming code.
- **Context7 MCP:** check current docs for LangGraph, Django 5, React 19, Vite 8 and Tailwind 4 before using an API you're unsure of.
- **Playwright MCP:** verify frontend changes in a real browser (`pnpm dev`, then navigate). The frontend has no automated tests, so this is the UI check for verifiers.

## Owner-only actions
Anything only the owner can do (merging, auth scopes, secrets, runs that need their API keys, actions an agent was denied, product decisions, accounts) goes to the pinned issue **#86 "Owner action queue"**: an unchecked item with the exact command and why it matters, marked urgent if it blocks other work. Agents report such items in their hand-back under a `Needs owner` heading. Never ask for them only in chat.

## Rules
- Bug-fix tests must fail before the fix. Never skip or weaken a test.
- Quality claims (README, PRs) must come from eval output or a committed results file.
- Never commit `.env`, `graphify-out/` or AI attribution. Hooks in `.claude/hooks/` enforce this.
