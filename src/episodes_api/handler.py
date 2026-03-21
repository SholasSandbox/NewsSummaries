"""
episodes_api/handler.py

Lambda 4 – Episodes API (Admin/Observability layer).

Provides a lightweight REST API via API Gateway HTTP API for internal
episode management. Allows querying DynamoDB for episode metadata and
generating short-lived presigned S3 URLs so reviewers can listen to
MP3 audio or read the transcript without direct S3 access.

Endpoints (all require the Authorization header set to ADMIN_API_KEY):
  GET /episodes                   – list episodes (optional ?date=YYYY-MM-DD, ?limit=N)
  GET /episodes/{episode_id}      – get a single episode's full metadata
  GET /episodes/{episode_id}/audio – presigned S3 URL for the MP3
  GET /episodes/{episode_id}/transcript – presigned S3 URL for the summary JSON

This Lambda is intentionally read-only; write operations happen through the
pipeline (Lambda 1 → Lambda 2 → Lambda 3).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

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
DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE_NAME"]
S3_BUCKET = os.environ["S3_BUCKET_NAME"]
# Simple bearer-token auth for the internal API (set as env var / secret).
# In production, replace with AWS IAM authoriser or Cognito.
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")
PRESIGNED_URL_EXPIRY = int(os.environ.get("PRESIGNED_URL_EXPIRY_SECONDS", "3600"))
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100

# ---------------------------------------------------------------------------
# AWS clients
# ---------------------------------------------------------------------------
dynamodb = boto3.resource("dynamodb")
episodes_table = dynamodb.Table(DYNAMODB_TABLE)
s3_client = boto3.client("s3")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def lambda_handler(event: dict, context: Any) -> dict:
    """
    API Gateway HTTP API v2 payload format handler.

    Routes requests based on the HTTP method and path, enforces simple
    API-key authentication, and returns JSON responses.
    """
    log.info(
        json.dumps(
            {
                "event": "request",
                "method": event.get("requestContext", {}).get("http", {}).get("method"),
                "path": event.get("rawPath"),
            }
        )
    )

    # ── Auth ──────────────────────────────────────────────────────────────────
    if ADMIN_API_KEY:
        auth_header = event.get("headers", {}).get("authorization", "")
        provided_key = auth_header.removeprefix("Bearer ").strip()
        if provided_key != ADMIN_API_KEY:
            return _response(401, {"error": "Unauthorized"})

    # ── Route ─────────────────────────────────────────────────────────────────
    http = event.get("requestContext", {}).get("http", {})
    method = http.get("method", "GET")
    raw_path = event.get("rawPath", "/")
    path_params = event.get("pathParameters") or {}
    query_params = event.get("queryStringParameters") or {}

    try:
        if raw_path == "/episodes" and method == "GET":
            return _list_episodes(query_params)

        episode_id = path_params.get("episode_id", "")

        if raw_path == f"/episodes/{episode_id}" and method == "GET":
            return _get_episode(episode_id)

        if raw_path == f"/episodes/{episode_id}/audio" and method == "GET":
            return _get_audio_url(episode_id)

        if raw_path == f"/episodes/{episode_id}/transcript" and method == "GET":
            return _get_transcript_url(episode_id)

        return _response(404, {"error": "Not found", "path": raw_path})

    except ClientError as exc:
        log.error(json.dumps({"event": "aws_error", "error": str(exc)}))
        return _response(500, {"error": "Internal server error"})
    except Exception as exc:  # pylint: disable=broad-except
        log.error(json.dumps({"event": "unhandled_error", "error": str(exc)}))
        return _response(500, {"error": "Internal server error"})


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _list_episodes(query_params: dict) -> dict:
    """
    Return a paginated list of episodes, newest first.

    Query parameters:
      date     – filter by YYYY-MM-DD run date (uses date-created_at-index GSI)
      category – filter by category (uses category-date-index GSI)
      limit    – max results to return (default 20, max 100)
    """
    limit = min(int(query_params.get("limit", DEFAULT_PAGE_LIMIT)), MAX_PAGE_LIMIT)
    date_filter = query_params.get("date")
    category_filter = query_params.get("category")

    if category_filter:
        # Use the category-date-index GSI to retrieve episodes for a specific category
        query_kwargs: dict = {
            "IndexName": "category-date-index",
            "KeyConditionExpression": Key("category").eq(category_filter),
            "ScanIndexForward": False,  # newest first
            "Limit": limit,
        }
        if date_filter:
            query_kwargs["KeyConditionExpression"] = (
                Key("category").eq(category_filter) & Key("date").eq(date_filter)
            )
        response = episodes_table.query(**query_kwargs)
    elif date_filter:
        # Use the date-created_at-index GSI to retrieve episodes for a specific date
        response = episodes_table.query(
            IndexName="date-created_at-index",
            KeyConditionExpression=Key("date").eq(date_filter),
            ScanIndexForward=False,  # newest first
            Limit=limit,
        )
    else:
        # Scan the full table (acceptable at small scale; add pagination for prod)
        response = episodes_table.scan(
            Limit=limit,
            FilterExpression=Attr("episode_id").exists(),
        )

    episodes = response.get("Items", [])
    # Sort by created_at descending when scanning without a GSI
    if not date_filter and not category_filter:
        episodes.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    log.info(
        json.dumps(
            {
                "event": "episodes_listed",
                "count": len(episodes),
                "category_filter": category_filter,
                "date_filter": date_filter,
            }
        )
    )
    return _response(
        200,
        {
            "episodes": [_serialise_episode(ep) for ep in episodes],
            "count": len(episodes),
            "date_filter": date_filter,
            "category_filter": category_filter,
        },
    )


def _get_episode(episode_id: str) -> dict:
    """Return full metadata for a single episode."""
    if not episode_id:
        return _response(400, {"error": "episode_id is required"})

    # Query using the partition key; date is the range key so we scan the
    # partition to handle calls where date is not provided.
    response = episodes_table.query(
        KeyConditionExpression=Key("episode_id").eq(episode_id),
    )
    items = response.get("Items", [])
    if not items:
        return _response(404, {"error": "Episode not found", "episode_id": episode_id})

    episode = items[0]
    log.info(json.dumps({"event": "episode_fetched", "episode_id": episode_id}))
    return _response(200, _serialise_episode(episode))


def _get_audio_url(episode_id: str) -> dict:
    """
    Return a short-lived presigned URL for the episode's MP3 audio file.
    This supports the 'Review MP3' flow shown in the Admin/Observability layer.
    """
    if not episode_id:
        return _response(400, {"error": "episode_id is required"})

    response = episodes_table.query(
        KeyConditionExpression=Key("episode_id").eq(episode_id),
    )
    items = response.get("Items", [])
    if not items:
        return _response(404, {"error": "Episode not found", "episode_id": episode_id})

    episode = items[0]
    audio_key = episode.get("audio_s3_key")
    if not audio_key:
        return _response(
            404,
            {
                "error": "Audio not yet generated for this episode",
                "episode_id": episode_id,
                "status": episode.get("status", "unknown"),
            },
        )

    presigned_url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": audio_key},
        ExpiresIn=PRESIGNED_URL_EXPIRY,
    )
    log.info(json.dumps({"event": "audio_url_generated", "episode_id": episode_id}))
    return _response(
        200,
        {
            "episode_id": episode_id,
            "audio_url": presigned_url,
            "expires_in_seconds": PRESIGNED_URL_EXPIRY,
        },
    )


def _get_transcript_url(episode_id: str) -> dict:
    """
    Return a short-lived presigned URL for the episode's summary/transcript JSON.
    This supports the 'Review Transcript' flow shown in the Admin/Observability layer.
    """
    if not episode_id:
        return _response(400, {"error": "episode_id is required"})

    response = episodes_table.query(
        KeyConditionExpression=Key("episode_id").eq(episode_id),
    )
    items = response.get("Items", [])
    if not items:
        return _response(404, {"error": "Episode not found", "episode_id": episode_id})

    episode = items[0]
    summary_key = episode.get("summary_s3_key")
    if not summary_key:
        return _response(
            404,
            {
                "error": "Transcript not yet generated for this episode",
                "episode_id": episode_id,
                "status": episode.get("status", "unknown"),
            },
        )

    presigned_url = s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": summary_key},
        ExpiresIn=PRESIGNED_URL_EXPIRY,
    )
    log.info(
        json.dumps({"event": "transcript_url_generated", "episode_id": episode_id})
    )
    return _response(
        200,
        {
            "episode_id": episode_id,
            "transcript_url": presigned_url,
            "expires_in_seconds": PRESIGNED_URL_EXPIRY,
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serialise_episode(episode: dict) -> dict:
    """Return a clean JSON-serialisable episode dict (strip DynamoDB Decimal types)."""
    import decimal

    result = {}
    for key, value in episode.items():
        if isinstance(value, decimal.Decimal):
            result[key] = int(value) if value % 1 == 0 else float(value)
        elif isinstance(value, list):
            result[key] = [
                (
                    int(v)
                    if isinstance(v, decimal.Decimal) and v % 1 == 0
                    else float(v) if isinstance(v, decimal.Decimal) else v
                )
                for v in value
            ]
        else:
            result[key] = value
    return result


def _response(status_code: int, body: dict) -> dict:
    """Build an API Gateway HTTP API v2 compatible response."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "X-Content-Type-Options": "nosniff",
        },
        "body": json.dumps(body),
    }
