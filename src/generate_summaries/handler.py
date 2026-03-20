"""
generate_summaries/handler.py

Lambda handler that reads raw articles from S3, generates structured
2–3 sentence summaries using the OpenAI o3-mini model, stores the
summary JSON back to S3, and writes episode metadata to DynamoDB.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError
from openai import APIStatusError, OpenAI, RateLimitError

# ---------------------------------------------------------------------------
# Structured logger
# ---------------------------------------------------------------------------


def _build_logger(name: str) -> logging.Logger:
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
DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE_NAME"]
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = "o3-mini"
MAX_RETRIES = 3
BASE_BACKOFF = 2  # seconds

SUMMARY_SYSTEM_PROMPT = """You are a professional news editor who writes concise, insightful news summaries.
Your summaries are factual, balanced, and written for an informed adult audience.
Always respond with valid JSON only."""

SUMMARY_USER_TEMPLATE = """Summarise the following news article in 2-3 sentences.
Focus on the most important facts and their significance.

Title: {title}
Source: {source}
Content: {content}

Respond ONLY with this JSON structure:
{{
  "summary": "2-3 sentence summary here",
  "category": "one of: general|world|business|technology|science|health|sports|entertainment",
  "importance": "one of: high|medium|low",
  "keywords": ["keyword1", "keyword2", "keyword3"]
}}"""

# ---------------------------------------------------------------------------
# AWS clients (module-level for connection reuse across warm invocations)
# ---------------------------------------------------------------------------
s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
episodes_table = dynamodb.Table(DYNAMODB_TABLE)
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


def lambda_handler(event: dict, context: Any) -> dict:
    """
    Main Lambda entry point.

    Accepts two invocation modes:
    1. Direct invocation from IngestNews Lambda:
       event = {"source": "ingest_news", "s3_key": "raw/...", "bucket": "..."}
    2. S3 event notification (PUT in raw/ prefix):
       event = {"Records": [{"s3": {"bucket": {...}, "object": {...}}}]}
    """
    records = _extract_records(event)
    if not records:
        log.warning(json.dumps({"event": "no_records", "raw_event": str(event)[:200]}))
        return {"statusCode": 200, "body": "No records to process"}

    results = {"processed": 0, "failed": 0, "skipped": 0}
    for record in records:
        bucket = record["bucket"]
        s3_key = record["key"]
        try:
            outcome = _process_article(bucket, s3_key)
            results[outcome] += 1
        except Exception as exc:  # noqa: BLE001
            log.error(
                json.dumps({"event": "record_error", "key": s3_key, "error": str(exc)})
            )
            results["failed"] += 1

    log.info(json.dumps({"event": "batch_complete", **results}))
    return {"statusCode": 200, "body": json.dumps(results)}


# ---------------------------------------------------------------------------
# Record extraction
# ---------------------------------------------------------------------------


def _extract_records(event: dict) -> list[dict[str, str]]:
    """Normalise different event shapes into a list of {bucket, key} dicts."""
    # S3 event notification
    if "Records" in event:
        records = []
        for rec in event["Records"]:
            s3_info = rec.get("s3", {})
            bucket = s3_info.get("bucket", {}).get("name", S3_BUCKET)
            key = s3_info.get("object", {}).get("key", "")
            if key:
                records.append({"bucket": bucket, "key": key})
        return records

    # Direct invocation from IngestNews
    if "s3_key" in event:
        return [{"bucket": event.get("bucket", S3_BUCKET), "key": event["s3_key"]}]

    return []


# ---------------------------------------------------------------------------
# Article processing
# ---------------------------------------------------------------------------


def _process_article(bucket: str, s3_key: str) -> str:
    """
    Read a raw article from S3, generate a summary, store it, and update DynamoDB.
    Returns "processed", "skipped", or raises on unrecoverable error.
    """
    # Derive the summary key and skip if already summarised
    summary_key = s3_key.replace("raw/", "summaries/", 1)
    if _s3_object_exists(bucket, summary_key):
        log.info(json.dumps({"event": "already_summarised", "key": s3_key}))
        return "skipped"

    raw_article = _read_s3_json(bucket, s3_key)
    if not raw_article:
        log.warning(json.dumps({"event": "empty_article", "key": s3_key}))
        return "skipped"

    ai_result = _generate_summary_with_retry(raw_article)

    episode_id = str(uuid.uuid4())
    run_date = raw_article.get(
        "run_date", datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )
    created_at = datetime.now(timezone.utc).isoformat()

    summary_doc = {
        "episode_id": episode_id,
        "date": run_date,
        "created_at": created_at,
        "title": raw_article.get("title", ""),
        "source": raw_article.get("source", ""),
        "url": raw_article.get("url", ""),
        "article_hash": raw_article.get("article_hash", ""),
        "raw_s3_key": s3_key,
        "summary_s3_key": summary_key,
        **ai_result,
    }

    _write_s3_json(bucket, summary_key, summary_doc)
    _write_dynamodb_episode(summary_doc)

    log.info(
        json.dumps(
            {
                "event": "article_summarised",
                "episode_id": episode_id,
                "title": raw_article.get("title", "")[:80],
                "category": ai_result.get("category"),
                "importance": ai_result.get("importance"),
            }
        )
    )
    return "processed"


# ---------------------------------------------------------------------------
# OpenAI Integration
# ---------------------------------------------------------------------------


def _generate_summary_with_retry(article: dict) -> dict:
    """
    Call OpenAI o3-mini to generate a structured summary.
    Retries up to MAX_RETRIES times with exponential backoff on rate-limit errors.
    """
    content = article.get("raw_summary") or article.get("title", "")
    prompt = SUMMARY_USER_TEMPLATE.format(
        title=article.get("title", ""),
        source=article.get("source", ""),
        content=content[:3000],  # cap content length to manage token costs
    )

    for attempt in range(MAX_RETRIES):
        try:
            response = openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=512,
            )
            raw_json = response.choices[0].message.content
            result = json.loads(raw_json)
            return _validate_summary_result(result)

        except RateLimitError as exc:
            wait = BASE_BACKOFF ** (attempt + 1)
            log.warning(
                json.dumps(
                    {
                        "event": "openai_rate_limit",
                        "attempt": attempt + 1,
                        "wait_seconds": wait,
                        "error": str(exc),
                    }
                )
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(wait)
            else:
                raise

        except (json.JSONDecodeError, KeyError) as exc:
            log.error(json.dumps({"event": "openai_parse_error", "error": str(exc)}))
            # Return a fallback summary rather than failing the whole batch
            return _fallback_summary(article)

        except APIStatusError as exc:
            log.error(
                json.dumps(
                    {
                        "event": "openai_api_error",
                        "status": exc.status_code,
                        "error": str(exc),
                    }
                )
            )
            if exc.status_code >= 500 and attempt < MAX_RETRIES - 1:
                time.sleep(BASE_BACKOFF ** (attempt + 1))
                continue
            return _fallback_summary(article)

    return _fallback_summary(article)


def _validate_summary_result(result: dict) -> dict:
    """Ensure the AI response contains required fields; fill defaults if missing."""
    valid_categories = {
        "general",
        "world",
        "business",
        "technology",
        "science",
        "health",
        "sports",
        "entertainment",
    }
    valid_importance = {"high", "medium", "low"}

    return {
        "summary": str(result.get("summary", "")).strip(),
        "category": (
            result.get("category", "general")
            if result.get("category") in valid_categories
            else "general"
        ),
        "importance": (
            result.get("importance", "medium")
            if result.get("importance") in valid_importance
            else "medium"
        ),
        "keywords": list(result.get("keywords", []))[:10],
    }


def _fallback_summary(article: dict) -> dict:
    """Generate a minimal fallback summary when the AI call fails."""
    return {
        "summary": article.get(
            "raw_summary", article.get("title", "Summary unavailable.")
        )[:500],
        "category": article.get("category", "general"),
        "importance": "medium",
        "keywords": [],
    }


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------


def _s3_object_exists(bucket: str, key: str) -> bool:
    """Return True if the S3 object exists."""
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError:
        return False


def _read_s3_json(bucket: str, key: str) -> dict | None:
    """Read and deserialise a JSON object from S3."""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        return json.loads(response["Body"].read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.error(
            json.dumps(
                {
                    "event": "s3_read_error",
                    "bucket": bucket,
                    "key": key,
                    "error": str(exc),
                }
            )
        )
        return None


def _write_s3_json(bucket: str, key: str, data: dict) -> None:
    """Serialise and write a JSON object to S3."""
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(data, ensure_ascii=False, default=str),
        ContentType="application/json",
    )


# ---------------------------------------------------------------------------
# DynamoDB helpers
# ---------------------------------------------------------------------------


def _write_dynamodb_episode(doc: dict) -> None:
    """Write an episode record to DynamoDB with a 90-day TTL."""
    ttl = int(time.time()) + (90 * 24 * 3600)
    episodes_table.put_item(
        Item={
            "episode_id": doc["episode_id"],
            "date": doc["date"],
            "created_at": doc["created_at"],
            "title": doc["title"],
            "source": doc["source"],
            "url": doc["url"],
            "article_hash": doc.get("article_hash", ""),
            "summary": doc.get("summary", ""),
            "category": doc.get("category", "general"),
            "importance": doc.get("importance", "medium"),
            "keywords": doc.get("keywords", []),
            "raw_s3_key": doc.get("raw_s3_key", ""),
            "summary_s3_key": doc.get("summary_s3_key", ""),
            "audio_url": None,
            "ttl": ttl,
        }
    )
