# ─────────────────────────────────────────────────────────────────────────────
# S3 — Content bucket (raw articles, summaries, audio, RSS feed)
# ─────────────────────────────────────────────────────────────────────────────

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "content" {
  bucket = "${local.prefix}-content-${data.aws_caller_identity.current.account_id}"

  # Safety net: prevent accidental deletion in production
  force_destroy = var.stage != "prod"
}

resource "aws_s3_bucket_versioning" "content" {
  bucket = aws_s3_bucket.content.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "content" {
  bucket = aws_s3_bucket.content.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# Block all public access — CloudFront uses OAC for authenticated reads
resource "aws_s3_bucket_public_access_block" "content" {
  bucket                  = aws_s3_bucket.content.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── Lifecycle policies for cost optimisation ──────────────────────────────────
resource "aws_s3_bucket_lifecycle_configuration" "content" {
  bucket = aws_s3_bucket.content.id

  rule {
    id     = "raw-articles-lifecycle"
    status = "Enabled"
    filter { prefix = "raw/" }
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    expiration { days = 90 }
  }

  rule {
    id     = "summaries-lifecycle"
    status = "Enabled"
    filter { prefix = "summaries/" }
    transition {
      days          = 60
      storage_class = "STANDARD_IA"
    }
    expiration { days = 365 }
  }

  rule {
    id     = "audio-lifecycle"
    status = "Enabled"
    filter { prefix = "audio/" }
    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }
    transition {
      days          = 180
      storage_class = "GLACIER"
    }
  }

  rule {
    id     = "abort-multipart"
    status = "Enabled"
    filter { prefix = "" }
    abort_incomplete_multipart_upload { days_after_initiation = 7 }
  }
}

# ── Bucket policy: allow CloudFront OAC to read audio and RSS feed ────────────
resource "aws_s3_bucket_policy" "content" {
  bucket = aws_s3_bucket.content.id
  policy = data.aws_iam_policy_document.content_bucket_policy.json

  # Bucket policy references the CloudFront distribution — create distribution first
  depends_on = [aws_cloudfront_distribution.cdn]
}

data "aws_iam_policy_document" "content_bucket_policy" {
  statement {
    sid    = "AllowCloudFrontReadAudio"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.content.arn}/audio/*"]
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.cdn.arn]
    }
  }

  statement {
    sid    = "AllowCloudFrontReadFeed"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.content.arn}/rss/feed.xml"]
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.cdn.arn]
    }
  }
}

# ── S3 event notification: trigger GenerateSummaries on new raw articles ──────
resource "aws_s3_bucket_notification" "content" {
  bucket = aws_s3_bucket.content.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.generate_summaries.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "raw/"
    filter_suffix       = ".json"
  }

  depends_on = [aws_lambda_permission.s3_invoke_generate_summaries]
}
