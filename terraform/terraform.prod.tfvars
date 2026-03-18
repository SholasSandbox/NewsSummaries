# ─────────────────────────────────────────────────────────────────────────────
# terraform.prod.tfvars — Production environment overrides
#
# Apply with:
#   terraform apply -var-file="terraform.prod.tfvars"
# ─────────────────────────────────────────────────────────────────────────────

stage      = "prod"
aws_region = "us-east-1"

rss_feeds = "https://feeds.bbci.co.uk/news/rss.xml,https://feeds.reuters.com/reuters/topNews,https://rss.cnn.com/rss/edition.rss,https://feeds.theguardian.com/theguardian/world/rss,https://feeds.npr.org/1001/rss.xml,https://feeds.washingtonpost.com/rss/world"

podcast_title       = "News Summaries"
podcast_description = "Daily AI-powered news summaries — delivered twice a day."
podcast_author      = "News Summaries Bot"
podcast_email       = "hello@example.com"
tts_voice           = "nova"

alert_email = "" # Set to your email to receive CloudWatch alarms

log_retention_days = 30

lambda_memory_ingest    = 256
lambda_memory_summaries = 512
lambda_memory_audio     = 1024
lambda_timeout          = 300

cloudfront_price_class = "PriceClass_100"
