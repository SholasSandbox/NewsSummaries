# ─────────────────────────────────────────────────────────────────────────────
# terraform.tfvars — Development environment defaults
#
# Sensitive values (openai_api_key, news_api_key) must be supplied via:
#   export TF_VAR_openai_api_key="sk-..."
#   export TF_VAR_news_api_key="..."
# or passed with -var flags. Do NOT commit secrets to this file.
# ─────────────────────────────────────────────────────────────────────────────

stage      = "dev"
aws_region = "us-east-1"

rss_feeds = "https://feeds.bbci.co.uk/news/rss.xml,https://feeds.reuters.com/reuters/topNews,https://rss.cnn.com/rss/edition.rss,https://feeds.theguardian.com/theguardian/world/rss"

podcast_title       = "News Summaries (Dev)"
podcast_description = "Daily AI-powered news summaries — development environment"
podcast_author      = "News Summaries Bot"
podcast_email       = "hello@example.com"
tts_voice           = "nova"

alert_email = "" # Set to your email to receive CloudWatch alarms

log_retention_days = 14

lambda_memory_ingest    = 256
lambda_memory_summaries = 512
lambda_memory_audio     = 1024
lambda_timeout          = 300

cloudfront_price_class = "PriceClass_100"
