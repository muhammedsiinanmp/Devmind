import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "devmind.settings.production")

django_asgi_app = get_asgi_application()

from realtime.auth import JwtQueryAuthMiddleware
from realtime.routing import websocket_urlpatterns

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(
                JwtQueryAuthMiddleware(URLRouter(websocket_urlpatterns))
            )
        ),
    }
)
