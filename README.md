# NewsSummaries

**AI-powered news summaries delivered as a podcast — twice daily.**

NewsSummaries is a fully serverless AWS pipeline that automatically ingests breaking news from RSS feeds, generates concise AI summaries using OpenAI's `o3-mini` model, converts them to natural-sounding audio using OpenAI TTS, and publishes the results as an iTunes-compatible podcast feed.

All infrastructure is managed with **HashiCorp Terraform**.

---

## Features

- 📰 **Multi-source ingestion** — BBC, Reuters, CNN, The Guardian, and optional NewsAPI
- 🤖 **AI summaries** — 2–3 sentence structured summaries with category and importance tags via `o3-mini`
- 🎙️ **Natural audio** — High-quality TTS using OpenAI `tts-1` with the "nova" voice
- 🌍 **Global delivery** — Audio served via CloudFront CDN (HTTPS, HTTP/2 + HTTP/3)
- 📡 **Podcast RSS feed** — iTunes-compatible feed for any podcast app (Overcast, Pocket Casts, etc.)
- ⏰ **Twice daily** — Automatic runs at 06:00 and 18:00 UTC via EventBridge Scheduler
- 💰 **Low cost** — Under $5/month at light usage; scales to zero when idle

---

## Architecture

```
EventBridge Scheduler (6 AM & 6 PM UTC)
        │
        ▼
Lambda: IngestNews ──► S3 raw/{date}/{hash}.json
        │
        ▼ (S3 ObjectCreated event)
Lambda: GenerateSummaries ──► S3 summaries/ + DynamoDB
        │
        ▼ (DynamoDB Stream INSERT)
Lambda: GenerateAudio ──► S3 audio/{date}/{id}.mp3
        │                  S3 feed.xml
        ▼
  CloudFront CDN ──► Podcast apps / browsers
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full data flow and component descriptions.

---

## Technology Stack

| Layer | Technology |
|---|---|
| **Infrastructure as Code** | HashiCorp Terraform 1.7+ |
| Compute | AWS Lambda (Python 3.11, arm64/Graviton2) |
| Scheduler | Amazon EventBridge Scheduler |
| Object storage | Amazon S3 (with lifecycle policies) |
| Database | Amazon DynamoDB (on-demand, with Streams) |
| CDN | Amazon CloudFront (OAC, HTTPS-only) |
| Error handling | Amazon SQS Dead Letter Queues |
| Alerting | Amazon SNS → Email |
| Observability | Amazon CloudWatch (Logs, Alarms, Dashboard) |
| AI summarisation | OpenAI `o3-mini` |
| AI text-to-speech | OpenAI `tts-1` (nova voice) |
| News sources | RSS feeds + NewsAPI.org |

---

## Quick Start

### Prerequisites

- Python 3.11, AWS CLI v2, Terraform 1.7+

### 1. Bootstrap Terraform state backend (one-time)

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws s3api create-bucket --bucket "news-summaries-tf-state-${ACCOUNT_ID}" --region us-east-1
aws s3api put-bucket-versioning \
  --bucket "news-summaries-tf-state-${ACCOUNT_ID}" \
  --versioning-configuration Status=Enabled
aws dynamodb create-table \
  --table-name terraform-state-lock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST --region us-east-1
export TF_STATE_BUCKET="news-summaries-tf-state-${ACCOUNT_ID}"
```

### 2. Configure API keys

```bash
export TF_VAR_openai_api_key="sk-your-openai-key"
export TF_VAR_news_api_key="your-newsapi-key"  # or DISABLED
```

### 3. Deploy to dev

```bash
git clone https://github.com/SholasSandbox/NewsSummaries.git
cd NewsSummaries
make install    # Python dev dependencies
make build      # Build Lambda packages into dist/
make init-dev   # terraform init (S3 backend)
make deploy-dev # terraform apply
```

### 4. Trigger a run manually

```bash
make run-ingest-dev
```

### 5. Subscribe to the podcast

```bash
# Print the RSS feed URL
cd terraform && terraform output podcast_feed_url
```

Add this URL to any podcast app (Overcast, Pocket Casts, Apple Podcasts).

---

## Directory Structure

```
NewsSummaries/
├── terraform/                  # Terraform HCL — all AWS infrastructure
│   ├── providers.tf            # AWS provider + version constraints
│   ├── backend.tf              # S3 remote state backend
│   ├── variables.tf            # Input variables
│   ├── locals.tf               # Naming conventions
│   ├── outputs.tf              # Stack outputs
│   ├── iam.tf                  # IAM roles (least-privilege)
│   ├── s3.tf                   # S3 bucket + lifecycle + notifications
│   ├── dynamodb.tf             # DynamoDB table + GSI + Streams
│   ├── lambda.tf               # Lambda functions + packaging
│   ├── eventbridge.tf          # Twice-daily EventBridge schedules
│   ├── cloudfront.tf           # CloudFront CDN distribution
│   ├── sqs.tf                  # Dead Letter Queues
│   ├── cloudwatch.tf           # Log groups, alarms, dashboard, SNS
│   ├── terraform.tfvars        # Dev defaults (non-sensitive)
│   └── terraform.prod.tfvars   # Prod overrides
├── src/
│   ├── ingest_news/            # Lambda 1: RSS + NewsAPI ingestion
│   ├── generate_summaries/     # Lambda 2: OpenAI o3-mini summarisation
│   ├── generate_audio/         # Lambda 3: OpenAI TTS + RSS feed
│   └── shared/                 # Shared utilities (logger, retry, RSS)
├── tests/
│   ├── conftest.py             # Moto fixtures
│   └── unit/                   # Unit tests for all three Lambdas
├── docs/
│   ├── ARCHITECTURE.md         # System design + data flow
│   ├── DEPLOYMENT.md           # Step-by-step Terraform deployment guide
│   ├── COST_ESTIMATION.md      # Monthly cost breakdown
│   └── DEVELOPMENT.md          # Local dev setup + testing guide
├── Makefile                    # Developer shortcuts
└── .env.example                # Environment variable template
```

---

## Developer Commands

```bash
make install        # Install Python dev dependencies
make build          # Build Lambda packages into dist/
make init-dev       # terraform init for dev (set TF_STATE_BUCKET first)
make plan-dev       # terraform plan for dev (dry run)
make deploy-dev     # terraform apply for dev
make plan-prod      # terraform plan for prod
make deploy-prod    # terraform apply for prod (with confirmation)
make tf-fmt         # Auto-format Terraform files
make validate       # terraform validate
make test           # Run unit tests with coverage
make lint           # Run flake8, black, isort checks
make format         # Auto-format Python code
make logs-ingest    # Tail IngestNews CloudWatch logs
make logs-summaries # Tail GenerateSummaries CloudWatch logs
make logs-audio     # Tail GenerateAudio CloudWatch logs
make run-ingest-dev # Manually invoke IngestNews in dev
make outputs-dev    # Show terraform output for dev
make clean          # Remove build artifacts (dist/, .pytest_cache, etc.)
make help           # Show all available commands
```

---

## CI/CD

The GitHub Actions workflow (`.github/workflows/terraform.yml`) runs:

1. **Lint** — flake8, black, isort on every push and PR
2. **Test** — pytest with moto AWS mocking
3. **Terraform fmt + validate + plan** — runs on every PR; posts plan as a PR comment
4. **Deploy Dev** — `terraform apply` automatically on push to `main`
5. **Deploy Prod** — manually via `workflow_dispatch` with environment approval

AWS credentials use OIDC — no long-lived keys stored in GitHub Secrets.

---

## Documentation

| Document | Description |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, data flows, technology choices |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Step-by-step Terraform deployment and troubleshooting |
| [COST_ESTIMATION.md](docs/COST_ESTIMATION.md) | Detailed monthly cost breakdown |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Local dev setup, testing, and code style |

---

## Contributing

1. Fork the repository and create a feature branch
2. Follow the code style: `make lint` must pass
3. Write tests for new functionality: `make test` must pass
4. Format Terraform: `make tf-fmt`
5. Open a pull request — CI runs automatically

---

## License

MIT License.
