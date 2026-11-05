# Contributing to DevMind

## Setup

Follow [Quick start](README.md#quick-start-local-development) in the README to run the stack, and [docs/ENGINEERING_GUIDE.md](docs/ENGINEERING_GUIDE.md) for every environment variable and workflow. Never commit `.env` or real credentials.

## Branches and pull requests

- `dev` is the default branch and is protected: force pushes and deletion are disabled. Branch from `dev` and open your pull request against it.
- These three CI checks from [`.github/workflows/ci.yml`](.github/workflows/ci.yml) are required status checks on `dev`, so they must pass before a pull request can merge:
  - `Django (pytest)`
  - `FastAPI (pytest)`
  - `Frontend (typecheck, build, lint)`
- Keep each pull request to one concern, and say in the description what you changed and how you tested it.
- A bug fix should come with a test that fails without the fix and passes with it.

## Checks to run locally

These are the same commands CI runs.

**Django** (`backend/django`). The tests need Postgres and Redis; the compose services work.

```bash
cd backend/django
uv sync --frozen
uvx ruff@0.17.3 check .
uv run black --check .
DJANGO_SECRET_KEY=dev JWT_SECRET_KEY=dev DJANGO_SETTINGS_MODULE=devmind.settings.test \
  DATABASE_URL=postgresql://devmind:devmind_secret@localhost:5432/devmind \
  uv run python manage.py makemigrations --check --dry-run
DJANGO_SECRET_KEY=dev JWT_SECRET_KEY=dev \
DATABASE_URL=postgresql://devmind:devmind_secret@localhost:5432/devmind \
REDIS_URL=redis://localhost:6379/0 DJANGO_ALLOW_ASYNC_UNSAFE=1 \
uv run pytest --cov
```

**FastAPI** (`backend/fastapi`). No services needed.

```bash
cd backend/fastapi
uv sync --frozen
uvx ruff@0.17.3 check .
uv run black --check .
uv run pytest
```

**Frontend** (`frontend`)

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm exec tsc -p tsconfig.app.json --noEmit
pnpm build
pnpm lint
```

With the compose stack running, `make test` runs both backend test suites inside the containers, and `make format` runs black on the Django code.

### Pre-commit hooks

[`.pre-commit-config.yaml`](.pre-commit-config.yaml) runs black, hadolint on Dockerfiles (via Docker), and the standard hooks: trailing whitespace, end-of-file fixer, YAML check, a 500 KB limit on added files, merge-conflict markers and leftover debug statements. Install it once:

```bash
pre-commit install
```

## Commit style

Look at `git log` for examples. Subjects are short, imperative and in sentence case, with no type prefix, for example "Reject GitHub webhooks when GITHUB_WEBHOOK_SECRET is unset". Use the body to explain why when the change isn't obvious. Keep each commit to one logical change.
