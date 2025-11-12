# AWS Serverless Twice‑Daily News Summarizer

> Goal: Summarise breaking news and trends twice daily (AM/PM), focusing on analysis rather than headlines. Fully serverless, secure, and cost‑efficient; publish web + podcast‑style audio and keep an archive + metadata.

---

## 1) Simple High‑Level Architecture

```
                         ┌────────────────────────────────────────────────┐
                         │                 News Sources                   │
                         │  • Paid APIs (e.g., NewsAPI)  • RSS feeds     │
                         │  • Social/official feeds (optional)           │
                         └────────────────────────────────────────────────┘
                                              │
                                              ▼
┌─────────────────────┐      ┌───────────────────────────────────────────┐
│ EventBridge        │      │  Ingestion (Lambda)                       │
│ Scheduler (AM/PM)  │─────▶│  • Pull APIs/RSS                          │
│ (twice daily)      │      │  • Normalize + dedupe                     │
└─────────────────────┘      └───────────────────────────────────────────┘
                                              │
                                              ▼
                                     ┌──────────────────────┐
                                     │ Step Functions (SFN) │  ← Orchestration
                                     └──────────────────────┘
                                              │
             ┌──────────────────────────────┬─┴──────────────────────────────┐
             ▼                              ▼                               ▼
  ┌─────────────────────┐       ┌────────────────────────────┐     ┌─────────────────────┐
  │  Amazon Bedrock     │       │  Amazon Comprehend (opt.) │     │  Amazon Polly       │
  │  (LLM summarise &   │       │  NER, sentiment, topics   │     │  Text‑to‑Speech      │
  │  analysis prompts)  │       └────────────────────────────┘     └─────────────────────┘
             │                              │                               │
             └───────────────┬──────────────┴───────────────┬───────────────┘
                             ▼                              ▼
                     ┌──────────────────┐          ┌─────────────────────────┐
                     │ Amazon S3        │          │ DynamoDB (Metadata/     │
                     │ • Raw/Processed  │          │ Index/Run logs)         │
                     │ • Audio/Transcr. │          └─────────────────────────┘
                     └──────────────────┘                     │
                             │                                 ▼
                             ▼                        ┌───────────────────────┐
                 ┌──────────────────────┐             │ OpenSearch Serverless │
                 │ CloudFront (+ S3)    │             │ (full‑text search)    │
                 │ + AWS WAF            │             └───────────────────────┘
                 └──────────────────────┘                     │
                             │                                 │
                             ▼                                 ▼
                   ┌──────────────────┐               ┌──────────────────┐
                   │ Web App (S3/     │  (wireless)   │ Mobile/PWA/Feeds │  (wireless)
                   │ Amplify Hosting) │◀────────────▶│  (RSS/Podcast)   │◀──────────▶ Users
                   └──────────────────┘               └──────────────────┘
```

**Security & Ops (everywhere):** IAM least privilege, KMS encryption (S3/DynamoDB/Bedrock/Polly), Secrets Manager for API keys, CloudWatch Logs/Metrics/Alarms, X‑Ray tracing, SQS DLQs where appropriate.

---

## 2) Execution & Data Flows (Numbered)

```
(1) Event Trigger
    EventBridge Scheduler (06:30 & 18:00 Europe/London) triggers Step Functions state machine.

(2) Ingestion & Normalisation
    SFN → Lambda[Ingest] pulls from APIs/RSS using Secrets Manager creds, writes Raw JSON to S3 (s3://news/raw/yyyymmdd/)
    Dedup & merge; emit summary manifest to DynamoDB (RunId, sources, counts).

(3) Pre‑Analysis NLP (optional)
    Lambda[NLP] → Comprehend for key phrases, entities, sentiment → store annotations to S3 (s3://news/annot/...).

(4) Summarisation & Analysis
    Lambda[Summarise] → Bedrock (e.g., Claude/Sonar) with system prompts (tone, niche, bias checks).
    Outputs: AM/PM brief (markdown), section highlights, sources list, citations → S3 (processed/...).

(5) Voice Generation
    Lambda[Voice] → Polly (neural voice) creates MP3 + VTT transcript → S3 (audio/...).

(6) Packaging & Publish
    Lambda[Publish] builds web JSON (index), RSS/Podcast feed (XML), and signed CloudFront invalidation.
    Metadata/index upsert to DynamoDB; searchable docs to OpenSearch Serverless.

(7) Delivery (wireless to clients)
    CloudFront (WAF enabled) fronts S3 website/Amplify app + audio objects.
    Users consume via web, mobile PWA, or podcast apps.

(8) Observability & Fail‑safes
    CloudWatch Alarms → SNS (email/SMS). Step Functions catches errors and routes to SQS DLQ.
    Cost/usage tracked with Cur/Cost Explorer tags.


FLOW DIAGRAM

     ┌───────────────┐      (1)        ┌──────────────────┐
     │  EventBridge  │ ───────────────▶│ Step Functions   │
     │  Scheduler    │                 │  Orchestrator    │
     └───────────────┘                 └───────┬──────────┘
                                               │
                           (2)                 │
                 ┌──────────────────────┐      │
                 │ Lambda[Ingest]       │◀─────┘
                 │  • APIs/RSS          │
                 │  • Secrets Manager   │
                 └─────────┬────────────┘
                           │  S3 Put (raw)
                           ▼
                    ┌──────────────┐
                    │    S3 Raw    │
                    └──────┬───────┘
                           │
                 (3)       ▼
          ┌────────────────────────┐
          │ Lambda[NLP] →         │
          │ Comprehend (optional) │
          └─────────┬─────────────┘
                    │ S3 Put (annot)
                    ▼
                ┌──────────────┐
                │   S3 Annot   │
                └──────┬───────┘
                       │
             (4)       ▼
     ┌────────────────────────┐
     │ Lambda[Summarise] →    │
     │ Bedrock (LLM)          │
     └─────────┬──────────────┘
               │ S3 Put (md/json)
               ▼
           ┌──────────────┐
           │  S3 Proc     │
           └──────┬───────┘
                  │
        (5)       ▼
┌────────────────────────┐
│ Lambda[Voice] → Polly  │
└─────────┬──────────────┘
          │ S3 Put (mp3/vtt)
          ▼
      ┌──────────────┐
      │  S3 Audio    │
      └──────┬───────┘
             │
   (6)       ▼                        (6b)
┌────────────────────────┐       ┌──────────────────────────┐
│ Lambda[Publish]        │       │ DynamoDB (metadata)      │
│ • Build web JSON/RSS   │──────▶│  Run, item, feed index   │
│ • CF invalidation      │       └──────────────────────────┘
│ • Index to OpenSearch  │──────────────▶ OpenSearch Serverless
└─────────┬──────────────┘
          │ (6a)
          ▼
     ┌──────────────┐     (7)        ┌───────────────────────────┐
     │  CloudFront  │────────────────▶ Users (Web/Mobile/Podcast)│  (wireless)
     │ + WAF + S3   │                └───────────────────────────┘
     └──────────────┘

(8) Observability: CloudWatch Logs/Metrics/Alarms + X‑Ray; Failures → SQS DLQ; Notifications → SNS.
```

---

### Notes & Best‑Practice Touches
- **Security**: IAM least privilege, KMS‑CMK for S3/DynamoDB/OpenSearch; WAF (rate‑limit/bot control); private S3 origins via OAC; VPC endpoints for Bedrock/Comprehend if using private subnets.
- **Reliability**: Step Functions retries/backoff; SQS DLQs; idempotent writes keyed by RunId (date‑AM/PM).
- **Cost**: Serverless + on‑demand; cache via CloudFront; fetch only deltas; compact audio (mp3) and gzip/brotli text.
- **Extensibility**: Toggle niche via config (DynamoDB item) and prompt templates in S3; multi‑voice variants; add translation (Amazon Translate) if needed.
- **Wireless consumption**: Delivered over the Internet via CloudFront to mobile/desktop (PWA friendly).



---

## 3) MVP + Stretch Goals 1 & 2 — High‑Level Architecture (Mixed Audience)

**Scope added:**
- **Stretch 1:** Persistent metadata + run history in **Amazon DynamoDB** (query by date/topic/run).
- **Stretch 2:** **AWS Step Functions** orchestrates separate steps for ingestion → analysis → publish, improving reliability and observability.

```
                          ┌───────────────────────────────────────────┐
                          │              News Sources                 │
                          │ • Trusted APIs      • RSS feeds           │
                          └───────────────────────────────────────────┘
                                              │
                                              ▼ (on schedule)
┌───────────────────────┐      (twice daily)  ┌────────────────────────┐
│ Amazon EventBridge    │────────────────────▶│ AWS Step Functions     │
│ Scheduler (AM/PM)     │                    │ Orchestrator           │
└───────────────────────┘                    └───────────┬────────────┘
                                                        (stateful flow)
                              ┌───────────────────────────┼───────────────────────────┐
                              ▼                           ▼                           ▼
                  ┌──────────────────────┐   ┌────────────────────────┐   ┌──────────────────────┐
                  │ Lambda: Ingest       │   │ Lambda: Summarise/     │   │ Lambda: Publish      │
                  │ • Pull APIs/RSS      │   │ Analyse (Bedrock)      │   │ • Build HTML/JSON    │
                  │ • Normalise + dedupe │   │ • (Optional) Polly TTS │   │ • Update indexes     │
                  └──────────┬───────────┘   └───────────┬────────────┘   └──────────┬──────────┘
                             │ S3 (raw)                   │ S3 (processed/audio)     │
                             ▼                            ▼                         ▼
                      ┌───────────────┐             ┌───────────────┐        ┌─────────────────┐
                      │ Amazon S3     │◀────────────│ Amazon S3     │        │ DynamoDB         │
                      │ Raw artifacts │             │ Outputs       │        │ • Metadata       │
                      └──────┬────────┘             └──────┬────────┘        │ • Run history    │
                             │                               │               │ • Config/flags   │
                             │                               │               └────────┬────────┘
                             │                               │                        │
                             ▼                               ▼                        │ (lookups)
                     ┌──────────────────┐            ┌──────────────────┐             │
                     │ CloudFront (CDN) │──────────▶ │ Users (Web/PWA)  │◀───────────┘
                     │ + S3 Website     │   HTTPS    │  & Podcast Apps  │
                     └──────────────────┘            └──────────────────┘
```

**Why this is better than the basic MVP:**
- **Reliability & Observability:** Step Functions gives clear step‑level retries, metrics, and visual traces.
- **History & Querying:** DynamoDB stores run metadata (e.g., AM vs PM, topics, counts, source list, publish status) and enables quick dashboards later.
- **Still lean & serverless:** Minimal moving parts, pay‑for‑what‑you‑use.

**Security & Ops (high level):**
- IAM least privilege, KMS encryption (S3/DynamoDB), Secrets Manager for API keys, CloudWatch Alarms to SNS.
- CloudFront with HTTPS, S3 Origin Access (OAC), optional WAF rate‑limits.

