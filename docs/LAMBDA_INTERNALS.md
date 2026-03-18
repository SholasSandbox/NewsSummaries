# Lambda Handler Internals — NewsSummaries

This document walks through the internals of every Lambda function in the
NewsSummaries pipeline. It is written as a learning resource: each section
explains **why** the code is structured the way it is, not just what it does.

---

## Background: What is a Lambda Handler?

AWS Lambda runs your code in response to an **event**. You tell Lambda which
Python function to call by setting the `handler` configuration value
(e.g. `handler.lambda_handler`). AWS will call that function with two arguments:

```python
def lambda_handler(event: dict, context: Any) -> dict:
    ...
```

| Parameter | Type | What it contains |
|---|---|---|
| `event` | `dict` | The triggering payload — differs per event source (see below) |
| `context` | `LambdaContext` | Runtime metadata: `function_name`, `aws_request_id`, `get_remaining_time_in_millis()` |

The function's **return value** is sent back to the caller (synchronous
invocations) or ignored (asynchronous `InvocationType=Event` invocations).
A well-structured handler:
1. Reads configuration from environment variables
2. Parses the event
3. Calls helpers that do the actual work
4. Returns a standardised response dict

---

## Cold Starts vs Warm Starts

Lambda reuses execution environments between invocations (**warm start**).
Code at **module level** runs only once, on the **cold start**. This is a
critical performance and cost pattern used throughout this project.

```
First invocation (cold start)
─────────────────────────────
  1. AWS downloads and unzips your deployment package
  2. Python interpreter starts
  3. All import statements run
  4. All module-level statements run (e.g. boto3.client("s3"))  ← one-time cost
  5. lambda_handler() is called

Subsequent invocations (warm start)
────────────────────────────────────
  1. lambda_handler() is called directly                        ← fast path
```

**Rule of thumb**: Create AWS SDK clients and load configuration at module
level. Only do per-request work inside the handler function.

---

## Lambda 1 — IngestNews (`src/ingest_news/handler.py`)

### Trigger
EventBridge Scheduler fires at `cron(0 6 * * ? *)` and `cron(0 18 * * ? *)`
(6 AM and 6 PM UTC). The event payload from EventBridge is minimal:
```json
{ "version": "0", "id": "...", "source": "aws.scheduler", "detail-type": "Scheduled Event", "detail": {} }
```
IngestNews ignores the event payload entirely — it is used purely as a clock tick.

### Handler walkthrough

```python
def lambda_handler(event: dict, context: Any) -> dict:
    run_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")  # used as S3 prefix
    articles = _fetch_all_rss_articles()                         # network I/O
    if NEWS_API_ENABLED:
        articles.extend(_fetch_newsapi_articles())               # optional
    unique_articles = _deduplicate(articles)                     # in-memory dedup
    stored_keys = _store_articles(unique_articles, run_date)     # S3 writes
    if stored_keys and GENERATE_SUMMARIES_FUNCTION:
        _invoke_generate_summaries(stored_keys)                  # async Lambda invocations
    return {"statusCode": 200, "body": json.dumps({...})}
```

### Deduplication — why SHA-256?

The same article can appear in multiple RSS feeds (e.g. Reuters UK and
Reuters World both carry the same story). The hash is computed from the
URL + title, lowercased:

```python
def _article_hash(article: dict) -> str:
    key = f"{article['url']}|{article['title']}".lower()
    return hashlib.sha256(key.encode()).hexdigest()[:16]
```

Only 16 hex characters (64 bits) are taken — sufficient for the dedup window
of a single 12-hour ingest run (collision probability is negligible at ~200
articles per run).

The hash doubles as the **S3 object key**: `raw/YYYY-MM-DD/{hash}.json`.
This makes the storage step **idempotent**: if `s3.head_object()` succeeds,
the article already exists and is skipped.

### S3 idempotency pattern

```python
try:
    s3.head_object(Bucket=S3_BUCKET, Key=s3_key)
    continue          # already stored — skip
except ClientError:
    pass              # object not found — proceed to write

s3.put_object(...)    # only reached for new articles
```

`head_object` costs ~$0.0004 per 10 000 calls — essentially free for the
volume here, and far cheaper than a re-summarisation retry.

### Async fan-out

Instead of invoking GenerateSummaries and waiting for the response
(which would burn IngestNews's 300-second timeout), it fires
`InvocationType="Event"` — fire-and-forget:

```python
lambda_client.invoke(
    FunctionName=GENERATE_SUMMARIES_FUNCTION,
    InvocationType="Event",   # ← async, returns immediately
    Payload=json.dumps(payload),
)
time.sleep(0.05)              # gentle rate limiting between invocations
```

Each article becomes an independent, parallel Lambda invocation with its own
300-second budget. This is the classic **fan-out** pattern.

### Key environment variables

| Variable | Purpose |
|---|---|
| `S3_BUCKET_NAME` | Target S3 bucket |
| `GENERATE_SUMMARIES_FUNCTION` | Lambda function name or ARN to fan out to |
| `NEWS_API_KEY` | Set to `DISABLED` to skip NewsAPI |
| `RSS_FEEDS` | Comma-separated feed URLs (overrides the hardcoded list) |

---

## Lambda 2 — GenerateSummaries (`src/generate_summaries/handler.py`)

### Trigger — two invocation modes

This handler is written to accept events from **two different sources**,
normalised by `_extract_records()`:

```
Mode 1: Direct invoke from IngestNews
  event = {"source": "ingest_news", "s3_key": "raw/2024-01-15/abc123.json", "bucket": "..."}

Mode 2: S3 event notification (raw/ prefix trigger)
  event = {"Records": [{"s3": {"bucket": {...}, "object": {"key": "..."}}}]}
```

This dual-mode design means the Lambda can be triggered either way without
any code change — useful when testing and when retrying failed articles
directly from the S3 console.

```python
def _extract_records(event: dict) -> list[dict[str, str]]:
    if "Records" in event:                         # S3 notification
        ...
    if "s3_key" in event:                          # direct invoke
        return [{"bucket": ..., "key": event["s3_key"]}]
    return []
```

### Module-level AWS clients

```python
# ← these run ONCE per cold start
s3_client = boto3.client("s3")
dynamodb   = boto3.resource("dynamodb")
episodes_table = dynamodb.Table(DYNAMODB_TABLE)
openai_client  = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
```

The `OpenAI` client establishes an HTTP session on construction. Keeping it
at module level means the session (and its connection pool) is reused across
warm invocations, saving ~200 ms on every article after the first in a run.

### OpenAI prompt engineering

The system prompt and user template enforce **JSON-only output**:

```python
SUMMARY_SYSTEM_PROMPT = """... Always respond with valid JSON only."""

SUMMARY_USER_TEMPLATE = """...
Respond ONLY with this JSON structure:
{
  "summary": "2-3 sentence summary here",
  "category": "one of: general|world|...",
  "importance": "one of: high|medium|low",
  "keywords": ["keyword1", "keyword2", "keyword3"]
}"""
```

`response_format={"type": "json_object"}` is also set on the API call, which
tells the model to guarantee valid JSON output.

### Retry with exponential backoff

OpenAI applies rate limits per minute. The retry loop implements
**exponential backoff** — waiting 2¹, 2², 2³ seconds before each retry:

```python
for attempt in range(MAX_RETRIES):       # MAX_RETRIES = 3
    try:
        response = openai_client.chat.completions.create(...)
        return _validate_summary_result(...)

    except RateLimitError:
        wait = BASE_BACKOFF ** (attempt + 1)   # 2, 4, 8 seconds
        time.sleep(wait)                        # only if retries remain
        ...

    except (json.JSONDecodeError, KeyError):
        return _fallback_summary(article)       # degrade gracefully
```

The **fallback** path returns the raw article text truncated to 500 characters
instead of raising. This ensures a DynamoDB record (and eventually audio) is
always produced — degraded quality is better than a missing episode.

### Validation layer

`_validate_summary_result()` whitelists the `category` and `importance` fields:

```python
valid_categories = {"general", "world", "business", ...}
valid_importance = {"high", "medium", "low"}

return {
    "category": result.get("category") if result.get("category") in valid_categories else "general",
    "importance": result.get("importance") if result.get("importance") in valid_importance else "medium",
    ...
}
```

This prevents the AI from returning unexpected values that would break downstream
DynamoDB queries (e.g. `category-date-index` GSI queries by exact category string).

### DynamoDB write with TTL

```python
ttl = int(time.time()) + (90 * 24 * 3600)  # now + 90 days
episodes_table.put_item(
    Item={
        "episode_id": episode_id,
        "date": run_date,
        ...,
        "audio_url": None,   # ← triggers Lambda 3 via DynamoDB Streams
        "ttl": ttl,
    }
)
```

Setting `audio_url = None` is intentional. Lambda 3 (GenerateAudio) is
triggered by a DynamoDB Streams INSERT event filtered to items where
`status = "summarized"` — but the stream fires on any INSERT. Lambda 3
checks for a missing `audio_url` as a safety guard to avoid re-processing.

The TTL attribute causes DynamoDB to automatically delete items after 90 days,
keeping the table small and cost-effective.

---

## Lambda 3 — GenerateAudio (`src/generate_audio/handler.py`)

### Trigger — DynamoDB Streams

DynamoDB Streams publishes change records when items are written to the
table. The Terraform `aws_lambda_event_source_mapping` resource filters
for INSERT events where `status = "summarized"`. The event payload looks like:

```json
{
  "Records": [
    {
      "eventName": "INSERT",
      "dynamodb": {
        "SequenceNumber": "111",
        "NewImage": {
          "episode_id": {"S": "abc-123"},
          "title":      {"S": "AI Breakthrough"},
          "summary":    {"S": "Scientists announce..."},
          "date":       {"S": "2024-01-15"}
        }
      }
    }
  ]
}
```

Notice the **DynamoDB type descriptors** (`{"S": "..."}` for strings,
`{"N": "123"}` for numbers). These must be deserialised before use:

```python
def _deserialise_dynamodb_item(item: dict) -> dict:
    from boto3.dynamodb.types import TypeDeserializer
    deserializer = TypeDeserializer()
    return {k: deserializer.deserialize(v) for k, v in item.items()}
```

This is a common Lambda pattern — the import is inside the function rather
than at module level, which is fine here since it's only called once per record.

### Partial-batch failure response

Lambda's DynamoDB event source supports **partial-batch failure**: rather
than retrying the entire batch when one record fails, you can return only the
failed record identifiers:

```python
batch_item_failures: list[dict] = []

for record in event.get("Records", []):
    sequence_number = record["dynamodb"]["SequenceNumber"]
    try:
        _process_episode(episode)
    except Exception:
        batch_item_failures.append({"itemIdentifier": sequence_number})

return {"batchItemFailures": batch_item_failures}  # ← partial-batch response
```

If a record fails, Lambda re-delivers only that record. Combined with
`bisect_batch_on_function_error = true` in Terraform, this isolates
poison-pill records instead of stalling the entire stream shard.

### OpenAI TTS streaming

The TTS response is streamed in 4 KB chunks into a `BytesIO` buffer:

```python
response = openai_client.audio.speech.create(
    model=TTS_MODEL,           # "tts-1"
    voice=TTS_VOICE,           # "nova"
    input=text[:4096],         # hard API limit
    response_format="mp3",
)
audio_buffer = io.BytesIO()
for chunk in response.iter_bytes(chunk_size=4096):
    audio_buffer.write(chunk)
return audio_buffer.getvalue()
```

Using `iter_bytes()` avoids holding the entire MP3 in memory at once during
download, which matters for Lambda's memory limit (1024 MB for this function).

### RSS feed regeneration

After processing all records in a batch, the handler rebuilds the entire RSS
feed from scratch using Python's standard library `xml.etree.ElementTree`:

```python
def _build_rss_xml(episodes: list[dict]) -> bytes:
    rss = ET.Element("rss", {"version": "2.0", "xmlns:itunes": "..."})
    channel = ET.SubElement(rss, "channel")
    # ... channel metadata ...
    for episode in episodes:
        _add_rss_item(channel, episode)
    buf = io.BytesIO()
    ET.ElementTree(rss).write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue()
```

The feed is then uploaded with a 15-minute CloudFront cache TTL
(`Cache-Control: public, max-age=900`) — short enough that new episodes
appear promptly in podcast apps, but long enough to avoid hammering S3.

### Key design decisions

| Decision | Rationale |
|---|---|
| Rebuild entire feed (not append) | Ensures feed is always correct even if a prior run failed mid-way |
| Scan DynamoDB for `audio_url` != null | Simple and correct at current scale; replace with GSI query at high volume |
| `CacheControl: public, max-age=86400` on MP3 | Audio files are immutable once written; 24-hour CDN cache saves S3 costs |

---

## Lambda 4 — EpisodesAPI (`src/episodes_api/handler.py`)

### Trigger — API Gateway HTTP API v2

When an HTTP request hits the API Gateway, Lambda receives a structured
**payload format v2** event:

```json
{
  "rawPath": "/episodes/abc-123/audio",
  "requestContext": {
    "http": { "method": "GET" }
  },
  "pathParameters": { "episode_id": "abc-123" },
  "queryStringParameters": { "date": "2024-01-15" },
  "headers": { "authorization": "Bearer secret-key" }
}
```

The response must match the format that API Gateway expects:

```python
return {
    "statusCode": 200,
    "headers": {"Content-Type": "application/json"},
    "body": json.dumps(result),      # ← must be a string, not a dict
}
```

This is different from all the pipeline Lambdas, which return dicts freely.
The `body` field **must be a JSON string**, not a nested dict — API Gateway
serialises `body` verbatim into the HTTP response body.

### Authentication pattern

Rather than a full Cognito or OAuth setup (overkill for an internal admin
tool), a simple **bearer-token check** is applied:

```python
if ADMIN_API_KEY:
    auth_header = event.get("headers", {}).get("authorization", "")
    provided_key = auth_header.removeprefix("Bearer ").strip()
    if provided_key != ADMIN_API_KEY:
        return _response(401, {"error": "Unauthorized"})
```

The `if ADMIN_API_KEY:` guard means auth is **skipped entirely when the
variable is empty** — intentionally, for local/test environments where
setting a key would add friction.

In production, consider replacing this with an **API Gateway Lambda
authoriser** or AWS IAM authentication so the key never travels in HTTP headers.

### Router pattern

Python doesn't have a built-in HTTP router, so this handler implements a
minimal one by matching the `rawPath` string:

```python
if raw_path == "/episodes" and method == "GET":
    return _list_episodes(query_params)

episode_id = path_params.get("episode_id", "")

if raw_path == f"/episodes/{episode_id}" and method == "GET":
    return _get_episode(episode_id)

if raw_path == f"/episodes/{episode_id}/audio" and method == "GET":
    return _get_audio_url(episode_id)
```

For a larger API, a library like [aws-lambda-powertools Router](https://docs.powertools.aws.dev/lambda/python/latest/core/event_handler/api_gateway/)
would be more appropriate. This inline router is intentionally kept simple
because there are only four routes.

### Presigned S3 URLs

Rather than streaming the MP3 through Lambda (which would be slow and
expensive), the handler generates a **presigned URL** — a time-limited,
pre-authenticated S3 URL the client can download directly:

```python
presigned_url = s3_client.generate_presigned_url(
    "get_object",
    Params={"Bucket": S3_BUCKET, "Key": audio_key},
    ExpiresIn=3600,   # URL valid for 1 hour
)
```

The presigned URL is signed with the Lambda's IAM role credentials. No S3
bucket public access is needed — the URL grants temporary access to that
specific object only.

### DynamoDB Decimal serialisation

DynamoDB's Python SDK returns numeric values as `decimal.Decimal` objects
(to avoid floating-point precision loss). JSON's `json.dumps()` cannot
serialise `Decimal` natively — it raises a `TypeError`. The handler has a
dedicated cleaner:

```python
def _serialise_episode(episode: dict) -> dict:
    import decimal
    result = {}
    for key, value in episode.items():
        if isinstance(value, decimal.Decimal):
            result[key] = int(value) if value % 1 == 0 else float(value)
        ...
    return result
```

This pattern appears in any project that reads from DynamoDB and then
serialises to JSON — remember it.

---

## Patterns Common to All Four Handlers

### 1. JSON-structured logging

All handlers use the same logger factory that emits **structured JSON** lines
to stdout (which CloudWatch Logs captures):

```python
def _build_logger(name: str) -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        '{"time": "%(asctime)s", "level": "%(levelname)s", '
        '"logger": "%(name)s", "message": %(message)s}'
    ))
    ...
```

Note: `%(message)s` is **not** quoted — the message is itself a JSON string
(`json.dumps({...})`), so the final log line is valid JSON:

```json
{"time": "2024-01-15 06:00:01", "level": "INFO", "logger": "handler", "message": {"event": "articles_stored", "count": 47}}
```

This lets CloudWatch Logs Insights query log fields directly, e.g.:
```
fields @timestamp, message.event, message.count
| filter message.event = "articles_stored"
```

### 2. Configuration from environment variables

```python
S3_BUCKET = os.environ["S3_BUCKET_NAME"]          # raises KeyError if missing — fail fast
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")  # optional — safe default
```

`os.environ["KEY"]` raises `KeyError` at cold-start if a required variable is
missing. This is deliberate — it's better to fail immediately with a clear
error than to crash mid-execution with a confusing `NoneType` error.

### 3. Module-level AWS client initialisation

```python
# ← module level (cold start)
s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
episodes_table = dynamodb.Table(DYNAMODB_TABLE)
```

`boto3.client()` creates an HTTPS session to the AWS endpoint. Doing this at
module level means the connection is established once and reused. If done
inside the handler, every invocation would pay the TCP handshake cost (~50 ms).

### 4. Error isolation — broad except with logging

Each handler uses a try/except around individual records (not the whole batch):

```python
for record in records:
    try:
        _process_one(record)
        results["processed"] += 1
    except Exception as exc:
        log.error(json.dumps({"event": "record_error", "error": str(exc)}))
        results["failed"] += 1
```

One bad article never blocks the rest of the batch. Failed records are counted
and returned (or sent to DLQ) rather than silently swallowed.

### 5. `from __future__ import annotations`

```python
from __future__ import annotations
```

This enables **postponed evaluation of type annotations** (PEP 563). It allows
writing `list[dict]`, `dict | None`, etc. in Python 3.9+ syntax even if
running on a Python version that doesn't support it natively. Enables cleaner
type hints without the older `Optional[dict]` / `List[dict]` forms from
`typing`.

---

## Event Source Summary

| Lambda | Trigger | Event shape |
|---|---|---|
| IngestNews | EventBridge Scheduler | `{"source": "aws.scheduler", "detail": {}}` — ignored |
| GenerateSummaries | IngestNews (async invoke) | `{"s3_key": "...", "bucket": "..."}` |
| GenerateSummaries | S3 event notification | `{"Records": [{"s3": {...}}]}` |
| GenerateAudio | DynamoDB Streams | `{"Records": [{"eventName": "INSERT", "dynamodb": {"NewImage": {...}}}]}` |
| EpisodesAPI | API Gateway HTTP API v2 | `{"rawPath": "...", "requestContext": {...}, "headers": {...}}` |

---

## Further Reading

- [AWS Lambda Programming Model (Python)](https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html)
- [Understanding Lambda execution environments](https://docs.aws.amazon.com/lambda/latest/dg/lambda-runtime-environment.html)
- [DynamoDB Streams event reference](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Streams.Lambda.html)
- [API Gateway HTTP API payload format v2](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-lambda.html)
- [AWS Lambda Powertools for Python](https://docs.powertools.aws.dev/lambda/python/latest/) — recommended for production-grade structured logging, tracing, and routing
