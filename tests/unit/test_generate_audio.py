"""
tests/unit/test_generate_audio.py

Unit tests for the GenerateAudio Lambda handler.
AWS services are mocked with moto; OpenAI TTS calls are mocked with unittest.mock.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree as ET

import boto3
import pytest
from moto import mock_aws

os.environ.setdefault("S3_BUCKET_NAME", "test-news-summaries")
os.environ.setdefault("DYNAMODB_TABLE_NAME", "test-news-summaries-episodes")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-key")
os.environ.setdefault("CLOUDFRONT_DOMAIN", "test.cloudfront.net")
os.environ.setdefault("PODCAST_TITLE", "Test Podcast")
os.environ.setdefault("PODCAST_DESCRIPTION", "A test podcast")
os.environ.setdefault("PODCAST_AUTHOR", "Test Author")
os.environ.setdefault("PODCAST_EMAIL", "test@example.com")
os.environ.setdefault("LOG_LEVEL", "DEBUG")

FAKE_MP3_BYTES = b"ID3\x03\x00\x00\x00" + b"\xff" * 200  # minimal fake MP3 header


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def _make_tts_mock() -> MagicMock:
    """Return a mock openai_client whose audio.speech.create streams fake MP3 bytes."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    # Simulate the iter_bytes() streaming interface
    mock_response.iter_bytes.return_value = iter([FAKE_MP3_BYTES])
    mock_client.audio.speech.create.return_value = mock_response
    return mock_client


def _make_dynamo_stream_event(episode: dict) -> dict:
    """Wrap an episode dict in a DynamoDB Streams INSERT event payload."""
    from boto3.dynamodb.types import TypeSerializer

    serializer = TypeSerializer()
    new_image = {k: serializer.serialize(v) for k, v in episode.items()}
    return {
        "Records": [
            {
                "eventName": "INSERT",
                "dynamodb": {
                    "SequenceNumber": "1234567890",
                    "NewImage": new_image,
                },
            }
        ]
    }


# ─────────────────────────────────────────────
# Tests: TTS API integration
# ─────────────────────────────────────────────


class TestTtsApiIntegration:
    """Tests for _generate_tts_with_retry."""

    def test_generates_audio_bytes(self) -> None:
        """Should return bytes from the TTS API response stream."""
        from src.generate_audio import handler as h

        mock_client = _make_tts_mock()
        with patch.object(h, "openai_client", mock_client):
            result = h._generate_tts_with_retry("Hello, world! This is a test.")

        assert isinstance(result, bytes)
        assert len(result) > 0
        mock_client.audio.speech.create.assert_called_once()

    def test_passes_correct_model_and_voice(self) -> None:
        """Should use tts-1 model and nova voice."""
        from src.generate_audio import handler as h

        mock_client = _make_tts_mock()
        with patch.object(h, "openai_client", mock_client):
            h._generate_tts_with_retry("Test text.")

        call_kwargs = mock_client.audio.speech.create.call_args
        assert call_kwargs.kwargs["model"] == "tts-1"
        assert call_kwargs.kwargs["voice"] == "nova"
        assert call_kwargs.kwargs["response_format"] == "mp3"

    def test_truncates_long_text(self) -> None:
        """Input text longer than 4096 characters should be truncated."""
        from src.generate_audio import handler as h

        mock_client = _make_tts_mock()
        long_text = "A" * 5000
        with patch.object(h, "openai_client", mock_client):
            h._generate_tts_with_retry(long_text)

        call_kwargs = mock_client.audio.speech.create.call_args
        assert len(call_kwargs.kwargs["input"]) == 4096

    def test_retries_on_rate_limit(self) -> None:
        """Should retry on RateLimitError and succeed on the second attempt."""
        from openai import RateLimitError

        from src.generate_audio import handler as h

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.iter_bytes.return_value = iter([FAKE_MP3_BYTES])

        mock_client.audio.speech.create.side_effect = [
            RateLimitError("rate limit", response=MagicMock(status_code=429), body={}),
            mock_response,
        ]

        with patch.object(h, "openai_client", mock_client), patch("time.sleep"):
            result = h._generate_tts_with_retry("Test text.")

        assert mock_client.audio.speech.create.call_count == 2
        assert isinstance(result, bytes)

    def test_raises_after_max_retries_exhausted(self) -> None:
        """Should raise an exception after all retries are exhausted."""
        from openai import RateLimitError

        from src.generate_audio import handler as h

        mock_client = MagicMock()
        mock_client.audio.speech.create.side_effect = RateLimitError(
            "rate limit", response=MagicMock(status_code=429), body={}
        )

        with patch.object(h, "openai_client", mock_client), patch("time.sleep"):
            with pytest.raises(RateLimitError):
                h._generate_tts_with_retry("Test text.")


# ─────────────────────────────────────────────
# Tests: Audio storage
# ─────────────────────────────────────────────


class TestAudioStorage:
    """Tests for _store_audio."""

    @mock_aws
    def test_stores_mp3_in_s3(self) -> None:
        """Should store audio bytes in S3 with audio/mpeg content type."""
        from src.generate_audio import handler as h

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-news-summaries")

        audio_key = "audio/2024-01-15/test-episode.mp3"
        with patch.object(h, "s3_client", s3):
            h._store_audio(audio_key, FAKE_MP3_BYTES)

        obj = s3.get_object(Bucket="test-news-summaries", Key=audio_key)
        assert obj["Body"].read() == FAKE_MP3_BYTES
        assert obj["ContentType"] == "audio/mpeg"

    @mock_aws
    def test_audio_stored_with_cache_control(self) -> None:
        """Audio objects should have a Cache-Control header for CDN caching."""
        from src.generate_audio import handler as h

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-news-summaries")

        with patch.object(h, "s3_client", s3):
            h._store_audio("audio/2024-01-15/test.mp3", FAKE_MP3_BYTES)

        obj = s3.get_object(
            Bucket="test-news-summaries", Key="audio/2024-01-15/test.mp3"
        )
        assert "max-age" in obj["CacheControl"]


# ─────────────────────────────────────────────
# Tests: RSS feed generation
# ─────────────────────────────────────────────


class TestRssFeedGeneration:
    """Tests for _build_rss_xml and _regenerate_rss_feed."""

    def test_build_rss_xml_produces_valid_xml(self) -> None:
        """Should produce parseable XML."""
        from src.generate_audio.handler import _build_rss_xml

        episodes = [
            {
                "episode_id": "uuid-1",
                "title": "Episode One",
                "summary": "Summary of episode one.",
                "audio_url": "https://test.cloudfront.net/audio/2024-01-15/uuid-1.mp3",
                "created_at": "2024-01-15T06:00:00+00:00",
            }
        ]

        xml_bytes = _build_rss_xml(episodes)
        root = ET.fromstring(xml_bytes)
        assert root.tag == "rss"
        assert root.attrib["version"] == "2.0"

    def test_build_rss_xml_contains_channel_metadata(self) -> None:
        """The RSS feed should include the podcast title and description."""
        from src.generate_audio.handler import _build_rss_xml

        xml_bytes = _build_rss_xml([])
        decoded = xml_bytes.decode("utf-8")
        assert "Test Podcast" in decoded

    def test_build_rss_xml_includes_all_episodes(self) -> None:
        """All provided episodes should appear as <item> elements."""
        from src.generate_audio.handler import _build_rss_xml

        episodes = [
            {
                "episode_id": f"uuid-{i}",
                "title": f"Episode {i}",
                "summary": f"Summary {i}",
                "audio_url": f"https://test.cloudfront.net/audio/ep{i}.mp3",
                "created_at": "2024-01-15T06:00:00+00:00",
            }
            for i in range(5)
        ]

        xml_bytes = _build_rss_xml(episodes)
        root = ET.fromstring(xml_bytes)
        channel = root.find("channel")
        items = channel.findall("item")
        assert len(items) == 5

    def test_build_rss_xml_enclosure_has_correct_type(self) -> None:
        """Each <enclosure> element must declare audio/mpeg type."""
        from src.generate_audio.handler import _build_rss_xml

        episodes = [
            {
                "episode_id": "uuid-1",
                "title": "Test",
                "summary": "Summary",
                "audio_url": "https://cdn.example.com/ep.mp3",
                "created_at": "2024-01-15T06:00:00+00:00",
            }
        ]

        xml_bytes = _build_rss_xml(episodes)
        root = ET.fromstring(xml_bytes)
        enclosure = root.find(".//enclosure")
        assert enclosure is not None
        assert enclosure.attrib["type"] == "audio/mpeg"
        assert enclosure.attrib["url"] == "https://cdn.example.com/ep.mp3"

    @mock_aws
    def test_regenerate_rss_feed_uploads_to_s3(self) -> None:
        """_regenerate_rss_feed should upload feed.xml to S3."""
        from src.generate_audio import handler as h

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-news-summaries")

        # Provide a mock list of episodes with audio
        mock_episodes = [
            {
                "episode_id": "uuid-1",
                "date": "2024-01-15",
                "title": "Test Episode",
                "summary": "A short summary.",
                "audio_url": "https://test.cloudfront.net/audio/2024-01-15/uuid-1.mp3",
                "created_at": "2024-01-15T06:00:00+00:00",
            }
        ]

        with (
            patch.object(h, "s3_client", s3),
            patch.object(
                h, "_get_recent_episodes_with_audio", return_value=mock_episodes
            ),
        ):
            h._regenerate_rss_feed()

        obj = s3.get_object(Bucket="test-news-summaries", Key="rss/feed.xml")
        content = obj["Body"].read()
        assert b"<rss" in content
        assert b"Test Episode" in content


# ─────────────────────────────────────────────
# Tests: Lambda handler (DynamoDB Streams)
# ─────────────────────────────────────────────


class TestLambdaHandler:
    """Tests for the GenerateAudio lambda_handler with DynamoDB Stream events."""

    @mock_aws
    def test_handler_processes_insert_event(self, sample_summary_doc: dict) -> None:
        """Handler should process an INSERT event and generate audio."""
        from src.generate_audio import handler as h

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-news-summaries")

        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = ddb.create_table(
            TableName="test-news-summaries-episodes",
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "episode_id", "AttributeType": "S"},
                {"AttributeName": "date", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "episode_id", "KeyType": "HASH"},
                {"AttributeName": "date", "KeyType": "RANGE"},
            ],
        )
        # Put the episode into DynamoDB
        table.put_item(Item=sample_summary_doc)

        event = _make_dynamo_stream_event(sample_summary_doc)
        mock_tts = _make_tts_mock()

        with (
            patch.object(h, "openai_client", mock_tts),
            patch.object(h, "s3_client", s3),
            patch.object(h, "episodes_table", table),
            patch.object(h, "_regenerate_rss_feed"),
        ):
            result = h.lambda_handler(event, MagicMock())

        assert result["batchItemFailures"] == []

    def test_handler_skips_non_insert_events(self) -> None:
        """MODIFY and REMOVE events should be skipped silently."""
        from src.generate_audio import handler as h

        event = {
            "Records": [
                {
                    "eventName": "MODIFY",
                    "dynamodb": {"SequenceNumber": "123", "NewImage": {}},
                },
                {
                    "eventName": "REMOVE",
                    "dynamodb": {"SequenceNumber": "456", "NewImage": {}},
                },
            ]
        }

        with patch.object(h, "openai_client", _make_tts_mock()):
            result = h.lambda_handler(event, MagicMock())

        assert result["batchItemFailures"] == []

    def test_handler_returns_failed_sequence_numbers_on_error(self) -> None:
        """Failures should appear in batchItemFailures for DLQ retry."""
        # Create a minimal INSERT event with an episode that has no summary
        from boto3.dynamodb.types import TypeSerializer

        from src.generate_audio import handler as h

        serializer = TypeSerializer()
        broken_episode = {"episode_id": "broken-uuid", "date": "2024-01-15"}
        new_image = {k: serializer.serialize(v) for k, v in broken_episode.items()}

        event = {
            "Records": [
                {
                    "eventName": "INSERT",
                    "dynamodb": {
                        "SequenceNumber": "seq-999",
                        "NewImage": new_image,
                    },
                }
            ]
        }

        # Force TTS to raise so the record is marked as failed
        mock_client = MagicMock()
        mock_client.audio.speech.create.side_effect = RuntimeError("TTS unavailable")

        with (
            patch.object(h, "openai_client", mock_client),
            patch("time.sleep"),
        ):
            result = h.lambda_handler(event, MagicMock())

        assert len(result["batchItemFailures"]) == 1
        assert result["batchItemFailures"][0]["itemIdentifier"] == "seq-999"
