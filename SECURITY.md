# Security Policy

## Reporting a vulnerability

Please don't report security problems in public issues, pull requests or discussions.

Report them privately through GitHub instead: open the repository's **Security** tab and choose **Report a vulnerability**. This creates a private security advisory that only the maintainers can see. Include:

- the affected component (Django API, Celery tasks, FastAPI service, frontend, or the compose/Nginx configuration) and the file or endpoint if you know it;
- steps to reproduce, or a proof of concept;
- what an attacker could do with it.

If the **Report a vulnerability** button isn't available, open an issue that asks for a private contact channel. Don't include any vulnerability details in it.

## Supported versions

DevMind has no tagged releases. Fixes go into the `dev` branch.

## Security model

The design is described in the [Security Model](docs/SYSTEM_ARCHITECTURE.md#11-security-model) section of the architecture docs. In short:

- GitHub webhooks are checked with HMAC-SHA256 before parsing, and rejected when no webhook secret is configured.
- Django and FastAPI authenticate each other with a shared `X-Internal-Secret` header, compared in constant time.
- GitHub OAuth tokens and BYOK API keys are encrypted at rest with Fernet, using a key derived from `DJANGO_SECRET_KEY`.
- A user-supplied BYOK `base_url` must be https and resolve only to public addresses.

Known gaps are listed in the README under [Known limitations](README.md#known-limitations) and in the architecture docs. They include JWTs kept in `localStorage`, an endpoint that returns the user's decrypted GitHub token to the browser, and a WebSocket consumer that doesn't check review ownership (WebSockets aren't served today). The trade-offs behind these choices are discussed in [Architectural Decisions](docs/SYSTEM_ARCHITECTURE.md#12-architectural-decisions).
