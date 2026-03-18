# Architecture — NewsSummaries

## System Overview

NewsSummaries is a fully serverless, event-driven pipeline deployed on AWS that:

1. **Ingests** breaking news twice daily from RSS feeds (BBC, Reuters, AP, NPR, The Guardian, Ars Technica) and optionally from NewsAPI.org.
2. **Summarises** each article using OpenAI's `o3-mini` model into a 2–3 sentence structured summary with category and importance tags.
3. **Converts** each summary to speech using OpenAI's TTS API (`tts-1`, `nova` voice) and stores the audio as an MP3.
4. **Distributes** audio files via CloudFront and publishes a standard iTunes-compatible RSS/podcast feed.
5. **Exposes** an internal Episodes API (Lambda 4) for admin review of episode metadata, audio files, and transcripts.

All infrastructure is defined as code using **HashiCorp Terraform** (`terraform/` directory) and can be deployed or torn down in a single command.

---

## Component Descriptions

| Component | AWS Service | Purpose |
|---|---|---|
| Scheduler | EventBridge Scheduler | Triggers ingest twice daily (06:00 & 18:00 UTC) |
| Lambda 1 – IngestNews | Lambda (Python 3.11, arm64) | Fetches RSS + NewsAPI, deduplicates, writes raw articles to S3 |
| Lambda 2 – GenerateSummaries | Lambda (Python 3.11, arm64) | OpenAI o3-mini summarisation, writes summaries to S3 + DynamoDB |
| Lambda 3 – GenerateAudio | Lambda (Python 3.11, arm64) | OpenAI TTS MP3 generation, writes audio to S3, updates DynamoDB + RSS |
| Lambda 4 – EpisodesAPI | Lambda (Python 3.11, arm64) | Internal admin API: query episode metadata, stream presigned audio/transcript URLs |
| S3 – Raw Articles | S3 | Stores raw ingested news JSON (`raw/`) |
| S3 – Episodes + Scripts | S3 | Stores AI summaries (`summaries/`) and MP3 audio (`audio/`) |
| Episode Metadata | DynamoDB (on-demand) | Queryable record per episode with GSIs |
| Podcast Delivery | CloudFront | Low-latency, HTTPS-only audio and RSS feed distribution |
| Episodes API Gateway | API Gateway HTTP API (optional) | Public-facing HTTPS endpoint fronting Lambda 4 |
| Dead Letter Queues | SQS | Captures failed Lambda invocations for inspection |
| Alerting | SNS → Email | Notifies on error alarm threshold breach |
| Observability | CloudWatch Logs + Alarms + Dashboard | Structured JSON logs, error rate alarms, metrics |

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                        EventBridge Scheduler                         │
│              cron(0 6 * * ? *)   cron(0 18 * * ? *)                │
└────────────────────────────┬────────────────────────────────────────┘
                             │ Invoke
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│                      Lambda: IngestNews                             │
│  1. Fetch RSS feeds (BBC, Reuters, AP, NPR, Guardian, Ars Tech)    │
│  2. Optionally fetch NewsAPI top headlines                          │
│  3. Deduplicate via SHA-256(url + title)                            │
│  4. PUT raw/{date}/{hash}.json  ──────────────────────────────────►│
│  5. Async invoke GenerateSummaries per new article                  │
└────────────────────────────────────────────────────────────────────┘
                             │ S3 PutObject notification (raw/)
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│                   Lambda: GenerateSummaries                         │
│  1. Read raw article JSON from S3                                   │
│  2. Call OpenAI o3-mini → structured JSON summary                   │
│  3. PUT summaries/{date}/{hash}.json  ────────────────────────────►│
│  4. PutItem → DynamoDB EpisodesTable (no audio_url yet)            │
└────────────────────────────────────────────────────────────────────┘
                             │ DynamoDB Stream INSERT event
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│                    Lambda: GenerateAudio                            │
│  1. Read summary text from DynamoDB stream event                    │
│  2. Call OpenAI TTS (tts-1, nova) → MP3 bytes                      │
│  3. PUT audio/{date}/{episode_id}.mp3  ───────────────────────────►│
│  4. UpdateItem DynamoDB with CloudFront audio_url                   │
│  5. Regenerate RSS feed → PUT rss/feed.xml                          │
└────────────────────────────────────────────────────────────────────┘
                             │
                ┌────────────┴────────────┐
                ▼                         ▼
   ┌────────────────────┐    ┌──────────────────────────┐
   │   CloudFront CDN   │    │   RSS / Podcast Feed      │
   │  audio/*.mp3 via   │    │  rss/feed.xml (via CF)    │
   │  HTTPS + OAC       │    │  iTunes / Overcast / etc  │
   └────────────────────┘    └──────────────────────────┘

┌─────────────────────────────────────── Admin / Observability ──────┐
│                                                                     │
│  DynamoDB (Episodes Metadata)                                       │
│       │ Query episodes by date / ID                                 │
│       ▼                                                             │
│  Lambda 4: EpisodesAPI                                              │
│  1. GET /episodes            → list episode metadata                │
│  2. GET /episodes/{id}       → full episode record                  │
│  3. GET /episodes/{id}/audio → presigned S3 URL (MP3 review)       │
│  4. GET /episodes/{id}/transcript → presigned S3 URL (JSON review) │
│       │ (optional)                                                  │
│       ▼                                                             │
│  API Gateway HTTP API  →  Admin Episodes UI (future)               │
│  (enable_api_gateway = true to activate)                            │
└─────────────────────────────────────────────────────────────────────┘
```

### S3 Key Structure

```
news-summaries-{stage}/
├── raw/
│   └── {YYYY-MM-DD}/
│       └── {16-char-hash}.json          # raw ingested article
├── summaries/
│   └── {YYYY-MM-DD}/
│       └── {16-char-hash}.json          # AI-generated summary + metadata
├── audio/
│   └── {YYYY-MM-DD}/
│       └── {uuid}.mp3                   # TTS-generated MP3 audio
├── rss/
│   └── feed.xml                         # iTunes RSS podcast feed
└── cloudfront-logs/                     # CloudFront access logs
```

### DynamoDB Schema

**Table:** `news-summaries-episodes-{stage}`

| Attribute | Type | Description |
|---|---|---|
| `episode_id` (PK) | String | UUID v4 |
| `date` (SK) | String | YYYY-MM-DD run date |
| `created_at` | String | ISO-8601 timestamp |
| `title` | String | Article title |
| `source` | String | Feed/publisher name |
| `url` | String | Original article URL |
| `summary` | String | AI-generated 2–3 sentence summary |
| `category` | String | general \| world \| business \| technology \| science \| health |
| `importance` | String | high \| medium \| low |
| `keywords` | List | Up to 10 keywords |
| `audio_url` | String | CloudFront URL to MP3 (null until generated) |
| `ttl` | Number | Unix epoch – item expires after 90 days |

**GSIs:**
- `date-created_at-index` — query all episodes for a given date, newest first
- `category-date-index` — query episodes by category and date

---

## Technology Choices & Rationale

### Terraform vs AWS SAM / CloudFormation
Terraform was chosen because:
- **Provider-agnostic**: State and modules work identically on AWS, GCP, or Azure — valuable for a Solutions Architect portfolio
- **Explicit dependency graph**: `terraform plan` shows a precise diff of every change before apply, reducing surprises in production
- **Rich ecosystem**: The [Terraform Registry](https://registry.terraform.io) offers community modules (e.g., `terraform-aws-modules/lambda`) and thousands of providers
- **Remote state**: S3 backend with DynamoDB locking supports team collaboration out of the box
- **Industry standard**: Used by the majority of AWS shops; a sought-after skill in SA roles
- AWS SAM offers simpler local invocation (`sam local`) but ties you to the AWS CloudFormation API and produces less readable state diffs

### OpenAI o3-mini vs Amazon Bedrock / Comprehend
- `o3-mini` delivers superior summary quality with very low cost ($1.10/M input tokens)
- No model fine-tuning required
- Amazon Polly is cheaper for TTS but produces noticeably less natural speech than `tts-1`
- OpenAI TTS `nova` voice sounds indistinguishable from a human broadcaster

### DynamoDB on-demand vs Provisioned
- On-demand chosen because traffic is bursty (two spikes per day) and low volume overall
- No capacity planning required
- At scale (>10M requests/month), switch to provisioned with auto-scaling

### CloudFront vs Direct S3 URLs
- HTTPS enforcement without custom certificates on S3
- Edge caching reduces S3 GET costs significantly
- Origin Access Control (OAC) keeps S3 bucket fully private

### arm64 (Graviton2) Lambda
- ~20% faster cold starts and ~34% lower cost than x86_64 for Python workloads
- Compatible with all dependencies used in this project

---

## Scalability Considerations

- **Horizontal scaling**: Each Lambda invocation is stateless; AWS scales concurrency automatically.
- **DynamoDB**: On-demand billing scales to millions of writes per second with no configuration.
- **S3**: Virtually unlimited storage; lifecycle policies prevent unbounded growth.
- **OpenAI rate limits**: Exponential backoff in `generate_summaries` and `generate_audio` handles transient 429 errors gracefully. At high volume, batch API or a queue-based architecture would be more appropriate.
- **RSS feed contention**: At high throughput, RSS regeneration could be decoupled into a separate scheduled Lambda to avoid concurrent writes.

---

## Security Architecture

- **Least-privilege IAM**: Each Lambda has its own execution role granting only the specific S3 prefixes, DynamoDB table, and SSM paths it needs.
- **Secrets management**: API keys are stored in SSM Parameter Store as `SecureString` (KMS-encrypted). They are injected at deploy time via SAM parameters — no secrets in code or environment variables in plaintext.
- **S3 bucket**: All public access is blocked. CloudFront accesses audio via OAC with SigV4 signing.
- **DynamoDB encryption**: Server-side encryption enabled at rest.
- **SQS DLQs**: KMS-encrypted at rest.
- **CloudFront**: HTTPS-only with redirect; HTTP/2 and HTTP/3 enabled.
- **CloudWatch Logs**: Structured JSON output. Log groups have defined retention (14 days dev, 90 days prod).

---

## Cost Optimisation Strategies

- **Lambda arm64**: ~34% cheaper than x86_64.
- **S3 lifecycle policies**: Objects transition to Standard-IA after 30 days and are deleted after 90 days.
- **DynamoDB TTL**: Episodes expire automatically after 90 days, avoiding storage bloat.
- **CloudFront caching**: Reduces S3 GET requests (CloudFront GETs are ~$0.0075/10K vs S3 $0.0004/1K but caching means far fewer origin requests).
- **OpenAI TTS `tts-1` vs `tts-1-hd`**: `tts-1` is half the price and suitable for news audio.
- See `COST_ESTIMATION.md` for a full monthly cost breakdown.

---

## Monitoring & Observability

### Structured Logging
All Lambda functions emit JSON log lines to CloudWatch:
```json
{"time": "2024-01-15 06:00:01", "level": "INFO", "logger": "handler", "message": {"event": "articles_stored", "count": 47}}
```

### CloudWatch Alarms
| Alarm | Threshold | Action |
|---|---|---|
| IngestNews errors | ≥3 in 1 hour | SNS → Email |
| GenerateSummaries errors | ≥5 in 1 hour | SNS → Email |
| GenerateAudio errors | ≥5 in 1 hour | SNS → Email |

### Dashboard
A CloudWatch Dashboard (`NewsSummaries-{stage}`) shows:
- Lambda invocation counts (all 3 functions)
- Lambda error counts
- Lambda P95 duration

### DLQ Monitoring
Failed Lambda invocations land in SQS DLQs. Set a CloudWatch alarm on `ApproximateNumberOfMessagesVisible` for each DLQ to detect processing failures.
