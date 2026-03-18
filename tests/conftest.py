"""
tests/conftest.py

Shared pytest fixtures for the NewsSummaries test suite.
Uses moto to mock AWS services in-process — no real AWS credentials needed.
"""

from __future__ import annotations

import json
import os
from typing import Generator

import boto3
import pytest
from moto import mock_aws

# ─────────────────────────────────────────────
# Environment variables
# ─────────────────────────────────────────────
# Set dummy AWS credentials before any boto3 client is created.
# moto intercepts the calls so these values are never sent to AWS.

TEST_BUCKET = "test-news-summaries"
TEST_TABLE = "test-news-summaries-episodes"
TEST_REGION = "us-east-1"
TEST_STAGE = "test"


@pytest.fixture(scope="session", autouse=True)
def aws_credentials() -> None:
    """
    Inject fake AWS credentials so boto3 does not attempt real AWS auth.
    These are intercepted by moto and never reach AWS endpoints.
    """
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
    os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
    os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
    os.environ.setdefault("AWS_DEFAULT_REGION", TEST_REGION)
    os.environ.setdefault("S3_BUCKET_NAME", TEST_BUCKET)
    os.environ.setdefault("DYNAMODB_TABLE_NAME", TEST_TABLE)
    os.environ.setdefault("STAGE", TEST_STAGE)
    os.environ.setdefault("LOG_LEVEL", "DEBUG")
    os.environ.setdefault("OPENAI_API_KEY", "sk-test-fake-key")
    os.environ.setdefault("NEWS_API_KEY", "DISABLED")
    os.environ.setdefault("GENERATE_SUMMARIES_FUNCTION", "test-summaries-function")
    os.environ.setdefault("CLOUDFRONT_DOMAIN", "test.cloudfront.net")
    os.environ.setdefault("PODCAST_TITLE", "Test Podcast")
    os.environ.setdefault("PODCAST_DESCRIPTION", "Test description")
    os.environ.setdefault("PODCAST_AUTHOR", "Test Author")
    os.environ.setdefault("PODCAST_EMAIL", "test@example.com")


@pytest.fixture
def mock_s3() -> Generator[boto3.client, None, None]:
    """Provide a mocked S3 client with the test bucket pre-created."""
    with mock_aws():
        client = boto3.client("s3", region_name=TEST_REGION)
        client.create_bucket(Bucket=TEST_BUCKET)
        yield client


@pytest.fixture
def mock_dynamodb() -> Generator[boto3.resource, None, None]:
    """
    Provide a mocked DynamoDB resource with the episodes table pre-created,
    including the same GSIs as the production table.
    """
    with mock_aws():
        resource = boto3.resource("dynamodb", region_name=TEST_REGION)
        resource.create_table(
            TableName=TEST_TABLE,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "episode_id", "AttributeType": "S"},
                {"AttributeName": "date", "AttributeType": "S"},
                {"AttributeName": "category", "AttributeType": "S"},
                {"AttributeName": "created_at", "AttributeType": "S"},
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
        yield resource


@pytest.fixture
def mock_ssm() -> Generator[boto3.client, None, None]:
    """Provide a mocked SSM client with test parameters pre-populated."""
    with mock_aws():
        client = boto3.client("ssm", region_name=TEST_REGION)
        client.put_parameter(
            Name="/news-summaries/openai-api-key",
            Value="sk-test-fake-openai-key",
            Type="SecureString",
        )
        client.put_parameter(
            Name="/news-summaries/news-api-key",
            Value="DISABLED",
            Type="SecureString",
        )
        yield client


@pytest.fixture
def sample_raw_article() -> dict:
    """A sample raw article dict as stored by IngestNews."""
    return {
        "article_hash": "abc123def456",
        "source": "BBC Top Stories",
        "category": "technology",
        "title": "AI Makes Major Breakthrough in Scientific Research",
        "url": "https://www.bbc.co.uk/news/technology-12345",
        "raw_summary": "Scientists have announced a major AI breakthrough...",
        "published_at": "2024-01-15T10:00:00+00:00",
        "ingested_at": "2024-01-15T06:00:01+00:00",
        "run_date": "2024-01-15",
    }


@pytest.fixture
def sample_summary_doc() -> dict:
    """A sample summary document as stored by GenerateSummaries."""
    return {
        "episode_id": "550e8400-e29b-41d4-a716-446655440000",
        "date": "2024-01-15",
        "created_at": "2024-01-15T06:01:00+00:00",
        "title": "AI Makes Major Breakthrough in Scientific Research",
        "source": "BBC Top Stories",
        "url": "https://www.bbc.co.uk/news/technology-12345",
        "article_hash": "abc123def456",
        "raw_s3_key": "raw/2024-01-15/abc123def456.json",
        "summary_s3_key": "summaries/2024-01-15/abc123def456.json",
        "summary": "Scientists have announced a major AI breakthrough that could accelerate drug discovery. "
                   "The new model outperformed human experts on complex protein folding tasks. "
                   "Researchers believe this could cut development timelines by decades.",
        "category": "technology",
        "importance": "high",
        "keywords": ["AI", "science", "breakthrough", "drug discovery"],
    }


@pytest.fixture
def s3_with_raw_article(mock_s3: boto3.client, sample_raw_article: dict) -> boto3.client:
    """S3 fixture with a raw article already uploaded."""
    import json
    mock_s3.put_object(
        Bucket=TEST_BUCKET,
        Key=f"raw/{sample_raw_article['run_date']}/{sample_raw_article['article_hash']}.json",
        Body=json.dumps(sample_raw_article),
        ContentType="application/json",
    )
    return mock_s3


@pytest.fixture
def s3_with_summary(mock_s3: boto3.client, sample_summary_doc: dict) -> boto3.client:
    """S3 fixture with a summary document already uploaded."""
    import json
    mock_s3.put_object(
        Bucket=TEST_BUCKET,
        Key=sample_summary_doc["summary_s3_key"],
        Body=json.dumps(sample_summary_doc),
        ContentType="application/json",
    )
    return mock_s3
