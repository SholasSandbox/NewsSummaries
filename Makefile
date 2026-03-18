.PHONY: install build deploy-dev deploy-prod test lint local logs-ingest logs-summaries logs-audio clean

STAGE_DEV  := dev
STAGE_PROD := prod
AWS_PROFILE ?= default
STACK_DEV  := news-summaries-dev
STACK_PROD := news-summaries-prod
REGION     := us-east-1

# ─────────────────────────────────────────────
# Dependencies
# ─────────────────────────────────────────────

install: ## Install all Python dependencies for local development
	pip install --upgrade pip
	pip install \
		feedparser==6.0.11 \
		requests==2.31.0 \
		openai==1.12.0 \
		boto3==1.34.0 \
		black \
		isort \
		flake8 \
		mypy \
		pytest \
		pytest-cov \
		pytest-mock
	pip install -r tests/requirements.txt

# ─────────────────────────────────────────────
# Build
# ─────────────────────────────────────────────

build: ## Build Lambda packages using SAM (Docker required)
	sam build --use-container

build-no-container: ## Build Lambda packages without Docker (requires Python 3.11 locally)
	sam build

# ─────────────────────────────────────────────
# Deploy
# ─────────────────────────────────────────────

deploy-dev: build ## Build and deploy to the dev environment
	sam deploy \
		--config-env $(STAGE_DEV) \
		--profile $(AWS_PROFILE) \
		--no-fail-on-empty-changeset

deploy-prod: build ## Build and deploy to the prod environment (requires confirmation)
	sam deploy \
		--config-env $(STAGE_PROD) \
		--profile $(AWS_PROFILE) \
		--no-fail-on-empty-changeset

# ─────────────────────────────────────────────
# Testing
# ─────────────────────────────────────────────

test: ## Run unit tests with coverage report
	pytest tests/unit/ \
		--cov=src \
		--cov-report=term-missing \
		--cov-report=xml:coverage.xml \
		-v

test-fast: ## Run unit tests without coverage (faster)
	pytest tests/unit/ -v

# ─────────────────────────────────────────────
# Linting & Formatting
# ─────────────────────────────────────────────

lint: ## Run all linters (flake8, black --check, isort --check)
	flake8 src/ tests/ --max-line-length 120 --extend-ignore=E203,W503
	black --check src/ tests/
	isort --check-only src/ tests/

format: ## Auto-format code with black and isort
	black src/ tests/
	isort src/ tests/

typecheck: ## Run mypy type checking
	mypy src/ --ignore-missing-imports --no-strict-optional

# ─────────────────────────────────────────────
# Local development
# ─────────────────────────────────────────────

local: ## Start SAM local API Gateway on port 3000
	sam local start-api --port 3000

invoke-ingest: ## Locally invoke the IngestNews function
	sam local invoke IngestNewsFunction \
		--event tests/events/ingest_news_event.json \
		--env-vars tests/events/env.json

invoke-summaries: ## Locally invoke the GenerateSummaries function
	sam local invoke GenerateSummariesFunction \
		--event tests/events/s3_event.json \
		--env-vars tests/events/env.json

invoke-audio: ## Locally invoke the GenerateAudio function
	sam local invoke GenerateAudioFunction \
		--event tests/events/dynamodb_stream_event.json \
		--env-vars tests/events/env.json

# ─────────────────────────────────────────────
# CloudWatch Logs
# ─────────────────────────────────────────────

logs-ingest: ## Tail CloudWatch logs for IngestNews (dev)
	sam logs \
		--name IngestNewsFunction \
		--stack-name $(STACK_DEV) \
		--tail \
		--profile $(AWS_PROFILE)

logs-summaries: ## Tail CloudWatch logs for GenerateSummaries (dev)
	sam logs \
		--name GenerateSummariesFunction \
		--stack-name $(STACK_DEV) \
		--tail \
		--profile $(AWS_PROFILE)

logs-audio: ## Tail CloudWatch logs for GenerateAudio (dev)
	sam logs \
		--name GenerateAudioFunction \
		--stack-name $(STACK_DEV) \
		--tail \
		--profile $(AWS_PROFILE)

# ─────────────────────────────────────────────
# Manual triggers
# ─────────────────────────────────────────────

run-ingest-dev: ## Manually trigger the IngestNews Lambda in dev
	aws lambda invoke \
		--function-name news-summaries-ingest-$(STAGE_DEV) \
		--payload '{}' \
		--log-type Tail \
		--query 'LogResult' \
		--output text \
		--profile $(AWS_PROFILE) \
		/tmp/ingest-response.json | base64 -d
	@echo ""
	@cat /tmp/ingest-response.json

# ─────────────────────────────────────────────
# SSM setup helpers
# ─────────────────────────────────────────────

setup-ssm: ## Create required SSM parameters (prompts for values)
	@read -p "Enter OpenAI API Key: " OPENAI_KEY; \
	aws ssm put-parameter \
		--name "/news-summaries/openai-api-key" \
		--value "$$OPENAI_KEY" \
		--type SecureString \
		--overwrite \
		--profile $(AWS_PROFILE)
	@read -p "Enter NewsAPI Key (or 'DISABLED'): " NEWS_KEY; \
	aws ssm put-parameter \
		--name "/news-summaries/news-api-key" \
		--value "$$NEWS_KEY" \
		--type SecureString \
		--overwrite \
		--profile $(AWS_PROFILE)

# ─────────────────────────────────────────────
# Clean
# ─────────────────────────────────────────────

clean: ## Remove SAM build artifacts and Python cache files
	rm -rf .aws-sam/
	rm -rf coverage.xml
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

# ─────────────────────────────────────────────
# Help
# ─────────────────────────────────────────────

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
