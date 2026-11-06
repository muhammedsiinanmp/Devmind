# DevMind frontend

The React single-page app for DevMind. You use it to sign in with GitHub, sync repositories and turn reviews on or off, browse AI reviews with a diff viewer and manage your own LLM provider keys (BYOK).

## Stack

| Concern | Library |
|---|---|
| UI | React 19, TypeScript 6 |
| Build / dev server | Vite 8 (`@vitejs/plugin-react`) |
| Styling | Tailwind CSS 4 (via `@tailwindcss/postcss`), `lucide-react` icons |
| Routing | React Router 7 |
| State | Zustand (auth store in `src/store/index.ts`) |
| HTTP | axios (`src/api/client.ts`) |
| Diff rendering | `react-diff-viewer-continued` |
| Lint | ESLint 9 with `typescript-eslint`, `react-hooks`, `react-refresh` |

## Scripts

Requires Node.js 20 and pnpm 9, the versions used in CI.

```bash
pnpm install --frozen-lockfile
pnpm dev        # Vite dev server on http://localhost:5173 (binds 0.0.0.0)
pnpm build      # tsc -b && vite build -> dist/
pnpm lint       # eslint .
pnpm preview    # serve the production build locally
```

CI (`.github/workflows/ci.yml`) runs `pnpm exec tsc -p tsconfig.app.json --noEmit`, `pnpm build`, `pnpm lint` and `pnpm test`. `pnpm test` runs Vitest, which currently covers only the review status polling loop (`src/lib/reviewStatusPolling.test.ts`) and a check that the removed scan page and API stay removed (`src/api/scanRemoved.test.ts`).

## How it talks to the backend

- **Django only.** All requests go to Django under `/api/v1` (axios `baseURL: '/api/v1'`). The frontend never calls the FastAPI service.
- **Dev proxy.** In development, `vite.config.ts` proxies `/api` to `http://localhost:8000` (the Django container from the root `docker-compose.yml`). Start the backend stack first; see the [root README](../README.md).
- **Sign-in.** `Login` calls `GET /api/v1/auth/github/start/` and redirects to the returned GitHub URL. GitHub sends the user back to `/auth/callback`, which calls `GET /api/v1/auth/github/callback/?code=&state=` and stores the returned `access` / `refresh` JWTs in `localStorage`. The GitHub OAuth App's callback URL must be `http://localhost:5173/auth/callback`.
- **Auth headers.** An axios request interceptor adds `Authorization: Bearer <access>`. On a 401 it calls `POST /api/v1/auth/token/refresh/` once, queues other requests until the refresh finishes, and sends the user to `/login` if the refresh fails.
- **Live status.** While a review is `pending` or `processing`, `ReviewStatus` polls `GET /api/v1/reviews/<id>/` every 3 seconds. It stops when the status becomes `completed` or `failed`, or when the component unmounts. Each request waits for the previous one to finish, and a failed request is retried on the next tick.

## Environment variables

The app reads no environment variables: nothing in `src/` uses `import.meta.env`.

## Pages

Routes come from `src/App.tsx`. Every route except `/login` and `/auth/callback` requires sign-in.

| Route | Page |
|---|---|
| `/login`, `/auth/callback` | GitHub sign-in |
| `/`, `/dashboard` | Review list |
| `/reviews/:id` | Review detail with diff and inline comments |
| `/repositories` | Connected repositories, GitHub sync, per-repo review toggle |
| `/settings` | BYOK LLM provider management |

## Docker

`Dockerfile` has a `dev` target (`pnpm dev --host`) and a `production-serve` target that builds the app and serves `dist/` with `nginx:alpine`. The root `docker-compose.yml` doesn't use it.
