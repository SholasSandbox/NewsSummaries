"""
ingest_news/handler.py

Lambda handler that fetches news from RSS feeds and NewsAPI.org,
deduplicates articles, and stores raw JSON in S3.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

import boto3
import feedparser
import requests


# ---------------------------------------------------------------------------
# Inline logger (shared layer may not be available during cold-start bootstrap)
# ---------------------------------------------------------------------------
def _build_logger(name: str) -> logging.Logger:
    """Return a JSON-structured logger."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                '{"time": "%(asctime)s", "level": "%(levelname)s", '
                '"logger": "%(name)s", "message": %(message)s}'
            )
        )
        logger.addHandler(handler)
    logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
    return logger


log = _build_logger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
S3_BUCKET = os.environ["S3_BUCKET_NAME"]
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE_NAME", "")
GENERATE_SUMMARIES_FUNCTION = os.environ.get("GENERATE_SUMMARIES_FUNCTION", "")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "")
NEWS_API_ENABLED = bool(NEWS_API_KEY and NEWS_API_KEY != "DISABLED")

RSS_FEEDS: list[dict[str, str]] = [
    {
        "name": "BBC Top Stories",
        "url": "http://feeds.bbci.co.uk/news/rss.xml",
        "category": "general",
    },
    {
        "name": "BBC World",
        "url": "http://feeds.bbci.co.uk/news/world/rss.xml",
        "category": "world",
    },
    {
        "name": "BBC Politics",
        "url": "http://feeds.bbci.co.uk/news/politics/rss.xml",
        "category": "politics",
    },
    {
        "name": "Reuters Top News",
        "url": "https://feeds.reuters.com/reuters/topNews",
        "category": "general",
    },
    {
        "name": "Reuters Business",
        "url": "https://feeds.reuters.com/reuters/businessNews",
        "category": "business",
    },
    {
        "name": "Reuters Technology",
        "url": "https://feeds.reuters.com/reuters/technologyNews",
        "category": "technology",
    },
    {
        "name": "Reuters Science",
        "url": "https://feeds.reuters.com/reuters/scienceNews",
        "category": "science",
    },
    {
        "name": "Reuters Markets",
        "url": "https://feeds.reuters.com/reuters/businessNews",
        "category": "markets",
    },
    {
        "name": "Associated Press",
        "url": "https://feeds.apnews.com/rss/apf-topnews",
        "category": "general",
    },
    {
        "name": "AP Politics",
        "url": "https://feeds.apnews.com/rss/apf-politics",
        "category": "politics",
    },
    {
        "name": "NPR News",
        "url": "https://feeds.npr.org/1001/rss.xml",
        "category": "general",
    },
    {
        "name": "NPR Lifestyle",
        "url": "https://feeds.npr.org/1057/rss.xml",
        "category": "lifestyle",
    },
    {
        "name": "The Guardian World",
        "url": "https://www.theguardian.com/world/rss",
        "category": "world",
    },
    {
        "name": "The Guardian Politics",
        "url": "https://www.theguardian.com/politics/rss",
        "category": "politics",
    },
    {
        "name": "The Guardian Life and Style",
        "url": "https://www.theguardian.com/lifeandstyle/rss",
        "category": "lifestyle",
    },
    {
        "name": "Ars Technica",
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "category": "technology",
    },
]

NEWSAPI_CATEGORIES = ["general", "business", "technology", "science", "health"]
NEWSAPI_BASE_URL = "https://newsapi.org/v2/top-headlines"
HTTP_TIMEOUT = 15  # seconds per request


def lambda_handler(event: dict, context: Any) -> dict:
    """
    Main Lambda entry point.

    Triggered by EventBridge Scheduler twice daily (6 AM and 6 PM UTC).
    Fetches articles from all configured RSS feeds, optionally supplements
    with NewsAPI results, deduplicates, and stores each article as a
    separate JSON object in S3 under raw/{YYYY-MM-DD}/{article_hash}.json.
    After storing, invokes the GenerateSummaries Lambda for each new article.
    """
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log.info(json.dumps({"event": "ingest_started", "run_date": run_date}))

    articles = _fetch_all_rss_articles()

    if NEWS_API_ENABLED:
        newsapi_articles = _fetch_newsapi_articles()
        articles.extend(newsapi_articles)
        log.info(
            json.dumps({"event": "newsapi_fetched", "count": len(newsapi_articles)})
        )

    unique_articles = _deduplicate(articles)
    log.info(
        json.dumps(
            {
                "event": "dedup_complete",
                "total": len(articles),
                "unique": len(unique_articles),
            }
        )
    )

    stored_keys = _store_articles(unique_articles, run_date)
    log.info(json.dumps({"event": "articles_stored", "count": len(stored_keys)}))

    if stored_keys and DYNAMODB_TABLE:
        _update_article_metadata(unique_articles, run_date)

    if stored_keys and GENERATE_SUMMARIES_FUNCTION:
        _invoke_generate_summaries(stored_keys)

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "run_date": run_date,
                "articles_fetched": len(articles),
                "articles_stored": len(stored_keys),
            }
        ),
    }


# ---------------------------------------------------------------------------
# RSS Helpers
# ---------------------------------------------------------------------------


def _fetch_all_rss_articles() -> list[dict]:
    """Fetch and normalise articles from all configured RSS feeds."""
    all_articles: list[dict] = []
    for feed_cfg in RSS_FEEDS:
        try:
            feed_articles = _fetch_rss_feed(feed_cfg)
            all_articles.extend(feed_articles)
            log.info(
                json.dumps(
                    {
                        "event": "rss_feed_fetched",
                        "feed": feed_cfg["name"],
                        "count": len(feed_articles),
                    }
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                json.dumps(
                    {
                        "event": "rss_feed_error",
                        "feed": feed_cfg["name"],
                        "error": str(exc),
                    }
                )
            )
    return all_articles


def _fetch_rss_feed(feed_cfg: dict) -> list[dict]:
    """Download and parse a single RSS feed, returning normalised article dicts."""
    # Use requests so we control timeout; feedparser can parse the response text.
    response = requests.get(
        feed_cfg["url"],
        timeout=HTTP_TIMEOUT,
        headers={"User-Agent": "NewsSummaries/1.0"},
    )
    response.raise_for_status()
    parsed = feedparser.parse(response.text)

    articles = []
    for entry in parsed.entries[:20]:  # cap at 20 per feed to control volume
        title = getattr(entry, "title", "").strip()
        summary = getattr(entry, "summary", getattr(entry, "description", "")).strip()
        link = getattr(entry, "link", "").strip()
        published = _parse_published(entry)
        if not title or not link:
            continue
        articles.append(
            {
                "source": feed_cfg["name"],
                "category": feed_cfg["category"],
                "title": title,
                "url": link,
                "raw_summary": summary,
                "published_at": published,
            }
        )
    return articles


def _parse_published(entry: Any) -> str:
    """Extract a normalised ISO-8601 publication timestamp from a feedparser entry."""
    try:
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            return datetime(
                *entry.published_parsed[:6], tzinfo=timezone.utc
            ).isoformat()
        if hasattr(entry, "updated_parsed") and entry.updated_parsed:
            return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc).isoformat()
    except Exception:  # noqa: BLE001
        pass
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# NewsAPI Helpers
# ---------------------------------------------------------------------------


def _fetch_newsapi_articles() -> list[dict]:
    """Fetch top headlines from NewsAPI for all configured categories."""
    articles: list[dict] = []
    for category in NEWSAPI_CATEGORIES:
        try:
            category_articles = _fetch_newsapi_category(category)
            articles.extend(category_articles)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                json.dumps(
                    {
                        "event": "newsapi_category_error",
                        "category": category,
                        "error": str(exc),
                    }
                )
            )
    return articles


def _fetch_newsapi_category(category: str) -> list[dict]:
    """Fetch headlines for a single NewsAPI category."""
    params = {
        "apiKey": NEWS_API_KEY,
        "category": category,
        "language": "en",
        "pageSize": 20,
    }
    response = requests.get(NEWSAPI_BASE_URL, params=params, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    data = response.json()

    articles = []
    for item in data.get("articles", []):
        title = (item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        if not title or not url or title == "[Removed]":
            continue
        articles.append(
            {
                "source": item.get("source", {}).get("name", "NewsAPI"),
                "category": category,
                "title": title,
                "url": url,
                "raw_summary": (item.get("description") or "").strip(),
                "published_at": item.get(
                    "publishedAt", datetime.now(timezone.utc).isoformat()
                ),
            }
        )
    return articles


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def _article_hash(article: dict) -> str:
    """Create a stable SHA-256 hash for an article based on its URL and title."""
    key = f"{article['url']}|{article['title']}".lower()
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _deduplicate(articles: list[dict]) -> list[dict]:
    """Remove duplicate articles by URL/title hash, keeping first occurrence."""
    seen: set[str] = set()
    unique: list[dict] = []
    for article in articles:
        h = _article_hash(article)
        if h not in seen:
            seen.add(h)
            article["article_hash"] = h
            unique.append(article)
    return unique


# ---------------------------------------------------------------------------
# S3 Storage
# ---------------------------------------------------------------------------


def _store_articles(articles: list[dict], run_date: str) -> list[str]:
    """
    Store each article as a JSON object in S3.

    Key pattern: raw/{YYYY-MM-DD}/{article_hash}.json
    Returns the list of S3 keys successfully written.
    """
    s3 = boto3.client("s3")
    stored_keys: list[str] = []
    for article in articles:
        article_hash = article["article_hash"]
        s3_key = f"raw/{run_date}/{article_hash}.json"
        body = {
            **article,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "run_date": run_date,
        }
        try:
            # Skip if already stored (idempotent)
            try:
                s3.head_object(Bucket=S3_BUCKET, Key=s3_key)
                log.debug(
                    json.dumps({"event": "article_already_exists", "key": s3_key})
                )
                continue
            except s3.exceptions.ClientError:
                pass  # Object does not exist – proceed to write

            s3.put_object(
                Bucket=S3_BUCKET,
                Key=s3_key,
                Body=json.dumps(body, ensure_ascii=False, default=str),
                ContentType="application/json",
                Metadata={
                    "source": article.get("source", ""),
                    "category": article.get("category", ""),
                },
            )
            stored_keys.append(s3_key)
        except Exception as exc:  # noqa: BLE001
            log.error(
                json.dumps(
                    {
                        "event": "s3_write_error",
                        "key": s3_key,
                        "error": str(exc),
                    }
                )
            )
    return stored_keys


# ---------------------------------------------------------------------------
# DynamoDB Metadata
# ---------------------------------------------------------------------------


def _update_article_metadata(articles: list[dict], run_date: str) -> None:
    """
    Write article ingestion metadata to DynamoDB.

    Creates a record per article with status="ingested" so Lambda 2 can
    pick up the article and update the record with summary information.
    TTL is set to 30 days from now for automatic cleanup.
    """
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(DYNAMODB_TABLE)
    now = datetime.now(timezone.utc)
    ttl = int(now.timestamp()) + 30 * 24 * 3600  # 30 days

    for article in articles:
        article_hash = article.get("article_hash", "")
        s3_key = f"raw/{run_date}/{article_hash}.json"
        item = {
            "episode_id": article_hash,
            "date": run_date,
            "title": article.get("title", ""),
            "source": article.get("source", ""),
            "url": article.get("url", ""),
            "category": article.get("category", "general"),
            "fetch_timestamp": now.isoformat(),
            "s3_path": s3_key,
            "status": "ingested",
            "created_at": now.isoformat(),
            "ttl": ttl,
        }
        try:
            table.put_item(
                Item=item, ConditionExpression="attribute_not_exists(episode_id)"
            )
            log.debug(json.dumps({"event": "dynamo_written", "hash": article_hash}))
        except table.meta.client.exceptions.ConditionalCheckFailedException:
            log.debug(
                json.dumps({"event": "dynamo_already_exists", "hash": article_hash})
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                json.dumps(
                    {
                        "event": "dynamo_write_error",
                        "hash": article_hash,
                        "error": str(exc),
                    }
                )
            )


# ---------------------------------------------------------------------------
# Downstream invocation
# ---------------------------------------------------------------------------


def _invoke_generate_summaries(s3_keys: list[str]) -> None:
    """
    Asynchronously invoke the GenerateSummaries Lambda for each stored S3 key.

    We invoke asynchronously (InvocationType=Event) to avoid hitting the
    300-second timeout of the ingest function when processing large batches.
    """
    lambda_client = boto3.client("lambda")
    for s3_key in s3_keys:
        payload = {"source": "ingest_news", "s3_key": s3_key, "bucket": S3_BUCKET}
        try:
            lambda_client.invoke(
                FunctionName=GENERATE_SUMMARIES_FUNCTION,
                InvocationType="Event",
                Payload=json.dumps(payload),
            )
            log.debug(json.dumps({"event": "summaries_invoked", "key": s3_key}))
        except Exception as exc:  # noqa: BLE001
            log.error(
                json.dumps(
                    {
                        "event": "summaries_invoke_error",
                        "key": s3_key,
                        "error": str(exc),
                    }
                )
            )
        time.sleep(0.05)  # gentle rate limiting between Lambda invocations
