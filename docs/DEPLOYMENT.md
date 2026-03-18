# Deployment Guide — NewsSummaries

## Prerequisites

| Tool | Minimum version | Install |
|---|---|---|
| Python | 3.11 | https://python.org |
| AWS CLI | 2.x | https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html |
| AWS SAM CLI | 1.110+ | https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html |
| Docker | 24+ (for `sam build`) | https://docs.docker.com/get-docker/ |
| make | any | Pre-installed on macOS/Linux |

Verify installations:
```bash
aws --version          # aws-cli/2.x.x
sam --version          # SAM CLI, version 1.x.x
python3.11 --version   # Python 3.11.x
docker --version       # Docker version 24.x.x
```

---

## AWS Account Setup

### 1. Configure AWS credentials

```bash
aws configure --profile news-summaries
# Enter: Access Key ID, Secret Access Key, Region (e.g. us-east-1), Output (json)
```

Or use AWS SSO / Identity Centre:
```bash
aws sso configure --profile news-summaries
```

### 2. Create SSM Parameters

Store your API keys before the first deploy:

```bash
# OpenAI API key (SecureString = KMS-encrypted)
aws ssm put-parameter \
  --name "/news-summaries/openai-api-key" \
  --value "sk-your-openai-key-here" \
  --type SecureString \
  --description "OpenAI API key for NewsSummaries" \
  --profile news-summaries

# NewsAPI.org key (optional – set "DISABLED" to skip NewsAPI)
aws ssm put-parameter \
  --name "/news-summaries/news-api-key" \
  --value "your-newsapi-key-here" \
  --type SecureString \
  --description "NewsAPI.org key for NewsSummaries" \
  --profile news-summaries
```

---

## First-time Setup

```bash
# Clone and enter the repository
git clone https://github.com/your-org/NewsSummaries.git
cd NewsSummaries

# Create the SAM deployment bucket (one-time, per region)
aws s3 mb s3://news-summaries-sam-artifacts-$(aws sts get-caller-identity \
  --query Account --output text) \
  --region us-east-1 \
  --profile news-summaries

# Install Python development dependencies
make install
```

---

## Environment Configuration

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
# Edit .env with your actual values (never commit this file)
```

The `samconfig.toml` file controls SAM deployment settings. Review and update:

```toml
# samconfig.toml
[dev.deploy.parameters]
stack_name = "news-summaries-dev"
s3_bucket  = "news-summaries-sam-artifacts-YOUR_ACCOUNT_ID"
region     = "us-east-1"
```

---

## Build

```bash
# Build all Lambda functions (uses Docker for consistent Python 3.11 / arm64 env)
make build
# Equivalent to: sam build --use-container
```

The build artifacts are placed in `.aws-sam/build/`.

---

## Deploy

### Development environment

```bash
make deploy-dev
# Equivalent to: sam deploy --config-env dev --profile news-summaries
```

First-time deploy will prompt for confirmation of IAM changes. Answer **y**.

### Production environment

```bash
make deploy-prod
# Equivalent to: sam deploy --config-env prod --profile news-summaries
```

Production deploys require an explicit `--config-env prod` and are protected
by a manual GitHub Actions approval step in the CI/CD workflow.

---

## Post-deployment Verification

### 1. Check stack outputs

```bash
aws cloudformation describe-stacks \
  --stack-name news-summaries-dev \
  --query 'Stacks[0].Outputs' \
  --profile news-summaries
```

Note the `CloudFrontDomain` and `RssFeedUrl` outputs.

### 2. Test the IngestNews function

```bash
aws lambda invoke \
  --function-name news-summaries-ingest-dev \
  --payload '{}' \
  --log-type Tail \
  --query 'LogResult' \
  --output text \
  --profile news-summaries \
  /tmp/ingest-response.json | base64 -d

cat /tmp/ingest-response.json
```

Expected response:
```json
{"statusCode": 200, "body": "{\"run_date\": \"2024-01-15\", \"articles_fetched\": 120, \"articles_stored\": 47}"}
```

### 3. Monitor pipeline progress

```bash
# Tail all Lambda logs in real time
make logs-ingest     # IngestNews logs
make logs-summaries  # GenerateSummaries logs
make logs-audio      # GenerateAudio logs
```

### 4. Verify RSS feed

```bash
# Get the RSS feed URL from stack outputs, then:
CLOUDFRONT_DOMAIN=$(aws cloudformation describe-stacks \
  --stack-name news-summaries-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontDomain`].OutputValue' \
  --output text)

curl -s "https://${CLOUDFRONT_DOMAIN}/rss/feed.xml" | head -50
```

### 5. Check DynamoDB records

```bash
aws dynamodb scan \
  --table-name news-summaries-episodes-dev \
  --limit 5 \
  --profile news-summaries
```

---

## Updating SSM Parameters

To rotate API keys without redeploying:

```bash
aws ssm put-parameter \
  --name "/news-summaries/openai-api-key" \
  --value "sk-new-key" \
  --type SecureString \
  --overwrite \
  --profile news-summaries
```

Lambda picks up the new value on the next cold start.

---

## Tearing Down

```bash
# Delete dev stack (also deletes all S3 objects in the bucket)
aws cloudformation delete-stack \
  --stack-name news-summaries-dev \
  --profile news-summaries

# Empty and delete the S3 bucket first if it has versioned objects
aws s3 rm s3://news-summaries-dev --recursive
aws s3api delete-bucket --bucket news-summaries-dev
```

---

## Troubleshooting

### `Error: No samconfig.toml found`
Run `make build` first, or ensure you are in the repository root directory.

### `AccessDeniedException` during deploy
Ensure your IAM user/role has `CloudFormation:*`, `Lambda:*`, `S3:*`, `DynamoDB:*`, and `IAM:PassRole` permissions.

### Lambda timeout on first run
The first RSS fetch may take longer than usual due to slow upstream feeds. Increase `Timeout` in `template.yaml` temporarily and redeploy.

### OpenAI `RateLimitError`
The code retries with exponential backoff up to 3 times. If errors persist, check your OpenAI usage tier and request a quota increase.

### DynamoDB stream not triggering `GenerateAudio`
Check that the Lambda has DynamoDB stream permissions and that the stream is `ENABLED` on the table:
```bash
aws dynamodb describe-table \
  --table-name news-summaries-episodes-dev \
  --query 'Table.StreamSpecification'
```

### CloudFront returning 403 on audio files
Verify that the S3 bucket policy `AllowCloudFrontOAC` statement is present and the `AWS:SourceArn` condition matches the actual CloudFront distribution ARN.

### RSS feed not updating
Check CloudWatch logs for the `GenerateAudio` function. The RSS feed is regenerated after every batch of DynamoDB stream records. If no audio has been generated yet, the feed will not be created.
