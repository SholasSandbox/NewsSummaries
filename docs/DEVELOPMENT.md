# Development Guide — NewsSummaries

## Prerequisites

- Python 3.11
- Docker (for `sam local` and `sam build --use-container`)
- AWS CLI v2
- AWS SAM CLI 1.110+

---

## Virtual Environment Setup

```bash
# Create a virtual environment (do this once)
python3.11 -m venv .venv

# Activate it
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate.bat       # Windows CMD
# .venv\Scripts\Activate.ps1       # Windows PowerShell

# Install all dev dependencies
make install
```

`make install` runs:
```bash
pip install -e ".[dev]"
pip install -r src/ingest_news/requirements.txt
pip install -r src/generate_summaries/requirements.txt
pip install -r src/generate_audio/requirements.txt
pip install -r tests/requirements.txt
```

---

## Project Structure

```
NewsSummaries/
├── template.yaml               # SAM / CloudFormation template
├── samconfig.toml              # SAM CLI configuration (dev + prod envs)
├── Makefile                    # Developer shortcuts
├── .env.example                # Template for local environment variables
├── src/
│   ├── ingest_news/
│   │   ├── handler.py          # Lambda handler
│   │   └── requirements.txt
│   ├── generate_summaries/
│   │   ├── handler.py
│   │   └── requirements.txt
│   ├── generate_audio/
│   │   ├── handler.py
│   │   └── requirements.txt
│   └── shared/
│       ├── __init__.py
│       └── utils.py            # Shared utilities (logger, secrets, retry, RSS)
├── tests/
│   ├── conftest.py             # Pytest fixtures (moto mocks)
│   ├── requirements.txt
│   └── unit/
│       ├── test_ingest_news.py
│       ├── test_generate_summaries.py
│       └── test_generate_audio.py
└── docs/
    ├── ARCHITECTURE.md
    ├── DEPLOYMENT.md
    ├── COST_ESTIMATION.md
    └── DEVELOPMENT.md          # This file
```

---

## Running Tests

```bash
# Run all unit tests with coverage
make test

# Run a specific test file
pytest tests/unit/test_ingest_news.py -v

# Run tests matching a keyword
pytest -k "test_deduplicate" -v

# Run with coverage report
pytest --cov=src --cov-report=term-missing
```

Tests use [moto](https://github.com/getmoto/moto) to mock AWS services (S3, DynamoDB, SSM) in-process — no real AWS credentials needed for unit tests.

---

## Local Lambda Invocation with SAM

Build first (required after any code change):

```bash
make build
# or: sam build --use-container
```

### Invoke a function locally

```bash
# IngestNews (uses a mock event)
sam local invoke IngestNewsFunction \
  --event tests/events/ingest_news_event.json \
  --env-vars tests/events/env.json

# GenerateSummaries with an S3 event
sam local invoke GenerateSummariesFunction \
  --event tests/events/s3_event.json \
  --env-vars tests/events/env.json

# GenerateAudio with a DynamoDB stream event
sam local invoke GenerateAudioFunction \
  --event tests/events/dynamodb_stream_event.json \
  --env-vars tests/events/env.json
```

Create `tests/events/env.json` with your local environment variables:
```json
{
  "IngestNewsFunction": {
    "S3_BUCKET_NAME": "local-news-summaries",
    "DYNAMODB_TABLE_NAME": "local-episodes",
    "LOG_LEVEL": "DEBUG",
    "OPENAI_API_KEY": "sk-fake-key-for-local",
    "NEWS_API_KEY": "DISABLED",
    "GENERATE_SUMMARIES_FUNCTION": "news-summaries-summaries-dev"
  }
}
```

### Start a local API Gateway (if you add HTTP endpoints)

```bash
make local
# or: sam local start-api --port 3000
```

---

## Mocking AWS Services with moto

The test suite uses `moto` for in-process AWS mocking. No real AWS calls are made.

Example pattern used in tests:
```python
import boto3
import pytest
from moto import mock_aws

@pytest.fixture
def s3_bucket(aws_credentials):
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="test-bucket")
        yield s3
```

The `aws_credentials` fixture in `conftest.py` sets dummy environment variables so `boto3` doesn't attempt real AWS auth.

---

## Mocking OpenAI

Use `pytest-mock` or `responses` to mock OpenAI HTTP calls:

```python
from unittest.mock import MagicMock, patch

def test_generate_summary(mock_s3):
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps({
        "summary": "Test summary.",
        "category": "technology",
        "importance": "high",
        "keywords": ["AI", "news"]
    })
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    with patch("generate_summaries.handler.openai_client") as mock_client:
        mock_client.chat.completions.create.return_value = mock_response
        result = lambda_handler({"s3_key": "raw/2024-01-15/abc123.json", "bucket": "test-bucket"}, {})
    assert result["statusCode"] == 200
```

---

## Code Style and Linting

```bash
# Run all linters
make lint

# Format code with black
black src/ tests/

# Check imports with isort
isort src/ tests/

# Type checking with mypy
mypy src/ --ignore-missing-imports

# Lint with flake8
flake8 src/ tests/ --max-line-length 120
```

### Style conventions

- Max line length: **120 characters**
- String quotes: **double quotes** (enforced by `black`)
- Type hints: used on all function signatures
- Docstrings: Google-style for modules, classes, and public functions
- Structured log messages: always emit JSON strings as the `message` field

### Pre-commit hooks (optional)

```bash
pip install pre-commit
pre-commit install
# Now lint/format runs automatically on git commit
```

---

## Adding a New RSS Feed

Edit `RSS_FEEDS` in `src/ingest_news/handler.py`:

```python
RSS_FEEDS = [
    ...
    {"name": "My New Feed", "url": "https://example.com/rss.xml", "category": "technology"},
]
```

Valid categories: `general`, `world`, `business`, `technology`, `science`, `health`, `sports`, `entertainment`.

---

## Environment Variables Reference

| Variable | Lambda | Description |
|---|---|---|
| `S3_BUCKET_NAME` | all | S3 bucket name |
| `DYNAMODB_TABLE_NAME` | all | DynamoDB table name |
| `LOG_LEVEL` | all | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `OPENAI_API_KEY` | summaries, audio | OpenAI API key |
| `NEWS_API_KEY` | ingest | NewsAPI.org key (`DISABLED` to skip) |
| `GENERATE_SUMMARIES_FUNCTION` | ingest | ARN/name of GenerateSummaries Lambda |
| `CLOUDFRONT_DOMAIN` | audio | CloudFront domain for audio URLs |
| `PODCAST_TITLE` | audio | Podcast show title in RSS feed |
| `PODCAST_DESCRIPTION` | audio | Podcast show description |
| `PODCAST_AUTHOR` | audio | Author name in RSS feed |
| `PODCAST_EMAIL` | audio | Author email in RSS feed |
