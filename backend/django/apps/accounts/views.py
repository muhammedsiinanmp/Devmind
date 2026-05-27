from django.conf import settings
from django.db.models import F
import httpx
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.oauth import (
    OAuthError,
    exchange_code_for_token,
    generate_oauth_state,
    get_github_user,
    upsert_user,
    validate_oauth_state,
)
from apps.accounts.models import UserLLMConfig
from apps.accounts.serializers import (
    UserSerializer,
    UserLLMConfigSerializer,
    UserLLMConfigCreateSerializer,
    UserLLMConfigTestSerializer,
)


def _provider_test_request(
    provider: str, api_key: str, base_url: str
) -> tuple[str, dict[str, str]] | tuple[None, None]:
    provider = provider.strip().lower()

    if provider == "openai":
        return (base_url or "https://api.openai.com/v1/models"), {
            "Authorization": f"Bearer {api_key}"
        }
    if provider == "anthropic":
        return (base_url or "https://api.anthropic.com/v1/models"), {
            "x-api-key": api_key,
            "anthropic-version": "2023-01-01",
        }
    if provider == "groq":
        return (base_url or "https://api.groq.com/openai/v1/models"), {
            "Authorization": f"Bearer {api_key}"
        }
    if provider == "mistral":
        return (base_url or "https://api.mistral.ai/v1/models"), {
            "Authorization": f"Bearer {api_key}"
        }
    if provider == "google_vertex":
        endpoint = base_url or "https://generativelanguage.googleapis.com/v1beta/openai"
        return (f"{endpoint.rstrip('/')}/models"), {
            "Authorization": f"Bearer {api_key}"
        }
    if provider == "custom":
        if not base_url:
            return None, None
        return (f"{base_url.rstrip('/')}/models"), {
            "Authorization": f"Bearer {api_key}"
        }
    return None, None


def _validate_provider_key(
    provider: str,
    model_name: str,
    api_key: str,
    base_url: str = "",
) -> tuple[bool, dict]:
    if not api_key:
        return False, {"error": "api_key is required"}

    test_url, headers = _provider_test_request(provider, api_key, base_url)
    if not test_url or not headers:
        if provider.strip().lower() == "custom" and not base_url:
            return False, {"error": "base_url required for custom provider"}
        return False, {"error": f"Unsupported provider: {provider}"}

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(test_url, headers=headers)

        if response.status_code == 200:
            return True, {
                "status": "ok",
                "message": f"Successfully validated {provider}/{model_name}",
            }
        if response.status_code in (401, 403):
            return False, {"error": "invalid_key", "message": "Invalid API key"}
        return False, {
            "error": "validation_failed",
            "message": f"Unexpected response: {response.status_code}",
        }
    except httpx.TimeoutException:
        return False, {"error": "timeout", "message": "Request timed out"}
    except httpx.HTTPError as exc:
        return False, {"error": "http_error", "message": str(exc)}
    except Exception as exc:
        return False, {"error": "unknown", "message": str(exc)}


class GitHubOAuthStartView(APIView):
    """
    Start the GitHub OAuth flow.

    GET /api/v1/auth/github/start/
    Returns: {"authorize_url": "https://github.com/login/oauth/authorize?..."}

    Generates a cryptographically random `state` token, stores it in
    Redis (TTL 10 min), and returns the full GitHub authorize URL.
    The frontend should redirect the user to this URL.
    """

    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        state = generate_oauth_state()
        authorize_url = (
            f"https://github.com/login/oauth/authorize"
            f"?client_id={settings.GITHUB_CLIENT_ID}"
            f"&scope=repo,user"
            f"&state={state}"
        )
        return Response({"authorize_url": authorize_url})


class GitHubOAuthCallbackView(APIView):
    """
    Handle GitHub OAuth callback.

    GET /api/v1/auth/github/callback/?code=XXXXX&state=YYYYY
    Validates the state token, exchanges the code for tokens,
    upserts the user, and returns a JWT access/refresh pair.
    """

    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        code = request.query_params.get("code")
        state = request.query_params.get("state")

        if not code:
            return Response(
                {"error": "Missing 'code' parameter"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not state or not validate_oauth_state(state):
            return Response(
                {"error": "Invalid or expired 'state' parameter"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token_data = exchange_code_for_token(code)
            github_user = get_github_user(token_data["access_token"])
            user = upsert_user(github_user, token_data)
        except OAuthError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            }
        )


class UserMeView(APIView):
    """
    Return the authenticated user's profile.

    GET /api/v1/auth/me/
    Requires: Bearer JWT in Authorization header.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: UserSerializer},
        summary="Get current user profile",
    )
    def get(self, request: Request) -> Response:
        assert request.user.is_authenticated  # nosec: B101 (used for mypy typing)
        serializer = UserSerializer(request.user)
        return Response(serializer.data)


class GitHubTokenView(APIView):
    """
    Return the user's stored GitHub access token.

    GET /api/v1/auth/github/token/
    Requires: Bearer JWT in Authorization header.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        assert request.user.is_authenticated
        try:
            token = request.user.github_token
            if not token or not token.access_token:
                return Response(
                    {
                        "error": "No GitHub token found. Please reconnect your GitHub account."
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )
            return Response({"access_token": token.access_token})
        except Exception:
            return Response(
                {
                    "error": "No GitHub token found. Please reconnect your GitHub account."
                },
                status=status.HTTP_404_NOT_FOUND,
            )


class LogoutView(APIView):
    """
    Invalidate a refresh token by blacklisting it.

    POST /api/v1/auth/logout/
    Body: {"refresh": "<refresh_token>"}
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={205: None},
        summary="Logout and blacklist refresh token",
    )
    def post(self, request: Request) -> Response:
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response(
                {"error": "Missing 'refresh' token in request body"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response(status=status.HTTP_205_RESET_CONTENT)
        except TokenError:
            return Response(
                {"error": "Invalid or already blacklisted token"},
                status=status.HTTP_400_BAD_REQUEST,
            )


class LLMConfigListCreateView(APIView):
    """
    List or create user's LLM API key configurations.

    GET /api/v1/settings/llm/
    POST /api/v1/settings/llm/
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        configs = UserLLMConfig.objects.filter(user=request.user)
        serializer = UserLLMConfigSerializer(configs, many=True)
        return Response(serializer.data)

    def post(self, request: Request) -> Response:
        serializer = UserLLMConfigCreateSerializer(data=request.data)
        if serializer.is_valid():
            # Validate key before saving, unless explicitly disabled (tests/local harness).
            if not getattr(settings, "SKIP_LLM_KEY_VALIDATION", False):
                ok, payload = _validate_provider_key(
                    provider=serializer.validated_data["provider"],
                    model_name=serializer.validated_data["model_name"],
                    api_key=serializer.validated_data["api_key"],
                    base_url=serializer.validated_data.get("base_url", ""),
                )
                if not ok:
                    return Response(payload, status=status.HTTP_400_BAD_REQUEST)

            config = serializer.save(user=request.user)
            response_serializer = UserLLMConfigSerializer(config)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LLMConfigDetailView(APIView):
    """
    Retrieve, update, or delete a specific LLM config.

    GET /api/v1/settings/llm/{id}/
    DELETE /api/v1/settings/llm/{id}/
    PATCH /api/v1/settings/llm/{id}/
    """

    permission_classes = [IsAuthenticated]

    def get_object(self, pk: int, user) -> UserLLMConfig:
        try:
            return UserLLMConfig.objects.get(pk=pk, user=user)
        except UserLLMConfig.DoesNotExist:
            return None

    def get(self, request: Request, pk: int) -> Response:
        config = self.get_object(pk, request.user)
        if not config:
            return Response(
                {"error": "Config not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = UserLLMConfigSerializer(config)
        return Response(serializer.data)

    def delete(self, request: Request, pk: int) -> Response:
        config = self.get_object(pk, request.user)
        if not config:
            return Response(
                {"error": "Config not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        config.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def patch(self, request: Request, pk: int) -> Response:
        config = self.get_object(pk, request.user)
        if not config:
            return Response(
                {"error": "Config not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        # Don't allow updating api_key through PATCH
        data = request.data.copy()
        data.pop("api_key", None)

        serializer = UserLLMConfigSerializer(config, data=data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def post(self, request: Request, pk: int) -> Response:
        config = self.get_object(pk, request.user)
        if not config:
            return Response(
                {"error": "Config not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        UserLLMConfig.objects.filter(user=request.user).exclude(pk=pk).update(
            priority=F("priority") + 1
        )
        config.priority = 0
        config.save()

        serializer = UserLLMConfigSerializer(config)
        return Response(serializer.data)


class LLMConfigTestView(APIView):
    """
    Test an LLM API key without saving.

    POST /api/v1/settings/llm/test/
    Body: {"provider": "openai", "model_name": "gpt-4o", "api_key": "...", "base_url": ""}
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = UserLLMConfigTestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        provider = serializer.validated_data["provider"]
        model_name = serializer.validated_data["model_name"]
        api_key = serializer.validated_data.get("api_key", "")
        base_url = serializer.validated_data.get("base_url", "")

        # If config_id provided and api_key is empty, fetch the real key
        config_id = request.data.get("config_id")
        if config_id and not api_key:
            try:
                config = UserLLMConfig.objects.get(pk=config_id, user=request.user)
                api_key = config.api_key  # Returns decrypted key via EncryptedCharField
            except UserLLMConfig.DoesNotExist:
                return Response(
                    {"error": "Config not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )

        if not api_key:
            return Response(
                {"error": "api_key is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ok, payload = _validate_provider_key(
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            base_url=base_url,
        )
        if ok:
            return Response(payload)
        return Response(payload, status=status.HTTP_400_BAD_REQUEST)


class InternalLLMConfigListView(APIView):
    """
    Internal endpoint for FastAPI BYOK chain resolution.

    GET /api/v1/auth/internal/llm-configs/?user_id={id}
    Header: X-Internal-Secret
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request: Request) -> Response:
        internal_secret = request.headers.get("X-Internal-Secret", "")
        expected = getattr(settings, "FASTAPI_INTERNAL_SECRET", "")
        if not expected or internal_secret != expected:
            return Response({"error": "forbidden"}, status=status.HTTP_403_FORBIDDEN)

        user_id = request.query_params.get("user_id")
        if not user_id:
            return Response([], status=status.HTTP_200_OK)

        configs = (
            UserLLMConfig.objects.filter(user_id=user_id, is_active=True)
            .order_by("priority", "-created_at")
            .all()
        )

        data = [
            {
                "provider": cfg.provider,
                "model_name": cfg.model_name,
                "api_key": cfg.api_key,
                "base_url": cfg.base_url,
                "priority": cfg.priority,
            }
            for cfg in configs
        ]
        return Response(data, status=status.HTTP_200_OK)
