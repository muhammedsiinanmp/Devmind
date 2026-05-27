import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

logger = logging.getLogger(__name__)

User = get_user_model()


class JwtQueryAuthMiddleware:
    """
    Authenticate WebSocket connections via JWT token in the query string.

    Reads ``?token=<access_token>`` from the WebSocket URL, validates it
    with ``rest_framework_simplejwt``, and sets ``scope["user"]``.

    Intended to wrap (run *after*) ``AuthMiddlewareStack`` so that
    session-based auth is tried first and JWT overrides it when present.
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode("utf-8")
        params = parse_qs(query_string)
        token_str = params.get("token", [None])[0]

        if token_str:
            try:
                token = AccessToken(token_str)
                user_id = token.payload.get("user_id")
                if user_id is not None:
                    user = await self._get_user(user_id)
                    if user and user.is_active:
                        scope["user"] = user
                        logger.debug(
                            "JWT auth succeeded for user=%s (ws path=%s)",
                            user.id,
                            scope.get("path", ""),
                        )
            except TokenError as exc:
                logger.warning("JWT auth failed: %s", exc)

        return await self.inner(scope, receive, send)

    async def _get_user(self, user_id: int):
        try:
            return await _get_user_async(user_id)
        except User.DoesNotExist:
            return None


@database_sync_to_async
def _get_user_async(user_id: int):
    return User.objects.get(pk=user_id)
