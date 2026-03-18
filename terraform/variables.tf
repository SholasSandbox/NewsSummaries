variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "stage" {
  description = "Deployment stage: dev or prod"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "prod"], var.stage)
    error_message = "Stage must be 'dev' or 'prod'."
  }
}

variable "openai_api_key" {
  description = "OpenAI API key stored in SSM. Set via TF_VAR_openai_api_key env var or tfvars."
  type        = string
  sensitive   = true
}

variable "news_api_key" {
  description = "NewsAPI.org API key (set to 'DISABLED' if not using NewsAPI)"
  type        = string
  sensitive   = true
  default     = "DISABLED"
}

variable "rss_feeds" {
  description = "Comma-separated list of RSS feed URLs to ingest"
  type        = string
  default     = "https://feeds.bbci.co.uk/news/rss.xml,https://feeds.reuters.com/reuters/topNews,https://rss.cnn.com/rss/edition.rss,https://feeds.theguardian.com/theguardian/world/rss"
}

variable "podcast_title" {
  description = "Title of the podcast RSS feed"
  type        = string
  default     = "News Summaries"
}

variable "podcast_description" {
  description = "Description of the podcast RSS feed"
  type        = string
  default     = "Daily AI-powered news summaries — delivered twice a day."
}

variable "podcast_author" {
  description = "Author name shown in podcast apps"
  type        = string
  default     = "News Summaries Bot"
}

variable "podcast_email" {
  description = "Contact email shown in podcast apps"
  type        = string
  default     = "hello@example.com"
}

variable "tts_voice" {
  description = "OpenAI TTS voice to use (alloy, echo, fable, onyx, nova, shimmer)"
  type        = string
  default     = "nova"
}

variable "alert_email" {
  description = "Email address to receive CloudWatch alarm notifications"
  type        = string
  default     = ""
}

variable "log_retention_days" {
  description = "CloudWatch Log Group retention period in days"
  type        = number
  default     = 30
}

variable "lambda_memory_ingest" {
  description = "Memory allocation (MB) for the IngestNews Lambda"
  type        = number
  default     = 256
}

variable "lambda_memory_summaries" {
  description = "Memory allocation (MB) for the GenerateSummaries Lambda"
  type        = number
  default     = 512
}

variable "lambda_memory_audio" {
  description = "Memory allocation (MB) for the GenerateAudio Lambda"
  type        = number
  default     = 1024
}

variable "lambda_timeout" {
  description = "Maximum execution time (seconds) for all Lambda functions"
  type        = number
  default     = 300
}

variable "cloudfront_price_class" {
  description = "CloudFront price class (PriceClass_100 = US/EU only, cheapest)"
  type        = string
  default     = "PriceClass_100"
}

variable "enable_api_gateway" {
  description = "Deploy the API Gateway HTTP API fronting Lambda 4 (Episodes API). Set false for dev to save cost."
  type        = bool
  default     = false
}

variable "admin_api_key" {
  description = "Bearer token for the internal Episodes API. Leave empty to disable auth (not recommended for prod)."
  type        = string
  sensitive   = true
  default     = ""
}
