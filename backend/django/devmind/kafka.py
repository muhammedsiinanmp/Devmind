"""
Kafka producer for DevMind events.

Fire-and-forget producer that logs errors but doesn't block the main thread.
"""

import json
import logging
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

TOPIC_PR_OPENED = "devmind.pr.opened"
TOPIC_PR_MERGED = "devmind.pr.merged"
TOPIC_REVIEW_REQUESTED = "devmind.review.requested"
TOPIC_REVIEW_COMPLETED = "devmind.review.completed"
TOPIC_REPO_INDEXED = "devmind.repo.indexed"
TOPIC_CVE_DETECTED = "devmind.cve.detected"
TOPIC_DIGEST_GENERATE = "devmind.digest.generate"

_producer: Any = None


def _get_producer() -> Any:
    """Get or create the Kafka producer singleton."""
    global _producer
    if _producer is not None:
        return _producer

    bootstrap_servers = getattr(settings, "KAFKA_BOOTSTRAP_SERVERS", "")

    if not bootstrap_servers:
        logger.warning("kafka.bootstrap_servers_not_configured")
        return None

    try:
        from confluent_kafka import Producer

        config = {
            "bootstrap.servers": bootstrap_servers,
            "client.id": "devmind-django",
        }

        _producer = Producer(config)
        logger.info(
            "kafka.producer_initialized bootstrap_servers=%s", bootstrap_servers
        )
        return _producer

    except Exception as e:
        logger.error("kafka.producer_init_failed error=%s", str(e))
        return None


def _delivery_callback(err: Any, msg: Any) -> None:
    """Callback for message delivery reports."""
    if err is not None:
        logger.error("kafka.delivery_failed topic=%s error=%s", msg.topic(), str(err))
    else:
        logger.debug(
            "kafka.delivery_success topic=%s partition=%d offset=%d",
            msg.topic(),
            msg.partition(),
            msg.offset(),
        )


def produce(topic: str, payload: dict[str, Any]) -> bool:
    """
    Produce a message to a Kafka topic.

    Fire-and-forget: logs errors but doesn't raise exceptions.

    Args:
        topic: Kafka topic name
        payload: Message payload dict (will be JSON serialized)

    Returns:
        True if message was produced, False otherwise
    """
    bootstrap_servers = getattr(settings, "KAFKA_BOOTSTRAP_SERVERS", "")

    if not bootstrap_servers:
        logger.debug("kafka.disabled skipping_produce topic=%s", topic)
        return False

    producer = _get_producer()
    if producer is None:
        logger.warning("kafka.producer_unavailable skipping_produce topic=%s", topic)
        return False

    try:
        message = json.dumps(payload, default=str)
        producer.produce(
            topic,
            value=message.encode("utf-8"),
            callback=_delivery_callback,
        )
        producer.poll(0)
        logger.debug("kafka.produce_queued topic=%s", topic)
        return True

    except Exception as e:
        logger.error("kafka.produce_failed topic=%s error=%s", topic, str(e))
        return False


def flush(timeout: float = 5.0) -> None:
    """Flush pending messages. Call on shutdown."""
    global _producer
    if _producer is not None:
        try:
            _producer.flush(timeout)
        except Exception as e:
            logger.error("kafka.flush_failed error=%s", str(e))
