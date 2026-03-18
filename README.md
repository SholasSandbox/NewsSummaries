# NewsSummaries

**AI-powered news summaries delivered as a podcast — twice daily.**

NewsSummaries is a fully serverless AWS pipeline that automatically ingests breaking news from RSS feeds, generates concise AI summaries using OpenAI's `o3-mini` model, converts them to natural-sounding audio using OpenAI TTS, and publishes the results as an iTunes-compatible podcast feed.

---

## Features

- 📰 **Multi-source ingestion** — BBC, Reuters, AP, NPR, The Guardian, Ars Technica, and optional NewsAPI
- 🤖 **AI summaries** — 2–3 sentence structured summaries with category and importance tags via `o3-mini`
- 🎙️ **Natural audio** — High-quality TTS using OpenAI `tts-1` with the "nova" voice
- 🌍 **Global delivery** — Audio served via CloudFront CDN (HTTPS, HTTP/2+HTTP/3)
- 📡 **Podcast RSS feed** — iTunes-compatible feed for any podcast app (Overcast, Pocket Casts, etc.)
- ⏰ **Twice daily** — Automatic runs at 06:00 and 18:00 UTC via EventBridge Scheduler
- 💰 **Low cost** — ~$22/month at full throughput; under $3/month with high-importance filtering

---

## Architecture

```
EventBridge Scheduler (6 AM & 6 PM UTC)
        │
        ▼
Lambda: IngestNews ──► S3 raw/{date}/{hash}.json
        │
        ▼ (S3 event / async invoke)
Lambda: GenerateSummaries ──► S3 summaries/ + DynamoDB
        │
        ▼ (DynamoDB Stream INSERT)
Lambda: GenerateAudio ──► S3 audio/{date}/{id}.mp3
        │                  S3 rss/feed.xml
        ▼
  CloudFront CDN ──► Podcast apps / browsers
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full data flow and component descriptions.

---

## Technology Stack

| Layer | Technology |
|---|---|
| Infrastructure | AWS SAM (CloudFormation) |
| Compute | AWS Lambda (Python 3.11, arm64/Graviton2) |
| Scheduler | Amazon EventBridge Scheduler |
| Object storage | Amazon S3 (with lifecycle policies) |
| Database | Amazon DynamoDB (on-demand, with Streams) |
| CDN | Amazon CloudFront (OAC, HTTPS-only) |
| Secrets | AWS SSM Parameter Store (SecureString) |
| Error handling | Amazon SQS Dead Letter Queues |
| Alerting | Amazon SNS → Email |
| AI summarisation | OpenAI `o3-mini` |
| AI text-to-speech | OpenAI `tts-1` (nova voice) |
| News sources | RSS feeds + NewsAPI.org |

---

## Quick Start

### Prerequisites

- Python 3.11, AWS CLI v2, AWS SAM CLI, Docker

### 1. Store API keys in SSM

```bash
aws ssm put-parameter \
  --name "/news-summaries/openai-api-key" \
  --value "sk-your-key" \
  --type SecureString

aws ssm put-parameter \
  --name "/news-summaries/news-api-key" \
  --value "your-newsapi-key" \
  --type SecureString
```

### 2. Deploy to dev

```bash
git clone https://github.com/your-org/NewsSummaries.git
cd NewsSummaries
make deploy-dev
```

### 3. Trigger a run manually

```bash
make run-ingest-dev
```

### 4. Subscribe to the podcast

```bash
# Get your RSS feed URL
aws cloudformation describe-stacks \
  --stack-name news-summaries-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`RssFeedUrl`].OutputValue' \
  --output text
```

Add this URL to any podcast app.

---

## Directory Structure

```
NewsSummaries/
├── template.yaml                   # AWS SAM template (all infrastructure)
├── samconfig.toml                  # SAM CLI config (dev + prod envs)
├── Makefile                        # Developer shortcuts
├── .env.example                    # Environment variable template
├── src/
│   ├── ingest_news/
│   │   ├── handler.py              # Fetches RSS + NewsAPI, stores raw articles
│   │   └── requirements.txt
│   ├── generate_summaries/
│   │   ├── handler.py              # OpenAI o3-mini summarisation
│   │   └── requirements.txt
│   ├── generate_audio/
│   │   ├── handler.py              # OpenAI TTS + RSS feed generation
│   │   └── requirements.txt
│   └── shared/
│       ├── __init__.py
│       └── utils.py                # Logger, secrets, retry, RSS utilities
├── tests/
│   ├── conftest.py                 # Moto fixtures
│   ├── requirements.txt
│   └── unit/
│       ├── test_ingest_news.py
│       ├── test_generate_summaries.py
│       └── test_generate_audio.py
├── docs/
│   ├── ARCHITECTURE.md             # System design + data flow
│   ├── DEPLOYMENT.md               # Step-by-step deployment guide
│   ├── COST_ESTIMATION.md          # Monthly cost breakdown
│   └── DEVELOPMENT.md              # Local dev setup + testing guide
└── .github/
    └── workflows/
        ├── terraform.yml           # Existing Terraform workflow (unchanged)
        └── deploy.yml              # SAM build, test, and deploy workflow
```

---

## Developer Commands

```bash
make install        # Install Python dev dependencies
make build          # SAM build (Docker required)
make deploy-dev     # Deploy to dev environment
make deploy-prod    # Deploy to prod environment
make test           # Run unit tests with coverage
make lint           # Run flake8, black, isort checks
make format         # Auto-format code
make logs-ingest    # Tail IngestNews CloudWatch logs
make logs-summaries # Tail GenerateSummaries CloudWatch logs
make logs-audio     # Tail GenerateAudio CloudWatch logs
make clean          # Remove build artifacts
make help           # Show all available commands
```

---

## Documentation

| Document | Description |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, data flows, technology choices |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Step-by-step deployment and troubleshooting |
| [COST_ESTIMATION.md](docs/COST_ESTIMATION.md) | Detailed monthly cost breakdown |
| [DEVELOPMENT.md](docs/DEVELOPMENT.md) | Local dev setup, testing, and code style |

---

## CI/CD

The GitHub Actions workflow (`.github/workflows/deploy.yml`) runs:
1. **Lint** — flake8, black, isort on every push and PR
2. **Test** — pytest with moto AWS mocking
3. **Build** — `sam build --use-container`
4. **Deploy Dev** — automatically on push to `main`
5. **Deploy Prod** — manually via `workflow_dispatch`

AWS credentials use OIDC (no long-lived keys stored in GitHub Secrets).

---

## Contributing

1. Fork the repository and create a feature branch
2. Follow the code style: `make lint` must pass
3. Write tests for new functionality: `make test` must pass
4. Open a pull request — CI runs automatically

---

## License

MIT License. See [LICENSE](LICENSE) for details.
