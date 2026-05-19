import json
from unittest.mock import AsyncMock, patch

import pytest
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from channels.auth import AuthMiddlewareStack

from realtime.routing import websocket_urlpatterns

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(email="test@example.com", password="testpass123")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestReviewStatusConsumer:
    async def test_connect_authenticated(self, user, client):
        client.force_login(user)
        headers = [(b"cookie", f"sessionid={client.session.session_key}".encode())]
        application = AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        communicator = WebsocketCommunicator(
            application, "/ws/reviews/1/", headers=headers
        )
        connected, subprotocol = await communicator.connect()
        assert connected is True
        await communicator.disconnect()

    async def test_disconnect_cleanup(self, user, client):
        client.force_login(user)
        headers = [(b"cookie", f"sessionid={client.session.session_key}".encode())]
        application = AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        communicator = WebsocketCommunicator(
            application, "/ws/reviews/1/", headers=headers
        )
        await communicator.connect()
        await communicator.disconnect()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
class TestNotificationConsumer:
    async def test_connect_authenticated(self, user, client):
        client.force_login(user)
        headers = [(b"cookie", f"sessionid={client.session.session_key}".encode())]
        application = AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        communicator = WebsocketCommunicator(
            application, "/ws/notifications/", headers=headers
        )
        connected, subprotocol = await communicator.connect()
        assert connected is True
        await communicator.disconnect()
