locals {
  # Short prefix used throughout all resource names
  prefix = "news-summaries-${var.stage}"

  # Lambda source paths (relative to project root, resolved from terraform/)
  src_root = "${path.module}/../src"

  # Build output path (generated during `make build`)
  dist_root = "${path.module}/../dist"

  # Common Lambda environment variables shared by all three functions
  common_lambda_env = {
    STAGE               = var.stage
    S3_BUCKET_NAME      = aws_s3_bucket.content.bucket
    DYNAMODB_TABLE_NAME = aws_dynamodb_table.episodes.name
    CLOUDFRONT_DOMAIN   = aws_cloudfront_distribution.cdn.domain_name
    LOG_LEVEL           = var.stage == "prod" ? "INFO" : "DEBUG"
  }
}
