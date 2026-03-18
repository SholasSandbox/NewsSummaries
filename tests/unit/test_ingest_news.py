"""
tests/unit/test_ingest_news.py

Unit tests for the IngestNews Lambda handler.
AWS services are mocked with moto; HTTP requests are intercepted with responses.
"""

from __future__ import annotations

import hashlib
import json
import os
from unittest.mock import MagicMock, patch

import boto3
import pytest
import responses as responses_lib
from moto import mock_aws

# Ensure environment variables are set before importing the handler
os.environ.setdefault("S3_BUCKET_NAME", "test-news-summaries")
os.environ.setdefault("DYNAMODB_TABLE_NAME", "test-news-summaries-episodes")
os.environ.setdefault("GENERATE_SUMMARIES_FUNCTION", "test-summaries")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("NEWS_API_KEY", "DISABLED")


SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test News Feed</title>
    <link>https://example.com</link>
    <item>
      <title>AI Breakthrough Changes Everything</title>
      <link>https://example.com/ai-breakthrough</link>
      <description>Scientists announce major AI breakthrough in lab.</description>
      <pubDate>Mon, 15 Jan 2024 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Climate Summit Reaches Historic Deal</title>
      <link>https://example.com/climate-summit</link>
      <description>World leaders sign landmark climate agreement.</description>
      <pubDate>Mon, 15 Jan 2024 09:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""


# ─────────────────────────────────────────────
# Tests: RSS Parsing
# ─────────────────────────────────────────────

class TestRssFeedParsing:
    """Tests for _fetch_rss_feed and related helpers."""

    @responses_lib.activate
    def test_fetch_rss_feed_returns_articles(self) -> None:
        """Should return normalised article dicts from a valid RSS feed."""
        from src.ingest_news.handler import _fetch_rss_feed

        feed_url = "https://example.com/rss.xml"
        responses_lib.add(responses_lib.GET, feed_url, body=SAMPLE_RSS, status=200)

        feed_cfg = {"name": "Test Feed", "url": feed_url, "category": "general"}
        articles = _fetch_rss_feed(feed_cfg)

        assert len(articles) == 2
        assert articles[0]["title"] == "AI Breakthrough Changes Everything"
        assert articles[0]["url"] == "https://example.com/ai-breakthrough"
        assert articles[0]["source"] == "Test Feed"
        assert articles[0]["category"] == "general"

    @responses_lib.activate
    def test_fetch_rss_feed_caps_at_20_articles(self) -> None:
        """Should cap at 20 articles per feed to control ingestion volume."""
        from src.ingest_news.handler import _fetch_rss_feed

        items = "\n".join(
            f"""<item>
                <title>Story {i}</title>
                <link>https://example.com/story-{i}</link>
                <description>Description {i}</description>
            </item>"""
            for i in range(30)
        )
        rss_with_30_items = f"<rss version='2.0'><channel>{items}</channel></rss>"
        feed_url = "https://example.com/big-feed.xml"
        responses_lib.add(responses_lib.GET, feed_url, body=rss_with_30_items, status=200)

        articles = _fetch_rss_feed({"name": "Big Feed", "url": feed_url, "category": "general"})
        assert len(articles) == 20

    @responses_lib.activate
    def test_fetch_rss_feed_skips_items_without_title_or_link(self) -> None:
        """Articles missing both title and URL should be discarded."""
        from src.ingest_news.handler import _fetch_rss_feed

        rss = """<rss version="2.0"><channel>
            <item><description>No title or link</description></item>
            <item><title>Valid Article</title><link>https://example.com/valid</link></item>
        </channel></rss>"""
        feed_url = "https://example.com/partial.xml"
        responses_lib.add(responses_lib.GET, feed_url, body=rss, status=200)

        articles = _fetch_rss_feed({"name": "Test", "url": feed_url, "category": "general"})
        assert len(articles) == 1
        assert articles[0]["title"] == "Valid Article"

    @responses_lib.activate
    def test_fetch_rss_feed_handles_http_error(self) -> None:
        """Should raise an exception (not crash silently) when the feed returns a non-200."""
        from src.ingest_news.handler import _fetch_rss_feed

        feed_url = "https://example.com/down.xml"
        responses_lib.add(responses_lib.GET, feed_url, status=503)

        with pytest.raises(Exception):
            _fetch_rss_feed({"name": "Down Feed", "url": feed_url, "category": "general"})


# ─────────────────────────────────────────────
# Tests: Deduplication
# ─────────────────────────────────────────────

class TestDeduplication:
    """Tests for the _deduplicate helper."""

    def test_deduplicates_identical_articles(self) -> None:
        """Duplicate articles (same URL and title) should produce only one output."""
        from src.ingest_news.handler import _deduplicate

        articles = [
            {"url": "https://example.com/a", "title": "Story A"},
            {"url": "https://example.com/a", "title": "Story A"},  # duplicate
        ]
        result = _deduplicate(articles)
        assert len(result) == 1

    def test_keeps_unique_articles(self) -> None:
        """Distinct articles should all be kept."""
        from src.ingest_news.handler import _deduplicate

        articles = [
            {"url": "https://example.com/a", "title": "Story A"},
            {"url": "https://example.com/b", "title": "Story B"},
            {"url": "https://example.com/c", "title": "Story C"},
        ]
        result = _deduplicate(articles)
        assert len(result) == 3

    def test_adds_article_hash_field(self) -> None:
        """Each unique article should gain an `article_hash` field."""
        from src.ingest_news.handler import _deduplicate

        articles = [{"url": "https://example.com/a", "title": "Story A"}]
        result = _deduplicate(articles)
        assert "article_hash" in result[0]
        assert len(result[0]["article_hash"]) == 16  # 16-char hex prefix

    def test_hash_is_deterministic(self) -> None:
        """The same article should always produce the same hash."""
        from src.ingest_news.handler import _article_hash

        article = {"url": "https://example.com/test", "title": "Test Article"}
        h1 = _article_hash(article)
        h2 = _article_hash(article)
        assert h1 == h2

    def test_hash_is_case_insensitive(self) -> None:
        """Title case differences should not create duplicate articles."""
        from src.ingest_news.handler import _article_hash

        article_lower = {"url": "https://example.com/test", "title": "test article"}
        article_upper = {"url": "https://example.com/test", "title": "TEST ARTICLE"}
        assert _article_hash(article_lower) == _article_hash(article_upper)


# ─────────────────────────────────────────────
# Tests: S3 Storage
# ─────────────────────────────────────────────

class TestS3Storage:
    """Tests for the _store_articles helper."""

    @mock_aws
    def test_stores_article_in_s3(self) -> None:
        """Each article should be stored as a JSON object under raw/{date}/{hash}.json."""
        from src.ingest_news.handler import _store_articles

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-news-summaries")

        articles = [{
            "article_hash": "abc123def456aa",
            "source": "BBC",
            "category": "general",
            "title": "Test Article",
            "url": "https://example.com/test",
            "raw_summary": "A test article.",
            "published_at": "2024-01-15T10:00:00+00:00",
        }]

        keys = _store_articles(articles, "2024-01-15")
        assert len(keys) == 1
        assert keys[0] == "raw/2024-01-15/abc123def456aa.json"

        # Verify S3 object content
        obj = s3.get_object(Bucket="test-news-summaries", Key=keys[0])
        body = json.loads(obj["Body"].read())
        assert body["title"] == "Test Article"
        assert body["run_date"] == "2024-01-15"
        assert "ingested_at" in body

    @mock_aws
    def test_skips_already_stored_articles(self) -> None:
        """Articles that already exist in S3 should be skipped (idempotent)."""
        from src.ingest_news.handler import _store_articles

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-news-summaries")

        # Pre-store the article
        article_hash = "abc123def456ab"
        s3.put_object(
            Bucket="test-news-summaries",
            Key=f"raw/2024-01-15/{article_hash}.json",
            Body=json.dumps({"title": "Already stored"}),
        )

        articles = [{
            "article_hash": article_hash,
            "title": "Test Article",
            "url": "https://example.com/test",
        }]

        keys = _store_articles(articles, "2024-01-15")
        assert len(keys) == 0  # Nothing new was stored

    @mock_aws
    def test_stores_multiple_articles(self) -> None:
        """Multiple articles should each produce a separate S3 object."""
        from src.ingest_news.handler import _store_articles

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-news-summaries")

        articles = [
            {"article_hash": f"hash{i:014d}", "title": f"Article {i}", "url": f"https://example.com/{i}"}
            for i in range(5)
        ]
        keys = _store_articles(articles, "2024-01-15")
        assert len(keys) == 5


# ─────────────────────────────────────────────
# Tests: Lambda handler
# ─────────────────────────────────────────────

class TestLambdaHandler:
    """Integration-style tests for the IngestNews lambda_handler."""

    @mock_aws
    @responses_lib.activate
    def test_handler_returns_200(self) -> None:
        """Handler should return a 200 status with article counts."""
        # Mock all RSS feeds to return a simple feed
        from src.ingest_news import handler as h

        for feed_cfg in h.RSS_FEEDS:
            responses_lib.add(responses_lib.GET, feed_cfg["url"], body=SAMPLE_RSS, status=200)

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-news-summaries")

        with patch.object(h, "_invoke_generate_summaries"):
            result = h.lambda_handler({}, MagicMock())

        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert "articles_fetched" in body
        assert "articles_stored" in body
        assert body["articles_stored"] >= 0

    @mock_aws
    @responses_lib.activate
    def test_handler_continues_after_feed_error(self) -> None:
        """Handler should continue processing even if one feed is unreachable."""
        from src.ingest_news import handler as h

        # First feed fails, rest succeed
        responses_lib.add(responses_lib.GET, h.RSS_FEEDS[0]["url"], status=503)
        for feed_cfg in h.RSS_FEEDS[1:]:
            responses_lib.add(responses_lib.GET, feed_cfg["url"], body=SAMPLE_RSS, status=200)

        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-news-summaries")

        with patch.object(h, "_invoke_generate_summaries"):
            result = h.lambda_handler({}, MagicMock())

        # Should still succeed despite one feed failure
        assert result["statusCode"] == 200
