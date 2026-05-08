"""
Tests for Kafka producer.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from django.test import override_settings

from devmind.kafka import (
    produce,
    TOPIC_REVIEW_COMPLETED,
    TOPIC_PR_OPENED,
    TOPIC_PR_CLOSED,
    TOPIC_SCAN_COMPLETED,
    TOPIC_USER_CREATED,
    TOPIC_REPO_CONNECTED,
    TOPIC_WEBHOOK_RECEIVED,
)


class TestTopicConstants:
    def test_all_topics_defined(self):
        assert TOPIC_REVIEW_COMPLETED == "devmind.review.completed"
        assert TOPIC_PR_OPENED == "devmind.pr.opened"
        assert TOPIC_PR_CLOSED == "devmind.pr.closed"
        assert TOPIC_SCAN_COMPLETED == "devmind.scan.completed"
        assert TOPIC_USER_CREATED == "devmind.user.created"
        assert TOPIC_REPO_CONNECTED == "devmind.repo.connected"
        assert TOPIC_WEBHOOK_RECEIVED == "devmind.webhook.received"


class TestProduceWithEmptyBootstrapServers:
    @override_settings(KAFKA_BOOTSTRAP_SERVERS="")
    def test_produce_returns_false_when_disabled(self):
        result = produce("test.topic", {"key": "value"})
        assert result is False

    @override_settings(KAFKA_BOOTSTRAP_SERVERS="")
    def test_produce_returns_false_when_not_configured(self):
        with patch("devmind.kafka._get_producer") as mock_get:
            result = produce("test.topic", {"key": "value"})
            assert result is False
            mock_get.assert_not_called()


class TestProduceWithBootstrapServers:
    @override_settings(KAFKA_BOOTSTRAP_SERVERS="kafka:9092")
    @patch("devmind.kafka._get_producer")
    def test_produce_calls_producer(self, mock_get_producer):
        import devmind.kafka as kafka_module

        kafka_module._producer = None

        mock_producer = MagicMock()
        mock_get_producer.return_value = mock_producer

        payload = {"review_id": 1, "status": "completed"}
        result = produce(TOPIC_REVIEW_COMPLETED, payload)

        assert result is True
        mock_producer.produce.assert_called_once()
        mock_producer.poll.assert_called_once_with(0)

    @override_settings(KAFKA_BOOTSTRAP_SERVERS="kafka:9092")
    @patch("devmind.kafka._get_producer")
    def test_produce_with_review_completed_topic(self, mock_get_producer):
        import devmind.kafka as kafka_module

        kafka_module._producer = None

        mock_producer = MagicMock()
        mock_get_producer.return_value = mock_producer

        payload = {
            "review_id": 42,
            "repository_full_name": "owner/repo",
            "pr_number": 1,
            "status": "completed",
            "risk_score": 25,
        }
        result = produce(TOPIC_REVIEW_COMPLETED, payload)

        assert result is True
        call_args = mock_producer.produce.call_args
        assert call_args[0][0] == TOPIC_REVIEW_COMPLETED

    @override_settings(KAFKA_BOOTSTRAP_SERVERS="kafka:9092")
    @patch("devmind.kafka._get_producer")
    def test_produce_with_pr_opened_topic(self, mock_get_producer):
        import devmind.kafka as kafka_module

        kafka_module._producer = None

        mock_producer = MagicMock()
        mock_get_producer.return_value = mock_producer

        payload = {
            "repository_full_name": "owner/repo",
            "pr_number": 5,
            "head_sha": "abc123",
            "action": "opened",
        }
        result = produce(TOPIC_PR_OPENED, payload)

        assert result is True
        call_args = mock_producer.produce.call_args
        assert call_args[0][0] == TOPIC_PR_OPENED


class TestGetProducer:
    @override_settings(KAFKA_BOOTSTRAP_SERVERS="kafka:9092")
    def test_get_producer_returns_none_when_bootstrap_empty(self):
        import devmind.kafka

        devmind.kafka._producer = None

        with override_settings(KAFKA_BOOTSTRAP_SERVERS=""):
            from devmind.kafka import _get_producer

            producer = _get_producer()

            assert producer is None

    @override_settings(KAFKA_BOOTSTRAP_SERVERS="kafka:9092")
    def test_get_producer_uses_cached_producer(self):
        import devmind.kafka

        mock_existing = MagicMock()
        devmind.kafka._producer = mock_existing

        from devmind.kafka import _get_producer

        producer = _get_producer()

        assert producer is mock_existing

    @override_settings(KAFKA_BOOTSTRAP_SERVERS="kafka:9092")
    @patch("confluent_kafka.Producer")
    def test_get_producer_handles_exception(self, mock_producer_class):
        import devmind.kafka

        devmind.kafka._producer = None

        mock_producer_class.side_effect = Exception("Connection failed")

        from devmind.kafka import _get_producer

        producer = _get_producer()

        assert producer is None


class TestDeliveryCallback:
    def test_delivery_callback_on_success(self):
        from devmind.kafka import _delivery_callback

        mock_msg = MagicMock()
        mock_msg.topic.return_value = "test.topic"
        mock_msg.partition.return_value = 0
        mock_msg.offset.return_value = 123

        _delivery_callback(None, mock_msg)

    def test_delivery_callback_on_error(self):
        from devmind.kafka import _delivery_callback

        mock_msg = MagicMock()
        mock_msg.topic.return_value = "test.topic"

        error = Exception("Delivery failed")
        _delivery_callback(error, mock_msg)


class TestProduceJsonSerialization:
    @override_settings(KAFKA_BOOTSTRAP_SERVERS="kafka:9092")
    @patch("devmind.kafka._get_producer")
    def test_produce_serializes_datetime_to_isoformat(self, mock_get_producer):
        import devmind.kafka

        devmind.kafka._producer = None

        mock_producer = MagicMock()
        mock_get_producer.return_value = mock_producer

        from datetime import datetime

        payload = {"created_at": datetime(2025, 5, 7, 10, 30, 0)}
        produce("test.topic", payload)

        call_args = mock_producer.produce.call_args
        message = call_args[1]["value"].decode("utf-8")
        assert "2025-05-07 10:30:00" in message

    @override_settings(KAFKA_BOOTSTRAP_SERVERS="kafka:9092")
    @patch("devmind.kafka._get_producer")
    def test_produce_handles_nested_objects(self, mock_get_producer):
        import devmind.kafka

        devmind.kafka._producer = None

        mock_producer = MagicMock()
        mock_get_producer.return_value = mock_producer

        payload = {
            "review": {
                "id": 1,
                "status": "completed",
                "comments": [{"line": 10, "severity": "error"}],
            }
        }
        produce("test.topic", payload)

        mock_producer.produce.assert_called_once()


class TestProduceHandlesProducerErrors:
    @override_settings(KAFKA_BOOTSTRAP_SERVERS="kafka:9092")
    @patch("devmind.kafka._get_producer")
    def test_produce_returns_false_on_exception(self, mock_get_producer):
        mock_producer = MagicMock()
        mock_producer.produce.side_effect = Exception("Kafka error")
        mock_get_producer.return_value = mock_producer

        result = produce("test.topic", {"key": "value"})

        assert result is False
