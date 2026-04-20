from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
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
from apps.accounts.serializers import UserSerializer


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

    def get(self, request):
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

    def get(self, request):
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

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)


class LogoutView(APIView):
    """
    Invalidate a refresh token by blacklisting it.

    POST /api/v1/auth/logout/
    Body: {"refresh": "<refresh_token>"}
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
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
