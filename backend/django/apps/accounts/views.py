from django.conf import settings
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
        api_key = serializer.validated_data["api_key"]
        base_url = serializer.validated_data.get("base_url", "")

        # Test the API key based on provider
        try:
            if provider == "openai":
                test_url = base_url or "https://api.openai.com/v1/models"
                headers = {"Authorization": f"Bearer {api_key}"}
            elif provider == "anthropic":
                test_url = base_url or "https://api.anthropic.com/v1/models"
                headers = {
                    "x-api-key": api_key,
                    "anthropic-version": "2023-01-01",
                }
            elif provider == "groq":
                test_url = base_url or "https://api.groq.com/openai/v1/models"
                headers = {"Authorization": f"Bearer {api_key}"}
            elif provider == "custom":
                if not base_url:
                    return Response(
                        {"error": "base_url required for custom provider"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                test_url = f"{base_url.rstrip('/')}/models"
                headers = {"Authorization": f"Bearer {api_key}"}
            else:
                return Response(
                    {"error": f"Unsupported provider: {provider}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            with httpx.Client(timeout=10.0) as client:
                response = client.get(test_url, headers=headers)

                if response.status_code == 200:
                    return Response(
                        {
                            "status": "ok",
                            "message": f"Successfully validated {provider}/{model_name}",
                        }
                    )
                elif response.status_code in (401, 403):
                    return Response(
                        {"error": "invalid_key", "message": "Invalid API key"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                else:
                    return Response(
                        {
                            "error": "validation_failed",
                            "message": f"Unexpected response: {response.status_code}",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        except httpx.TimeoutException:
            return Response(
                {"error": "timeout", "message": "Request timed out"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except httpx.HTTPError as e:
            return Response(
                {"error": "http_error", "message": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            return Response(
                {"error": "unknown", "message": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
