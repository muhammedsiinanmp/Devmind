import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings

from .events import ReviewEventType, get_review_group

logger = logging.getLogger(__name__)


class ReviewStatusConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.review_id = self.scope["url_route"]["kwargs"].get("review_id")
        self.user = self.scope.get("user")

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4003)
            return

        self.group_name = get_review_group(self.review_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        logger.info(
            f"WebSocket connected: review={self.review_id}, user={self.user.id}"
        )

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            logger.info(f"WebSocket disconnected: review={self.review_id}")

    async def receive(self, text_data):
        pass

    async def review_status_update(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": ReviewEventType.STATUS_CHANGED,
                    "review_id": event["review_id"],
                    "status": event["status"],
                    "message": event.get("message", ""),
                }
            )
        )

    async def review_completed(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": ReviewEventType.COMPLETED,
                    "review_id": event["review_id"],
                    "status": event["status"],
                    "summary": event.get("summary", {}),
                }
            )
        )

    async def review_failed(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": ReviewEventType.FAILED,
                    "review_id": event["review_id"],
                    "status": event["status"],
                    "error": event.get("error", ""),
                }
            )
        )


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope.get("user")

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4003)
            return

        self.group_name = f"notifications_{self.user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        logger.info(f"WebSocket connected: notifications for user={self.user.id}")

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        pass

    async def notification_new(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": "notification.new",
                    "notification_id": event["notification_id"],
                    "title": event.get("title", ""),
                    "message": event.get("message", ""),
                }
            )
        )
