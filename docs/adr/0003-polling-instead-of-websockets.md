# 0003: Polling instead of WebSockets for review status

Status: accepted. Implemented in #83 (C2); polling error handling in #101 (C7) and the refetch on completion in #104 (C8).

## Context

The code had Django Channels consumers and an optional Supabase status push, but neither was ever served: there was no ASGI server, the production image runs `gunicorn devmind.wsgi:application`, and Nginx had no WebSocket upgrade block. Making them work would have meant an ASGI server, a channel layer and a second authentication path (for example a JWT in a WebSocket query string).

## Decision

Remove the Channels and Supabase code. The browser reads status from the same JWT-authenticated REST endpoint as everything else: while a review is `pending` or `processing`, `ReviewStatus` polls `GET /api/v1/reviews/<id>/` every 3 seconds. A 403 or 404 stops polling; a 5xx or network error backs off (3, 6, 12, 24, 48, then 60 s) and polling gives up after 10 consecutive failures. The loop is in `frontend/src/lib/reviewStatusPolling.ts` and is covered by Vitest.

## Consequences

- One auth path: the ownership checks on `GET /api/v1/reviews/<id>/` apply to status reads.
- The server handles only short HTTP requests under WSGI, with no long-lived connections.
- Status appears up to 3 seconds late, and every open page with an unfinished review sends a request every 3 seconds. With many open dashboards, polling would become the main read load; server-sent events or WebSockets behind an ASGI server would then be worth their cost. That is a consideration, not a measured limit.
