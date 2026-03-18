.PHONY: install build deploy-dev deploy-prod plan-dev plan-prod init-dev init-prod \
        test test-fast lint format typecheck \
        logs-ingest logs-summaries logs-audio \
        run-ingest-dev tf-fmt validate clean help

STAGE_DEV   := dev
STAGE_PROD  := prod
AWS_PROFILE ?= default
AWS_REGION  ?= us-east-1
TF_DIR      := terraform

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
# Build Lambda packages (pip install → dist/)
# Terraform picks these up automatically via archive_file
# ─────────────────────────────────────────────

build: ## Install Lambda dependencies into dist/ (required before terraform plan/apply)
	@echo "Building IngestNews..."
	@rm -rf dist/ingest_news && mkdir -p dist/ingest_news
	@cp src/ingest_news/handler.py dist/ingest_news/
	@cp -r src/shared dist/ingest_news/
	@pip install -r src/ingest_news/requirements.txt -t dist/ingest_news/ --quiet --upgrade
	@echo "Building GenerateSummaries..."
	@rm -rf dist/generate_summaries && mkdir -p dist/generate_summaries
	@cp src/generate_summaries/handler.py dist/generate_summaries/
	@cp -r src/shared dist/generate_summaries/
	@pip install -r src/generate_summaries/requirements.txt -t dist/generate_summaries/ --quiet --upgrade
	@echo "Building GenerateAudio..."
	@rm -rf dist/generate_audio && mkdir -p dist/generate_audio
	@cp src/generate_audio/handler.py dist/generate_audio/
	@cp -r src/shared dist/generate_audio/
	@pip install -r src/generate_audio/requirements.txt -t dist/generate_audio/ --quiet --upgrade
	@echo "Building EpisodesAPI..."
	@rm -rf dist/episodes_api && mkdir -p dist/episodes_api
	@cp src/episodes_api/handler.py dist/episodes_api/
	@pip install -r src/episodes_api/requirements.txt -t dist/episodes_api/ --quiet --upgrade
	@echo "Build complete. dist/ is ready."

# ─────────────────────────────────────────────
# Terraform — Initialise
# ─────────────────────────────────────────────

init-dev: ## Initialise Terraform for the dev environment (set TF_STATE_BUCKET env var)
	cd $(TF_DIR) && terraform init \
		-backend-config="bucket=$(TF_STATE_BUCKET)" \
		-backend-config="key=news-summaries/dev/terraform.tfstate" \
		-backend-config="region=$(AWS_REGION)" \
		-reconfigure

init-prod: ## Initialise Terraform for the prod environment
	cd $(TF_DIR) && terraform init \
		-backend-config="bucket=$(TF_STATE_BUCKET)" \
		-backend-config="key=news-summaries/prod/terraform.tfstate" \
		-backend-config="region=$(AWS_REGION)" \
		-reconfigure

# ─────────────────────────────────────────────
# Terraform — Plan & Apply
# ─────────────────────────────────────────────

plan-dev: build init-dev ## Plan infrastructure changes for dev
	cd $(TF_DIR) && terraform plan \
		-var-file="terraform.tfvars" \
		-var="openai_api_key=$(TF_VAR_openai_api_key)" \
		-var="news_api_key=$(TF_VAR_news_api_key)" \
		-input=false

deploy-dev: build init-dev ## Build and deploy to the dev environment
	cd $(TF_DIR) && terraform apply \
		-var-file="terraform.tfvars" \
		-var="openai_api_key=$(TF_VAR_openai_api_key)" \
		-var="news_api_key=$(TF_VAR_news_api_key)" \
		-input=false \
		-auto-approve

plan-prod: build init-prod ## Plan infrastructure changes for prod
	cd $(TF_DIR) && terraform plan \
		-var-file="terraform.prod.tfvars" \
		-var="openai_api_key=$(TF_VAR_openai_api_key)" \
		-var="news_api_key=$(TF_VAR_news_api_key)" \
		-input=false

deploy-prod: build init-prod ## Build and deploy to the prod environment (requires confirmation)
	cd $(TF_DIR) && terraform apply \
		-var-file="terraform.prod.tfvars" \
		-var="openai_api_key=$(TF_VAR_openai_api_key)" \
		-var="news_api_key=$(TF_VAR_news_api_key)" \
		-input=false

# ─────────────────────────────────────────────
# Terraform — Format & Validate
# ─────────────────────────────────────────────

tf-fmt: ## Auto-format all Terraform files
	cd $(TF_DIR) && terraform fmt -recursive

validate: ## Validate Terraform configuration syntax
	cd $(TF_DIR) && terraform validate

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

format: ## Auto-format Python code with black and isort
	black src/ tests/
	isort src/ tests/

typecheck: ## Run mypy type checking
	mypy src/ --ignore-missing-imports --no-strict-optional

# ─────────────────────────────────────────────
# CloudWatch Logs
# ─────────────────────────────────────────────

logs-ingest: ## Tail CloudWatch logs for IngestNews (dev)
	aws logs tail /aws/lambda/news-summaries-dev-ingest-news \
		--follow \
		--format short \
		--profile $(AWS_PROFILE)

logs-summaries: ## Tail CloudWatch logs for GenerateSummaries (dev)
	aws logs tail /aws/lambda/news-summaries-dev-generate-summaries \
		--follow \
		--format short \
		--profile $(AWS_PROFILE)

logs-audio: ## Tail CloudWatch logs for GenerateAudio (dev)
	aws logs tail /aws/lambda/news-summaries-dev-generate-audio \
		--follow \
		--format short \
		--profile $(AWS_PROFILE)

logs-api: ## Tail CloudWatch logs for EpisodesAPI Lambda 4 (dev)
	aws logs tail /aws/lambda/news-summaries-dev-episodes-api \
		--follow \
		--format short \
		--profile $(AWS_PROFILE)

# ─────────────────────────────────────────────
# Manual Lambda triggers
# ─────────────────────────────────────────────

run-ingest-dev: ## Manually trigger the IngestNews Lambda in dev
	aws lambda invoke \
		--function-name news-summaries-dev-ingest-news \
		--payload '{}' \
		--log-type Tail \
		--query 'LogResult' \
		--output text \
		--region $(AWS_REGION) \
		--profile $(AWS_PROFILE) \
		/tmp/ingest-response.json | base64 -d
	@echo ""
	@cat /tmp/ingest-response.json

# ─────────────────────────────────────────────
# Outputs (after deploy)
# ─────────────────────────────────────────────

outputs-dev: ## Show Terraform outputs for dev environment
	cd $(TF_DIR) && terraform output

# ─────────────────────────────────────────────
# Clean
# ─────────────────────────────────────────────

clean: ## Remove build artifacts and Python cache files
	rm -rf dist/
	rm -rf coverage.xml test-results.xml
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

# ─────────────────────────────────────────────
# Help
# ─────────────────────────────────────────────

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
