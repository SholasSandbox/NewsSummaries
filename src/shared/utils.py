"""
shared/utils.py

Common utilities shared across all NewsSummaries Lambda functions.
Provides structured logging, AWS SSM secret retrieval with caching,
exponential backoff, episode ID generation, and RSS feed formatting.
"""

from __future__ import annotations

import functools
import io
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from email.utils import format_datetime
from typing import Any, Callable, TypeVar
from xml.etree import ElementTree as ET

import boto3
from botocore.exceptions import ClientError

F = TypeVar("F", bound=Callable[..., Any])

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_LOGGERS: dict[str, logging.Logger] = {}


def get_logger(name: str) -> logging.Logger:
    """
    Return a structured JSON logger suitable for CloudWatch Logs Insights.

    Logs are emitted as JSON to stdout, one object per line.  Each line
    contains ``time``, ``level``, ``logger``, and ``message`` fields.
    Additional fields can be embedded in the message by passing a JSON string.

    Args:
        name: Logger name (typically ``__name__``).

    Returns:
        Configured :class:`logging.Logger` instance.
    """
    if name in _LOGGERS:
        return _LOGGERS[name]

    import os
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            '{"time": "%(asctime)s", "level": "%(levelname)s", '
            '"logger": "%(name)s", "message": %(message)s}'
        ))
        logger.addHandler(handler)
    logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
    _LOGGERS[name] = logger
    return logger


# ---------------------------------------------------------------------------
# SSM Secret retrieval with in-process caching
# ---------------------------------------------------------------------------
_SECRET_CACHE: dict[str, str] = {}
_ssm_client = None


def _get_ssm_client() -> Any:
    global _ssm_client  # noqa: PLW0603
    if _ssm_client is None:
        _ssm_client = boto3.client("ssm")
    return _ssm_client


def get_secret(name: str, *, with_decryption: bool = True) -> str:
    """
    Retrieve a secret string from AWS SSM Parameter Store.

    Results are cached in-process so subsequent calls within the same Lambda
    execution environment do not incur additional API latency.

    Args:
        name: The full SSM parameter name (e.g. ``/news-summaries/openai-api-key``).
        with_decryption: Whether to decrypt SecureString parameters.

    Returns:
        The parameter value as a string.

    Raises:
        ClientError: If the parameter does not exist or access is denied.
    """
    if name in _SECRET_CACHE:
        return _SECRET_CACHE[name]

    ssm = _get_ssm_client()
    response = ssm.get_parameter(Name=name, WithDecryption=with_decryption)
    value = response["Parameter"]["Value"]
    _SECRET_CACHE[name] = value
    return value


def clear_secret_cache() -> None:
    """Clear the in-process SSM cache (useful in tests)."""
    _SECRET_CACHE.clear()


# ---------------------------------------------------------------------------
# Exponential backoff decorator
# ---------------------------------------------------------------------------

def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    """
    Decorator that retries the wrapped function with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts (not counting the first call).
        base_delay: Base delay in seconds. Actual delay = ``base_delay ** attempt``.
        exceptions: Tuple of exception types that should trigger a retry.

    Returns:
        Decorated function that retries on the specified exceptions.

    Example::

        @retry_with_backoff(max_retries=3, exceptions=(RateLimitError,))
        def call_openai(prompt: str) -> str:
            ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            logger = get_logger(func.__module__)
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if attempt >= max_retries:
                        raise
                    wait = base_delay ** (attempt + 1)
                    logger.warning(json.dumps({
                        "event": "retry",
                        "function": func.__name__,
                        "attempt": attempt + 1,
                        "max_retries": max_retries,
                        "wait_seconds": wait,
                        "error": str(exc),
                    }))
                    time.sleep(wait)
        return wrapper  # type: ignore[return-value]
    return decorator


# ---------------------------------------------------------------------------
# Episode ID
# ---------------------------------------------------------------------------

def generate_episode_id() -> str:
    """
    Generate a globally unique episode ID.

    Returns:
        A UUID4 string, e.g. ``"3f2504e0-4f89-11d3-9a0c-0305e82c3301"``.
    """
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# RSS Feed Formatting
# ---------------------------------------------------------------------------

def format_rss_feed(
    episodes: list[dict],
    *,
    podcast_title: str = "News Summaries",
    podcast_description: str = "Daily AI-powered news summaries",
    podcast_author: str = "News Summaries Bot",
    podcast_email: str = "podcast@example.com",
    feed_url: str = "",
) -> bytes:
    """
    Generate an iTunes-compatible podcast RSS 2.0 feed from a list of episode dicts.

    Each episode dict should contain at a minimum:
    - ``episode_id`` (str): Unique identifier used as the ``<guid>``.
    - ``title`` (str): Episode title.
    - ``summary`` (str): Episode description / summary text.
    - ``audio_url`` (str): Public URL to the MP3 audio file.
    - ``created_at`` (str): ISO-8601 creation timestamp.

    Args:
        episodes: List of episode metadata dicts (newest first).
        podcast_title: Podcast show title.
        podcast_description: Podcast show description.
        podcast_author: Author name shown in podcast apps.
        podcast_email: Author contact email.
        feed_url: Canonical URL of this RSS feed.

    Returns:
        UTF-8 encoded XML bytes ready to be uploaded to S3.
    """
    ET.register_namespace("itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
    ET.register_namespace("content", "http://purl.org/rss/1.0/modules/content/")

    rss = ET.Element("rss", {
        "version": "2.0",
        "xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
        "xmlns:content": "http://purl.org/rss/1.0/modules/content/",
    })
    channel = ET.SubElement(rss, "channel")

    def _txt(parent: ET.Element, tag: str, text: str, **attrib: str) -> ET.Element:
        el = ET.SubElement(parent, tag, attrib)
        el.text = text
        return el

    _txt(channel, "title", podcast_title)
    _txt(channel, "link", feed_url)
    _txt(channel, "description", podcast_description)
    _txt(channel, "language", "en-us")
    _txt(channel, "lastBuildDate", format_datetime(datetime.now(timezone.utc)))
    _txt(channel, "itunes:author", podcast_author)
    _txt(channel, "itunes:explicit", "false")
    _txt(channel, "itunes:type", "episodic")

    owner = ET.SubElement(channel, "itunes:owner")
    _txt(owner, "itunes:name", podcast_author)
    _txt(owner, "itunes:email", podcast_email)

    cat = ET.SubElement(channel, "itunes:category", {"text": "News"})
    ET.SubElement(cat, "itunes:category", {"text": "Daily News"})

    for ep in episodes:
        item = ET.SubElement(channel, "item")
        created_at_str = ep.get("created_at", datetime.now(timezone.utc).isoformat())
        try:
            pub_dt = datetime.fromisoformat(created_at_str)
        except ValueError:
            pub_dt = datetime.now(timezone.utc)

        _txt(item, "title", ep.get("title", "News Summary"))
        _txt(item, "description", ep.get("summary", ""))
        _txt(item, "guid", ep.get("episode_id", generate_episode_id()), isPermaLink="false")
        _txt(item, "pubDate", format_datetime(pub_dt))
        _txt(item, "itunes:summary", ep.get("summary", ""))
        _txt(item, "itunes:episodeType", "full")
        ET.SubElement(item, "enclosure", {
            "url": ep.get("audio_url", ""),
            "type": "audio/mpeg",
            "length": str(ep.get("audio_size_bytes", 0)),
        })

    tree = ET.ElementTree(rss)
    buf = io.BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()
