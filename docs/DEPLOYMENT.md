# Deployment Guide — NewsSummaries

## Prerequisites

| Tool | Minimum version | Install |
|---|---|---|
| Python | 3.11 | https://python.org |
| AWS CLI | 2.x | https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html |
| Terraform | 1.7+ | https://developer.hashicorp.com/terraform/install |
| make | any | Pre-installed on macOS/Linux |

Verify installations:
```bash
aws --version         # aws-cli/2.x.x
terraform version     # Terraform v1.7.x
python3.11 --version  # Python 3.11.x
```

---

## AWS Account Setup

### 1. Configure AWS credentials

```bash
aws configure --profile news-summaries
# Enter: Access Key ID, Secret Access Key, Region (us-east-1), Output (json)
```

Or use AWS SSO / Identity Centre:
```bash
aws sso configure --profile news-summaries
```

### 2. Bootstrap Terraform remote state

Terraform stores its state in S3 with DynamoDB locking.
Create these resources **once** before the first deploy:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --profile news-summaries)
REGION=us-east-1
STATE_BUCKET="news-summaries-tf-state-${ACCOUNT_ID}"

# Create the state bucket
aws s3api create-bucket \
  --bucket "${STATE_BUCKET}" \
  --region "${REGION}" \
  --profile news-summaries

# Enable versioning (required for state safety)
aws s3api put-bucket-versioning \
  --bucket "${STATE_BUCKET}" \
  --versioning-configuration Status=Enabled \
  --profile news-summaries

# Enable server-side encryption
aws s3api put-bucket-encryption \
  --bucket "${STATE_BUCKET}" \
  --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' \
  --profile news-summaries

# Create DynamoDB lock table
aws dynamodb create-table \
  --table-name terraform-state-lock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region "${REGION}" \
  --profile news-summaries

echo "State bucket: ${STATE_BUCKET}"
```

---

## First-time Setup

```bash
# Clone and enter the repository
git clone https://github.com/SholasSandbox/NewsSummaries.git
cd NewsSummaries

# Copy environment template
cp .env.example .env
# Edit .env with your actual API keys (never commit this file)

# Install Python dev dependencies
make install

# Set your state bucket in the environment (or export permanently in .bashrc / .zshrc)
export TF_STATE_BUCKET="news-summaries-tf-state-YOUR_ACCOUNT_ID"
export AWS_PROFILE=news-summaries
```

---

## Configure API Keys

Sensitive values are passed to Terraform as `TF_VAR_` environment variables
(never stored in `.tf` or `.tfvars` files):

```bash
# OpenAI API key — required
export TF_VAR_openai_api_key="sk-your-openai-key-here"

# NewsAPI.org key — set to DISABLED to skip
export TF_VAR_news_api_key="your-newsapi-key-or-DISABLED"
```

---

## Build Lambda packages

Before running `terraform plan` or `terraform apply`, build the Lambda deployment
packages (pip install dependencies into `dist/`):

```bash
make build
```

This installs Python dependencies for each function into `dist/ingest_news/`,
`dist/generate_summaries/`, and `dist/generate_audio/`. Terraform's `archive_file`
data source then zips these directories automatically.

---

## Initialise Terraform

```bash
# Dev environment
make init-dev
# Equivalent to:
# cd terraform && terraform init \
#   -backend-config="bucket=${TF_STATE_BUCKET}" \
#   -backend-config="key=news-summaries/dev/terraform.tfstate" \
#   -backend-config="region=us-east-1"
```

---

## Plan (dry run)

```bash
make plan-dev
```

Review the output carefully. Terraform shows exactly which resources will be
**created**, **updated**, or **destroyed**.

---

## Deploy

### Development environment

```bash
make deploy-dev
# Equivalent to: cd terraform && terraform apply -var-file="terraform.tfvars" ...
```

First-time deploy takes ~3 minutes (CloudFront distribution creation is slow).

### Production environment

```bash
make plan-prod    # Review the plan first
make deploy-prod  # Prompts for confirmation
```

---

## View Outputs

After a successful deploy:

```bash
make outputs-dev
# or: cd terraform && terraform output
```

Key outputs:
| Output | Description |
|---|---|
| `cloudfront_domain` | Base domain for the CDN |
| `podcast_feed_url` | Full URL of the RSS podcast feed |
| `content_bucket_name` | S3 bucket for all content |
| `episodes_table_name` | DynamoDB table name |

---

## Post-deployment Verification

### 1. Trigger a manual ingest run

```bash
make run-ingest-dev
```

Expected response:
```json
{"statusCode": 200, "body": "{\"run_date\": \"2024-01-15\", \"articles_fetched\": 120, \"articles_stored\": 47}"}
```

### 2. Monitor pipeline progress

```bash
make logs-ingest     # IngestNews CloudWatch logs
make logs-summaries  # GenerateSummaries logs
make logs-audio      # GenerateAudio logs
```

### 3. Verify RSS feed

```bash
FEED_URL=$(cd terraform && terraform output -raw podcast_feed_url)
curl -s "${FEED_URL}" | head -50
```

### 4. Check DynamoDB records

```bash
aws dynamodb scan \
  --table-name news-summaries-dev-episodes \
  --limit 5 \
  --profile news-summaries
```

---

## Updating Infrastructure

Edit the relevant `.tf` file in `terraform/`, then:

```bash
make plan-dev    # Review changes
make deploy-dev  # Apply changes
```

Terraform only modifies resources that have changed — safe to run repeatedly.

---

## Rotating API Keys

Update the environment variable and re-apply:

```bash
export TF_VAR_openai_api_key="sk-new-key-here"
make deploy-dev
```

Terraform updates the Lambda environment variables in-place. No downtime.

---

## CI/CD — GitHub Actions

The `.github/workflows/terraform.yml` workflow automatically:
- **On every PR**: runs lint, tests, `terraform fmt -check`, `terraform validate`, and `terraform plan` (posts the plan as a PR comment)
- **On push to main**: runs `terraform apply` to deploy to dev
- **Manual `workflow_dispatch`**: triggers a prod deploy after approval

Required GitHub Secrets:

| Secret | Description |
|---|---|
| `AWS_DEPLOY_ROLE_ARN_DEV` | IAM role ARN for OIDC dev deploys |
| `AWS_DEPLOY_ROLE_ARN_PROD` | IAM role ARN for OIDC prod deploys |
| `TF_STATE_BUCKET` | S3 bucket name for Terraform state |
| `TF_VAR_openai_api_key` | OpenAI API key |
| `TF_VAR_news_api_key` | NewsAPI key (`DISABLED` to skip) |
| `ALERT_EMAIL` | (optional) email for CloudWatch alarms |

### Setting up AWS OIDC for GitHub Actions

```bash
# Create an OIDC provider for GitHub in your AWS account (one-time)
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

Then create an IAM role with a trust policy allowing GitHub Actions to assume it.
See the [AWS documentation](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc.html) for details.

---

## Tearing Down

```bash
# Destroy dev infrastructure (prompts for confirmation)
cd terraform
terraform destroy -var-file="terraform.tfvars" \
  -var="openai_api_key=${TF_VAR_openai_api_key}" \
  -var="news_api_key=${TF_VAR_news_api_key}"

# The S3 bucket has force_destroy=true in dev so it will be emptied automatically.
# In prod (force_destroy=false), empty the bucket first:
# aws s3 rm s3://BUCKET_NAME --recursive
```

---

## Troubleshooting

### `Error: Backend initialization required`
Run `make init-dev` (or `init-prod`) before plan/apply.

### `Error: No valid credential sources found`
Ensure `AWS_PROFILE` is set or `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` are exported.

### `AccessDeniedException` during apply
Ensure your IAM user/role has permissions for Lambda, S3, DynamoDB, CloudFront, IAM, EventBridge, SQS, SNS, and CloudWatch.

### Lambda timeout on first run
The first RSS fetch may take longer than usual due to slow upstream feeds. Increase `lambda_timeout` in `terraform.tfvars` and re-apply.

### OpenAI `RateLimitError`
The code retries with exponential backoff up to 3 times. If errors persist, check your OpenAI usage tier and request a quota increase.

### CloudFront returning 403 on audio files
Verify that the S3 bucket policy `AllowCloudFrontReadAudio` statement exists and the `AWS:SourceArn` condition matches the actual CloudFront distribution ARN (`terraform output`).

### DynamoDB stream not triggering `GenerateAudio`
Check that `stream_enabled = true` on the DynamoDB table and the `aws_lambda_event_source_mapping` resource exists in the Terraform state:
```bash
cd terraform && terraform state list | grep event_source_mapping
```

### `Error: creating Lambda function: InvalidParameterValueException`
The Lambda deployment package must exist before apply. Run `make build` first.
