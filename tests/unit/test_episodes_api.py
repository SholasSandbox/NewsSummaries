"""
tests/unit/test_episodes_api.py

Unit tests for the EpisodesAPI Lambda handler (Lambda 4 – Admin/Observability layer).
AWS services are mocked with moto.
"""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

# Set environment variables before importing the handler
os.environ.setdefault("S3_BUCKET_NAME", "test-news-summaries")
os.environ.setdefault("DYNAMODB_TABLE_NAME", "test-news-summaries-episodes")
os.environ.setdefault("ADMIN_API_KEY", "")          # auth disabled in tests
os.environ.setdefault("PRESIGNED_URL_EXPIRY_SECONDS", "3600")
os.environ.setdefault("LOG_LEVEL", "DEBUG")
os.environ.setdefault("CLOUDFRONT_DOMAIN", "test.cloudfront.net")
os.environ.setdefault("STAGE", "test")

TEST_BUCKET = "test-news-summaries"
TEST_TABLE = "test-news-summaries-episodes"
TEST_REGION = "us-east-1"

SAMPLE_EPISODE = {
    "episode_id": "test-episode-001",
    "date": "2024-01-15",
    "created_at": "2024-01-15T06:01:00+00:00",
    "title": "AI Makes Major Breakthrough",
    "source": "BBC",
    "url": "https://www.bbc.co.uk/news/tech-12345",
    "summary": "Scientists announce an AI breakthrough.",
    "category": "technology",
    "importance": "high",
    "keywords": ["AI", "science"],
    "status": "complete",
    "audio_url": "https://test.cloudfront.net/audio/2024-01-15/test-episode-001.mp3",
    "audio_s3_key": "audio/2024-01-15/test-episode-001.mp3",
    "summary_s3_key": "summaries/2024-01-15/abc123.json",
}


def _make_apigw_event(
    method: str = "GET",
    path: str = "/episodes",
    path_params: dict | None = None,
    query_params: dict | None = None,
    auth_header: str = "",
) -> dict:
    """Build a minimal API Gateway HTTP API v2 event."""
    return {
        "rawPath": path,
        "requestContext": {
            "http": {"method": method}
        },
        "pathParameters": path_params or {},
        "queryStringParameters": query_params or {},
        "headers": {"authorization": auth_header} if auth_header else {},
    }


def _make_table(dynamodb_resource: Any) -> Any:
    """Create the episodes table with required key schema."""
    return dynamodb_resource.create_table(
        TableName=TEST_TABLE,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "episode_id", "AttributeType": "S"},
            {"AttributeName": "date", "AttributeType": "S"},
            {"AttributeName": "created_at", "AttributeType": "S"},
            {"AttributeName": "category", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "episode_id", "KeyType": "HASH"},
            {"AttributeName": "date", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "date-created_at-index",
                "KeySchema": [
                    {"AttributeName": "date", "KeyType": "HASH"},
                    {"AttributeName": "created_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                "IndexName": "category-date-index",
                "KeySchema": [
                    {"AttributeName": "category", "KeyType": "HASH"},
                    {"AttributeName": "date", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
        ],
    )


# ─────────────────────────────────────────────
# Tests: List Episodes  GET /episodes
# ─────────────────────────────────────────────

class TestListEpisodes:

    @mock_aws
    def test_list_episodes_returns_200(self) -> None:
        """GET /episodes should return 200 with an episodes array."""
        ddb = boto3.resource("dynamodb", region_name=TEST_REGION)
        table = _make_table(ddb)
        table.put_item(Item=SAMPLE_EPISODE)

        from src.episodes_api import handler as h
        # Reload module-level clients to use mocked AWS
        h.dynamodb = ddb
        h.episodes_table = ddb.Table(TEST_TABLE)

        event = _make_apigw_event("GET", "/episodes")
        result = h.lambda_handler(event, {})

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "episodes" in body
        assert body["count"] >= 1

    @mock_aws
    def test_list_episodes_filter_by_date(self) -> None:
        """GET /episodes?date=YYYY-MM-DD should use the GSI."""
        ddb = boto3.resource("dynamodb", region_name=TEST_REGION)
        table = _make_table(ddb)
        table.put_item(Item=SAMPLE_EPISODE)
        # Different date – should not appear
        other = {**SAMPLE_EPISODE, "episode_id": "other-ep", "date": "2024-01-16"}
        table.put_item(Item=other)

        from src.episodes_api import handler as h
        h.dynamodb = ddb
        h.episodes_table = ddb.Table(TEST_TABLE)

        event = _make_apigw_event("GET", "/episodes", query_params={"date": "2024-01-15"})
        result = h.lambda_handler(event, {})

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["date_filter"] == "2024-01-15"
        assert all(ep["date"] == "2024-01-15" for ep in body["episodes"])

    @mock_aws
    def test_list_episodes_empty_table(self) -> None:
        """GET /episodes on an empty table should return an empty array."""
        ddb = boto3.resource("dynamodb", region_name=TEST_REGION)
        _make_table(ddb)

        from src.episodes_api import handler as h
        h.dynamodb = ddb
        h.episodes_table = ddb.Table(TEST_TABLE)

        event = _make_apigw_event("GET", "/episodes")
        result = h.lambda_handler(event, {})

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["episodes"] == []
        assert body["count"] == 0


# ─────────────────────────────────────────────
# Tests: Get Single Episode  GET /episodes/{id}
# ─────────────────────────────────────────────

class TestGetEpisode:

    @mock_aws
    def test_get_episode_returns_200(self) -> None:
        """GET /episodes/{id} should return the full episode metadata."""
        ddb = boto3.resource("dynamodb", region_name=TEST_REGION)
        table = _make_table(ddb)
        table.put_item(Item=SAMPLE_EPISODE)

        from src.episodes_api import handler as h
        h.dynamodb = ddb
        h.episodes_table = ddb.Table(TEST_TABLE)

        event = _make_apigw_event(
            "GET",
            f"/episodes/{SAMPLE_EPISODE['episode_id']}",
            path_params={"episode_id": SAMPLE_EPISODE["episode_id"]},
        )
        result = h.lambda_handler(event, {})

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["episode_id"] == SAMPLE_EPISODE["episode_id"]
        assert body["title"] == SAMPLE_EPISODE["title"]

    @mock_aws
    def test_get_episode_not_found_returns_404(self) -> None:
        """GET /episodes/{id} for an unknown ID should return 404."""
        ddb = boto3.resource("dynamodb", region_name=TEST_REGION)
        _make_table(ddb)

        from src.episodes_api import handler as h
        h.dynamodb = ddb
        h.episodes_table = ddb.Table(TEST_TABLE)

        event = _make_apigw_event(
            "GET",
            "/episodes/does-not-exist",
            path_params={"episode_id": "does-not-exist"},
        )
        result = h.lambda_handler(event, {})

        assert result["statusCode"] == 404
        body = json.loads(result["body"])
        assert "not found" in body["error"].lower()

    @mock_aws
    def test_get_episode_missing_id_returns_400(self) -> None:
        """GET /episodes/ with no ID should return 400."""
        ddb = boto3.resource("dynamodb", region_name=TEST_REGION)
        _make_table(ddb)

        from src.episodes_api import handler as h
        h.dynamodb = ddb
        h.episodes_table = ddb.Table(TEST_TABLE)

        event = _make_apigw_event(
            "GET",
            "/episodes/",
            path_params={"episode_id": ""},
        )
        result = h.lambda_handler(event, {})

        assert result["statusCode"] == 400


# ─────────────────────────────────────────────
# Tests: Presigned Audio URL  GET /episodes/{id}/audio
# ─────────────────────────────────────────────

class TestGetAudioUrl:

    @mock_aws
    def test_get_audio_url_returns_presigned_url(self) -> None:
        """GET /episodes/{id}/audio should return a presigned S3 URL."""
        ddb = boto3.resource("dynamodb", region_name=TEST_REGION)
        table = _make_table(ddb)
        table.put_item(Item=SAMPLE_EPISODE)

        s3 = boto3.client("s3", region_name=TEST_REGION)
        s3.create_bucket(Bucket=TEST_BUCKET)
        s3.put_object(
            Bucket=TEST_BUCKET,
            Key=SAMPLE_EPISODE["audio_s3_key"],
            Body=b"fake mp3",
        )

        from src.episodes_api import handler as h
        h.dynamodb = ddb
        h.episodes_table = ddb.Table(TEST_TABLE)
        h.s3_client = s3

        event = _make_apigw_event(
            "GET",
            f"/episodes/{SAMPLE_EPISODE['episode_id']}/audio",
            path_params={"episode_id": SAMPLE_EPISODE["episode_id"]},
        )
        result = h.lambda_handler(event, {})

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "audio_url" in body
        assert "expires_in_seconds" in body
        assert "https" in body["audio_url"]

    @mock_aws
    def test_get_audio_url_no_audio_yet_returns_404(self) -> None:
        """GET /episodes/{id}/audio when audio not yet generated should return 404."""
        ddb = boto3.resource("dynamodb", region_name=TEST_REGION)
        table = _make_table(ddb)
        # Episode without audio_s3_key
        episode_no_audio = {k: v for k, v in SAMPLE_EPISODE.items()
                            if k not in ("audio_url", "audio_s3_key")}
        table.put_item(Item=episode_no_audio)

        from src.episodes_api import handler as h
        h.dynamodb = ddb
        h.episodes_table = ddb.Table(TEST_TABLE)

        event = _make_apigw_event(
            "GET",
            f"/episodes/{SAMPLE_EPISODE['episode_id']}/audio",
            path_params={"episode_id": SAMPLE_EPISODE["episode_id"]},
        )
        result = h.lambda_handler(event, {})

        assert result["statusCode"] == 404
        body = json.loads(result["body"])
        assert "not yet generated" in body["error"]


# ─────────────────────────────────────────────
# Tests: Presigned Transcript URL  GET /episodes/{id}/transcript
# ─────────────────────────────────────────────

class TestGetTranscriptUrl:

    @mock_aws
    def test_get_transcript_url_returns_presigned_url(self) -> None:
        """GET /episodes/{id}/transcript should return a presigned S3 URL."""
        ddb = boto3.resource("dynamodb", region_name=TEST_REGION)
        table = _make_table(ddb)
        table.put_item(Item=SAMPLE_EPISODE)

        s3 = boto3.client("s3", region_name=TEST_REGION)
        s3.create_bucket(Bucket=TEST_BUCKET)
        s3.put_object(
            Bucket=TEST_BUCKET,
            Key=SAMPLE_EPISODE["summary_s3_key"],
            Body=b'{"summary": "test"}',
        )

        from src.episodes_api import handler as h
        h.dynamodb = ddb
        h.episodes_table = ddb.Table(TEST_TABLE)
        h.s3_client = s3

        event = _make_apigw_event(
            "GET",
            f"/episodes/{SAMPLE_EPISODE['episode_id']}/transcript",
            path_params={"episode_id": SAMPLE_EPISODE["episode_id"]},
        )
        result = h.lambda_handler(event, {})

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "transcript_url" in body
        assert "https" in body["transcript_url"]


# ─────────────────────────────────────────────
# Tests: Auth
# ─────────────────────────────────────────────

class TestAuthentication:

    @mock_aws
    def test_valid_api_key_passes(self) -> None:
        """A correct Authorization: Bearer <key> header should be accepted."""
        ddb = boto3.resource("dynamodb", region_name=TEST_REGION)
        _make_table(ddb)

        from src.episodes_api import handler as h
        h.dynamodb = ddb
        h.episodes_table = ddb.Table(TEST_TABLE)
        original_key = h.ADMIN_API_KEY
        h.ADMIN_API_KEY = "secret-key-123"

        try:
            event = _make_apigw_event("GET", "/episodes", auth_header="Bearer secret-key-123")
            result = h.lambda_handler(event, {})
            assert result["statusCode"] == 200
        finally:
            h.ADMIN_API_KEY = original_key

    @mock_aws
    def test_wrong_api_key_returns_401(self) -> None:
        """An incorrect API key should return 401 Unauthorized."""
        ddb = boto3.resource("dynamodb", region_name=TEST_REGION)
        _make_table(ddb)

        from src.episodes_api import handler as h
        h.dynamodb = ddb
        h.episodes_table = ddb.Table(TEST_TABLE)
        original_key = h.ADMIN_API_KEY
        h.ADMIN_API_KEY = "correct-key"

        try:
            event = _make_apigw_event("GET", "/episodes", auth_header="Bearer wrong-key")
            result = h.lambda_handler(event, {})
            assert result["statusCode"] == 401
        finally:
            h.ADMIN_API_KEY = original_key

    @mock_aws
    def test_missing_api_key_header_returns_401(self) -> None:
        """A request with no Authorization header should return 401 when auth is enabled."""
        ddb = boto3.resource("dynamodb", region_name=TEST_REGION)
        _make_table(ddb)

        from src.episodes_api import handler as h
        h.dynamodb = ddb
        h.episodes_table = ddb.Table(TEST_TABLE)
        original_key = h.ADMIN_API_KEY
        h.ADMIN_API_KEY = "some-key"

        try:
            event = _make_apigw_event("GET", "/episodes")
            result = h.lambda_handler(event, {})
            assert result["statusCode"] == 401
        finally:
            h.ADMIN_API_KEY = original_key


# ─────────────────────────────────────────────
# Tests: Unknown routes
# ─────────────────────────────────────────────

class TestRouting:

    @mock_aws
    def test_unknown_path_returns_404(self) -> None:
        """Unknown paths should return 404."""
        ddb = boto3.resource("dynamodb", region_name=TEST_REGION)
        _make_table(ddb)

        from src.episodes_api import handler as h
        h.dynamodb = ddb
        h.episodes_table = ddb.Table(TEST_TABLE)

        event = _make_apigw_event("GET", "/unknown-path")
        result = h.lambda_handler(event, {})

        assert result["statusCode"] == 404

    @mock_aws
    def test_response_has_content_type_header(self) -> None:
        """All responses should include Content-Type: application/json."""
        ddb = boto3.resource("dynamodb", region_name=TEST_REGION)
        _make_table(ddb)

        from src.episodes_api import handler as h
        h.dynamodb = ddb
        h.episodes_table = ddb.Table(TEST_TABLE)

        event = _make_apigw_event("GET", "/episodes")
        result = h.lambda_handler(event, {})

        assert result["headers"]["Content-Type"] == "application/json"
