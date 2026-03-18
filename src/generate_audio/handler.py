"""
generate_audio/handler.py

Lambda handler that reads summaries from DynamoDB / S3, converts the text
to MP3 audio using the OpenAI TTS API (tts-1 model, "nova" voice), stores
the audio in S3, updates the DynamoDB episode record with the CloudFront
audio URL, and regenerates the RSS/podcast feed XML.
"""

from __future__ import annotations

import io
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any
from xml.etree import ElementTree as ET

import boto3
from botocore.exceptions import ClientError
from openai import OpenAI, RateLimitError, APIStatusError

# ---------------------------------------------------------------------------
# Structured logger
# ---------------------------------------------------------------------------

def _build_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            '{"time": "%(asctime)s", "level": "%(levelname)s", '
            '"logger": "%(name)s", "message": %(message)s}'
        ))
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
CLOUDFRONT_DOMAIN = os.environ.get("CLOUDFRONT_DOMAIN", "")
PODCAST_TITLE = os.environ.get("PODCAST_TITLE", "News Summaries")
PODCAST_DESCRIPTION = os.environ.get("PODCAST_DESCRIPTION", "Daily AI-powered news summaries")
PODCAST_AUTHOR = os.environ.get("PODCAST_AUTHOR", "News Summaries Bot")
PODCAST_EMAIL = os.environ.get("PODCAST_EMAIL", "podcast@example.com")
TTS_MODEL = "tts-1"
TTS_VOICE = "nova"
MAX_RETRIES = 3
BASE_BACKOFF = 2

RSS_FEED_KEY = "rss/feed.xml"

# ---------------------------------------------------------------------------
# AWS clients
# ---------------------------------------------------------------------------
s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
episodes_table = dynamodb.Table(DYNAMODB_TABLE)
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


def lambda_handler(event: dict, context: Any) -> dict:
    """
    Main Lambda entry point.

    Triggered by DynamoDB Streams. Processes INSERT events where the
    episode does not yet have an audio_url, generating TTS audio and
    updating the record + RSS feed.

    Returns a partial-batch response so failed records are retried.
    """
    batch_item_failures: list[dict] = []
    results = {"processed": 0, "failed": 0, "skipped": 0}

    for record in event.get("Records", []):
        sequence_number = record.get("dynamodb", {}).get("SequenceNumber", "")
        try:
            if record.get("eventName") != "INSERT":
                results["skipped"] += 1
                continue

            new_image = record.get("dynamodb", {}).get("NewImage", {})
            episode = _deserialise_dynamodb_item(new_image)

            if not episode.get("episode_id"):
                results["skipped"] += 1
                continue

            # Skip if audio already generated (safety guard)
            if episode.get("audio_url") and episode["audio_url"] is not None:
                results["skipped"] += 1
                continue

            _process_episode(episode)
            results["processed"] += 1

        except Exception as exc:  # noqa: BLE001
            log.error(json.dumps({
                "event": "record_error",
                "sequence_number": sequence_number,
                "error": str(exc),
            }))
            batch_item_failures.append({"itemIdentifier": sequence_number})
            results["failed"] += 1

    # Regenerate RSS feed after processing all records in the batch
    if results["processed"] > 0:
        try:
            _regenerate_rss_feed()
        except Exception as exc:  # noqa: BLE001
            log.error(json.dumps({"event": "rss_regeneration_error", "error": str(exc)}))

    log.info(json.dumps({"event": "batch_complete", **results}))
    return {"batchItemFailures": batch_item_failures}


# ---------------------------------------------------------------------------
# Episode processing
# ---------------------------------------------------------------------------

def _process_episode(episode: dict) -> None:
    """Generate TTS audio for one episode, store it, and update DynamoDB."""
    episode_id = episode["episode_id"]
    run_date = episode.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    summary_text = episode.get("summary", "")
    title = episode.get("title", "")

    if not summary_text:
        # Attempt to load summary from S3
        summary_s3_key = episode.get("summary_s3_key", "")
        if summary_s3_key:
            s3_doc = _read_s3_json(S3_BUCKET, summary_s3_key)
            summary_text = (s3_doc or {}).get("summary", "")

    if not summary_text:
        log.warning(json.dumps({"event": "no_summary_text", "episode_id": episode_id}))
        return

    tts_text = f"{title}. {summary_text}" if title else summary_text
    audio_bytes = _generate_tts_with_retry(tts_text)

    audio_key = f"audio/{run_date}/{episode_id}.mp3"
    _store_audio(audio_key, audio_bytes)

    audio_url = (
        f"https://{CLOUDFRONT_DOMAIN}/{audio_key}"
        if CLOUDFRONT_DOMAIN
        else f"https://s3.amazonaws.com/{S3_BUCKET}/{audio_key}"
    )

    _update_episode_audio_url(episode_id, run_date, audio_url, audio_key)

    log.info(json.dumps({
        "event": "audio_generated",
        "episode_id": episode_id,
        "audio_url": audio_url,
        "bytes": len(audio_bytes),
    }))


# ---------------------------------------------------------------------------
# OpenAI TTS
# ---------------------------------------------------------------------------

def _generate_tts_with_retry(text: str) -> bytes:
    """
    Convert text to speech using the OpenAI TTS API.
    Retries with exponential backoff on rate-limit and server errors.
    """
    for attempt in range(MAX_RETRIES):
        try:
            response = openai_client.audio.speech.create(
                model=TTS_MODEL,
                voice=TTS_VOICE,
                input=text[:4096],  # API hard limit
                response_format="mp3",
            )
            audio_buffer = io.BytesIO()
            for chunk in response.iter_bytes(chunk_size=4096):
                audio_buffer.write(chunk)
            return audio_buffer.getvalue()

        except RateLimitError as exc:
            wait = BASE_BACKOFF ** (attempt + 1)
            log.warning(json.dumps({
                "event": "tts_rate_limit",
                "attempt": attempt + 1,
                "wait_seconds": wait,
                "error": str(exc),
            }))
            if attempt < MAX_RETRIES - 1:
                time.sleep(wait)
            else:
                raise

        except APIStatusError as exc:
            log.error(json.dumps({"event": "tts_api_error", "status": exc.status_code, "error": str(exc)}))
            if exc.status_code >= 500 and attempt < MAX_RETRIES - 1:
                time.sleep(BASE_BACKOFF ** (attempt + 1))
                continue
            raise

    raise RuntimeError("TTS generation failed after all retries")


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------

def _store_audio(key: str, audio_bytes: bytes) -> None:
    """Upload MP3 audio bytes to S3."""
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=audio_bytes,
        ContentType="audio/mpeg",
        CacheControl="public, max-age=86400",
    )


def _read_s3_json(bucket: str, key: str) -> dict | None:
    """Read and deserialise a JSON object from S3."""
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        return json.loads(response["Body"].read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.error(json.dumps({"event": "s3_read_error", "key": key, "error": str(exc)}))
        return None


# ---------------------------------------------------------------------------
# DynamoDB helpers
# ---------------------------------------------------------------------------

def _update_episode_audio_url(episode_id: str, date: str, audio_url: str, audio_key: str) -> None:
    """Update the DynamoDB episode record with the generated audio URL."""
    episodes_table.update_item(
        Key={"episode_id": episode_id, "date": date},
        UpdateExpression="SET audio_url = :url, audio_s3_key = :key, updated_at = :ts",
        ExpressionAttributeValues={
            ":url": audio_url,
            ":key": audio_key,
            ":ts": datetime.now(timezone.utc).isoformat(),
        },
    )


def _deserialise_dynamodb_item(item: dict) -> dict:
    """Convert a DynamoDB Streams item (with type descriptors) to a plain dict."""
    from boto3.dynamodb.types import TypeDeserializer
    deserializer = TypeDeserializer()
    return {k: deserializer.deserialize(v) for k, v in item.items()}


# ---------------------------------------------------------------------------
# RSS Feed Generation
# ---------------------------------------------------------------------------

def _regenerate_rss_feed() -> None:
    """
    Query the DynamoDB table for the most recent 50 episodes that have audio,
    generate a valid iTunes/podcast RSS feed XML, and upload it to S3.
    """
    episodes = _get_recent_episodes_with_audio(limit=50)
    if not episodes:
        log.info(json.dumps({"event": "rss_no_episodes"}))
        return

    xml_bytes = _build_rss_xml(episodes)
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=RSS_FEED_KEY,
        Body=xml_bytes,
        ContentType="application/rss+xml; charset=utf-8",
        CacheControl="public, max-age=900",  # 15 min cache
    )
    log.info(json.dumps({"event": "rss_feed_updated", "episodes": len(episodes)}))


def _get_recent_episodes_with_audio(limit: int = 50) -> list[dict]:
    """Scan DynamoDB for the most recent episodes that have an audio_url."""
    try:
        response = episodes_table.scan(
            FilterExpression=boto3.dynamodb.conditions.Attr("audio_url").exists()
            & boto3.dynamodb.conditions.Attr("audio_url").ne(None),
            Limit=limit * 3,  # over-fetch to compensate for filter reductions
        )
        items = response.get("Items", [])
        items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return items[:limit]
    except Exception as exc:  # noqa: BLE001
        log.error(json.dumps({"event": "dynamodb_scan_error", "error": str(exc)}))
        return []


def _build_rss_xml(episodes: list[dict]) -> bytes:
    """Build a valid iTunes-compatible podcast RSS feed from episode records."""
    ET.register_namespace("itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
    ET.register_namespace("content", "http://purl.org/rss/1.0/modules/content/")

    rss = ET.Element("rss", {
        "version": "2.0",
        "xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
        "xmlns:content": "http://purl.org/rss/1.0/modules/content/",
    })

    channel = ET.SubElement(rss, "channel")
    feed_url = (
        f"https://{CLOUDFRONT_DOMAIN}/{RSS_FEED_KEY}"
        if CLOUDFRONT_DOMAIN
        else f"https://s3.amazonaws.com/{S3_BUCKET}/{RSS_FEED_KEY}"
    )

    _add_text(channel, "title", PODCAST_TITLE)
    _add_text(channel, "link", feed_url)
    _add_text(channel, "description", PODCAST_DESCRIPTION)
    _add_text(channel, "language", "en-us")
    _add_text(channel, "lastBuildDate", format_datetime(datetime.now(timezone.utc)))
    _add_text(channel, "itunes:author", PODCAST_AUTHOR)
    _add_text(channel, "itunes:explicit", "false")
    _add_text(channel, "itunes:type", "episodic")

    owner = ET.SubElement(channel, "itunes:owner")
    _add_text(owner, "itunes:name", PODCAST_AUTHOR)
    _add_text(owner, "itunes:email", PODCAST_EMAIL)

    category = ET.SubElement(channel, "itunes:category", {"text": "News"})
    ET.SubElement(category, "itunes:category", {"text": "Daily News"})

    for episode in episodes:
        _add_rss_item(channel, episode)

    tree = ET.ElementTree(rss)
    buf = io.BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()


def _add_rss_item(channel: ET.Element, episode: dict) -> None:
    """Append a single <item> element to the RSS channel for an episode."""
    item = ET.SubElement(channel, "item")
    audio_url = episode.get("audio_url", "")
    episode_id = episode.get("episode_id", "")
    title = episode.get("title", "News Summary")
    summary = episode.get("summary", "")
    created_at_str = episode.get("created_at", datetime.now(timezone.utc).isoformat())

    try:
        created_at = datetime.fromisoformat(created_at_str)
    except ValueError:
        created_at = datetime.now(timezone.utc)

    _add_text(item, "title", title)
    _add_text(item, "description", summary)
    _add_text(item, "guid", episode_id, attrib={"isPermaLink": "false"})
    _add_text(item, "pubDate", format_datetime(created_at))
    _add_text(item, "itunes:summary", summary)
    _add_text(item, "itunes:episodeType", "full")
    ET.SubElement(item, "enclosure", {
        "url": audio_url,
        "type": "audio/mpeg",
        "length": "0",  # length unknown at feed-generation time
    })


def _add_text(parent: ET.Element, tag: str, text: str, attrib: dict | None = None) -> ET.Element:
    """Helper to create a sub-element with text content."""
    el = ET.SubElement(parent, tag, attrib or {})
    el.text = text
    return el
