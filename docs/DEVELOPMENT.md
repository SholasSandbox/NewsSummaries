# Development Guide — NewsSummaries

## Prerequisites

- Python 3.11
- Terraform 1.7+ (`brew install terraform` or https://developer.hashicorp.com/terraform/install)
- AWS CLI v2
- make

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

---

## Project Structure

```
NewsSummaries/
├── terraform/                      # All infrastructure as Terraform HCL
│   ├── providers.tf                # AWS provider + required_providers
│   ├── backend.tf                  # S3 remote state configuration
│   ├── variables.tf                # Input variable definitions
│   ├── locals.tf                   # Computed local values
│   ├── outputs.tf                  # Stack outputs
│   ├── iam.tf                      # IAM roles and least-privilege policies
│   ├── s3.tf                       # S3 bucket, lifecycle, notifications
│   ├── dynamodb.tf                 # DynamoDB table, GSI, TTL, streams
│   ├── lambda.tf                   # Lambda functions + packaging
│   ├── eventbridge.tf              # EventBridge Scheduler (twice daily)
│   ├── cloudfront.tf               # CloudFront CDN distribution
│   ├── sqs.tf                      # Dead Letter Queues + alarms
│   ├── cloudwatch.tf               # Log groups, alarms, dashboard, SNS
│   ├── terraform.tfvars            # Dev defaults (non-sensitive)
│   └── terraform.prod.tfvars       # Prod overrides
├── Makefile                        # Developer shortcuts
├── .env.example                    # Environment variable template
├── src/
│   ├── ingest_news/
│   │   ├── handler.py              # Lambda 1 handler
│   │   └── requirements.txt
│   ├── generate_summaries/
│   │   ├── handler.py              # Lambda 2 handler
│   │   └── requirements.txt
│   ├── generate_audio/
│   │   ├── handler.py              # Lambda 3 handler
│   │   └── requirements.txt
│   ├── episodes_api/
│   │   ├── handler.py              # Lambda 4 handler (Episodes API)
│   │   └── requirements.txt
│   └── shared/
│       ├── __init__.py
│       └── utils.py                # Shared utilities (logger, retry, RSS)
├── dist/                           # Built Lambda packages (git-ignored)
├── tests/
│   ├── conftest.py                 # Pytest fixtures (moto mocks)
│   ├── requirements.txt
│   └── unit/
│       ├── test_ingest_news.py
│       ├── test_generate_summaries.py
│       ├── test_generate_audio.py
│       └── test_episodes_api.py
└── docs/
    ├── ARCHITECTURE.md
    ├── DEPLOYMENT.md
    ├── DEVELOPMENT.md              # This file
    ├── LAMBDA_INTERNALS.md         # Deep-dive on all four Lambda handlers
    └── COST_ESTIMATION.md
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

Tests use [moto](https://github.com/getmoto/moto) to mock AWS services (S3, DynamoDB)
in-process — no real AWS credentials needed.

---

## Local Lambda Testing (without AWS)

Because the functions are plain Python, you can invoke them locally by setting
the required environment variables and calling the handler directly:

```bash
# Export the same env vars the Lambda gets in AWS
export AWS_DEFAULT_REGION=us-east-1
export AWS_ACCESS_KEY_ID=testing
export AWS_SECRET_ACCESS_KEY=testing
export S3_BUCKET=local-news-summaries
export DYNAMODB_TABLE=local-episodes
export CLOUDFRONT_DOMAIN=d1234567890.cloudfront.net
export OPENAI_API_KEY=sk-fake
export NEWS_API_KEY=DISABLED
export STAGE=dev
export LOG_LEVEL=DEBUG

# Run the ingest handler (uses moto-style mocks if you wrap it, or hits real RSS)
python3 -c "
import src.ingest_news.handler as h
print(h.lambda_handler({}, type('ctx', (), {'function_name': 'local', 'aws_request_id': 'test'})()))
"
```

For full integration testing against real AWS, deploy to the dev environment with
`make deploy-dev`, then use `make run-ingest-dev`.

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

The `aws_credentials` fixture in `conftest.py` sets dummy environment variables so
`boto3` doesn't attempt real AWS auth.

---

## Mocking OpenAI

Use `pytest-mock` to mock OpenAI HTTP calls:

```python
from unittest.mock import MagicMock, patch
import json

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

## Terraform Workflow

```bash
# Format all Terraform files
make tf-fmt

# Validate syntax
make validate

# Plan changes (dry run)
make plan-dev

# Apply changes
make deploy-dev
```

To inspect the current state:
```bash
cd terraform
terraform state list              # All managed resources
terraform state show aws_s3_bucket.content  # Details of one resource
terraform output                  # Stack outputs
```

---

## Code Style and Linting

```bash
make lint       # Run flake8, black --check, isort --check
make format     # Auto-format with black and isort
make typecheck  # mypy type checking
```

### Style conventions

- Max line length: **120 characters**
- String quotes: **double quotes** (enforced by `black`)
- Type hints: used on all function signatures
- Docstrings: Google-style for modules, classes, and public functions
- Structured log messages: JSON strings as the `message` field

---

## Adding a New RSS Feed

Edit `rss_feeds` in `terraform/terraform.tfvars`:

```hcl
rss_feeds = "https://feeds.bbci.co.uk/news/rss.xml,...,https://new-feed.example.com/rss.xml"
```

Then `make deploy-dev` to update the Lambda environment variable.

---

## Environment Variables Reference

| Variable | Lambda | Description |
|---|---|---|
| `S3_BUCKET_NAME` | all | S3 bucket name |
| `DYNAMODB_TABLE_NAME` | all | DynamoDB table name |
| `CLOUDFRONT_DOMAIN` | all | CloudFront domain for audio URLs |
| `LOG_LEVEL` | all | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `STAGE` | all | `dev` or `prod` |
| `OPENAI_API_KEY` | summaries, audio | OpenAI API key |
| `NEWS_API_KEY` | ingest | NewsAPI.org key (`DISABLED` to skip) |
| `RSS_FEEDS` | ingest | Comma-separated RSS feed URLs |
| `GENERATE_SUMMARIES_FUNCTION` | ingest | Lambda function name/ARN for fan-out |
| `TTS_VOICE` | audio | OpenAI TTS voice (nova, alloy, echo…) |
| `PODCAST_TITLE` | audio | Podcast show title in RSS feed |
| `PODCAST_DESCRIPTION` | audio | Podcast show description |
| `PODCAST_AUTHOR` | audio | Author name in RSS feed |
| `PODCAST_EMAIL` | audio | Author email in RSS feed |
| `ADMIN_API_KEY` | episodes_api | Bearer token for the Episodes API (empty = auth disabled) |
| `PRESIGNED_URL_EXPIRY_SECONDS` | episodes_api | Lifetime of presigned S3 URLs in seconds (default 3600) |

---

## Lambda Handler Internals

For a detailed educational walkthrough of every handler — cold starts, event
shapes, retry patterns, DynamoDB Streams deserialisation, and more — see
[docs/LAMBDA_INTERNALS.md](LAMBDA_INTERNALS.md).
