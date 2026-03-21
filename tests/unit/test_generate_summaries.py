"""
tests/unit/test_generate_summaries.py

Unit tests for the GenerateSummaries Lambda handler.
AWS services are mocked with moto; OpenAI calls are mocked with unittest.mock.
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import boto3
from moto import mock_aws

os.environ.setdefault("S3_BUCKET_NAME", "test-news-summaries")
os.environ.setdefault("DYNAMODB_TABLE_NAME", "test-news-summaries-episodes")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-key")
os.environ.setdefault("LOG_LEVEL", "DEBUG")


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def _make_openai_mock(summary_json: dict) -> MagicMock:
    """Return a mock openai_client whose chat.completions.create returns the given dict."""
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps(summary_json)
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_response
    return mock_client


VALID_AI_RESPONSE = {
    "summary": "Scientists have announced a breakthrough. The model outperformed experts. Timelines may be cut.",
    "category": "technology",
    "importance": "high",
    "keywords": ["AI", "science", "breakthrough"],
}


# ─────────────────────────────────────────────
# Tests: OpenAI response parsing
# ─────────────────────────────────────────────


class TestOpenAIResponseParsing:
    """Tests for _validate_summary_result and _generate_summary_with_retry."""

    def test_validate_valid_response(self) -> None:
        """A well-formed AI response should pass through unchanged."""
        from src.generate_summaries.handler import _validate_summary_result

        result = _validate_summary_result(VALID_AI_RESPONSE)
        assert result["summary"] == VALID_AI_RESPONSE["summary"]
        assert result["category"] == "technology"
        assert result["importance"] == "high"
        assert result["keywords"] == ["AI", "science", "breakthrough"]

    def test_validate_unknown_category_defaults_to_general(self) -> None:
        """An unrecognised category should default to 'general'."""
        from src.generate_summaries.handler import _validate_summary_result

        result = _validate_summary_result({**VALID_AI_RESPONSE, "category": "gossip"})
        assert result["category"] == "general"

    def test_validate_new_categories_are_accepted(self) -> None:
        """markets, lifestyle, and politics should be accepted as valid categories."""
        from src.generate_summaries.handler import _validate_summary_result

        for cat in ("markets", "lifestyle", "politics"):
            result = _validate_summary_result({**VALID_AI_RESPONSE, "category": cat})
            assert result["category"] == cat, f"Category '{cat}' should be accepted"

    def test_validate_unknown_importance_defaults_to_medium(self) -> None:
        """An unrecognised importance value should default to 'medium'."""
        from src.generate_summaries.handler import _validate_summary_result

        result = _validate_summary_result(
            {**VALID_AI_RESPONSE, "importance": "critical"}
        )
        assert result["importance"] == "medium"

    def test_validate_keywords_capped_at_10(self) -> None:
        """More than 10 keywords should be truncated to 10."""
        from src.generate_summaries.handler import _validate_summary_result

        many_keywords = [f"kw{i}" for i in range(20)]
        result = _validate_summary_result(
            {**VALID_AI_RESPONSE, "keywords": many_keywords}
        )
        assert len(result["keywords"]) == 10

    def test_fallback_summary_uses_raw_content(self) -> None:
        """_fallback_summary should use the article's raw_summary field."""
        from src.generate_summaries.handler import _fallback_summary

        article = {
            "raw_summary": "Breaking news about something important.",
            "category": "world",
        }
        result = _fallback_summary(article)
        assert result["summary"] == "Breaking news about something important."
        assert result["category"] == "world"

    @mock_aws
    def test_generate_summary_calls_openai(self) -> None:
        """_generate_summary_with_retry should call the OpenAI API once for a new article."""
        from src.generate_summaries import handler as h

        mock_client = _make_openai_mock(VALID_AI_RESPONSE)
        with patch.object(h, "openai_client", mock_client):
            result = h._generate_summary_with_retry(
                {
                    "title": "Test Article",
                    "source": "BBC",
                    "raw_summary": "Test content.",
                }
            )

        mock_client.chat.completions.create.assert_called_once()
        assert result["category"] == "technology"
        assert result["importance"] == "high"

    @mock_aws
    def test_generate_summary_retries_on_rate_limit(self) -> None:
        """Should retry on RateLimitError and succeed on the second attempt."""
        from openai import RateLimitError

        from src.generate_summaries import handler as h

        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps(VALID_AI_RESPONSE)
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        # Fail once then succeed
        mock_client.chat.completions.create.side_effect = [
            RateLimitError("rate limit", response=MagicMock(status_code=429), body={}),
            mock_response,
        ]

        with patch.object(h, "openai_client", mock_client), patch("time.sleep"):
            result = h._generate_summary_with_retry(
                {
                    "title": "Test",
                    "source": "BBC",
                    "raw_summary": "Content",
                }
            )

        assert mock_client.chat.completions.create.call_count == 2
        assert result["summary"] != ""

    @mock_aws
    def test_generate_summary_returns_fallback_on_json_error(self) -> None:
        """Should return a fallback summary when the AI returns invalid JSON."""
        from src.generate_summaries import handler as h

        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "not valid json at all"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response

        article = {"title": "Test", "source": "BBC", "raw_summary": "Fallback content."}
        with patch.object(h, "openai_client", mock_client):
            result = h._generate_summary_with_retry(article)

        assert result["summary"] == "Fallback content."


# ─────────────────────────────────────────────
# Tests: DynamoDB writes
# ─────────────────────────────────────────────


class TestDynamoDBWrites:
    """Tests for _write_dynamodb_episode."""

    @mock_aws
    def test_writes_episode_to_dynamodb(self) -> None:
        """Should write a complete episode record to DynamoDB."""
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
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

        from src.generate_summaries import handler as h

        # Patch the module-level table reference to use our mocked table
        with patch.object(
            h, "episodes_table", ddb.Table("test-news-summaries-episodes")
        ):
            h._write_dynamodb_episode(
                {
                    "episode_id": "test-uuid-1234",
                    "date": "2024-01-15",
                    "created_at": "2024-01-15T06:00:00+00:00",
                    "title": "Test Article",
                    "source": "BBC",
                    "url": "https://bbc.co.uk/test",
                    "article_hash": "abc123",
                    "summary": "Short test summary.",
                    "category": "technology",
                    "importance": "high",
                    "keywords": ["AI"],
                    "raw_s3_key": "raw/2024-01-15/abc123.json",
                    "summary_s3_key": "summaries/2024-01-15/abc123.json",
                }
            )

        table = ddb.Table("test-news-summaries-episodes")
        item = table.get_item(
            Key={"episode_id": "test-uuid-1234", "date": "2024-01-15"}
        )["Item"]
        assert item["title"] == "Test Article"
        assert item["category"] == "technology"
        assert "ttl" in item
        assert item["audio_url"] is None
        assert item["status"] == "summarized"


# ─────────────────────────────────────────────
# Tests: End-to-end _process_article
# ─────────────────────────────────────────────


class TestProcessArticle:
    """Integration tests for the _process_article function."""

    @mock_aws
    def test_process_article_writes_summary_to_s3(
        self, sample_raw_article: dict
    ) -> None:
        """_process_article should write a summary JSON to S3."""
        from src.generate_summaries import handler as h

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-news-summaries")

        # Put raw article
        s3_key = f"raw/{sample_raw_article['run_date']}/{sample_raw_article['article_hash']}.json"
        s3.put_object(
            Bucket="test-news-summaries",
            Key=s3_key,
            Body=json.dumps(sample_raw_article),
        )

        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
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

        mock_client = _make_openai_mock(VALID_AI_RESPONSE)

        with (
            patch.object(h, "openai_client", mock_client),
            patch.object(h, "s3_client", s3),
            patch.object(
                h, "episodes_table", ddb.Table("test-news-summaries-episodes")
            ),
        ):
            outcome = h._process_article("test-news-summaries", s3_key)

        assert outcome == "processed"

        # Verify summary in S3
        summary_key = s3_key.replace("raw/", "summaries/", 1)
        obj = s3.get_object(Bucket="test-news-summaries", Key=summary_key)
        summary_doc = json.loads(obj["Body"].read())
        assert summary_doc["category"] == "technology"
        assert summary_doc["importance"] == "high"

    @mock_aws
    def test_process_article_skips_if_already_summarised(
        self, sample_raw_article: dict
    ) -> None:
        """Should return 'skipped' if a summary already exists in S3."""
        from src.generate_summaries import handler as h

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-news-summaries")

        run_date = sample_raw_article["run_date"]
        article_hash = sample_raw_article["article_hash"]
        raw_key = f"raw/{run_date}/{article_hash}.json"
        summary_key = f"summaries/{run_date}/{article_hash}.json"

        # Pre-create both raw and summary objects
        s3.put_object(
            Bucket="test-news-summaries",
            Key=raw_key,
            Body=json.dumps(sample_raw_article),
        )
        s3.put_object(
            Bucket="test-news-summaries",
            Key=summary_key,
            Body=json.dumps({"summary": "existing"}),
        )

        with patch.object(h, "s3_client", s3):
            outcome = h._process_article("test-news-summaries", raw_key)

        assert outcome == "skipped"


# ─────────────────────────────────────────────
# Tests: Error handling
# ─────────────────────────────────────────────


class TestErrorHandling:
    """Tests for error handling in the GenerateSummaries handler."""

    @mock_aws
    def test_handler_handles_missing_s3_key(self) -> None:
        """Handler should handle missing S3 objects without raising unhandled exceptions."""
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-news-summaries")

        from src.generate_summaries import handler as h

        with patch.object(h, "s3_client", s3):
            result = h.lambda_handler(
                {
                    "s3_key": "raw/2024-01-15/nonexistent.json",
                    "bucket": "test-news-summaries",
                },
                MagicMock(),
            )

        assert result["statusCode"] == 200

    def test_extract_records_direct_invocation(self) -> None:
        """Should extract a single record from a direct Lambda invocation event."""
        from src.generate_summaries.handler import _extract_records

        event = {"s3_key": "raw/2024-01-15/abc.json", "bucket": "my-bucket"}
        records = _extract_records(event)
        assert len(records) == 1
        assert records[0]["key"] == "raw/2024-01-15/abc.json"
        assert records[0]["bucket"] == "my-bucket"

    def test_extract_records_s3_notification(self) -> None:
        """Should extract records from an S3 event notification payload."""
        from src.generate_summaries.handler import _extract_records

        event = {
            "Records": [
                {
                    "s3": {
                        "bucket": {"name": "my-bucket"},
                        "object": {"key": "raw/2024-01-15/abc.json"},
                    }
                }
            ]
        }
        records = _extract_records(event)
        assert len(records) == 1
        assert records[0]["key"] == "raw/2024-01-15/abc.json"

    def test_extract_records_empty_event(self) -> None:
        """An unrecognised event shape should return an empty list."""
        from src.generate_summaries.handler import _extract_records

        records = _extract_records({"unknown": "format"})
        assert records == []
