# ─────────────────────────────────────────────────────────────────────────────
# CloudFront — CDN for audio delivery and RSS feed
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_cloudfront_origin_access_control" "content" {
  name                              = "${local.prefix}-oac"
  description                       = "OAC for News Summaries S3 content bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "cdn" {
  comment             = "News Summaries CDN — ${var.stage}"
  enabled             = true
  http_version        = "http2and3"
  price_class         = var.cloudfront_price_class
  is_ipv6_enabled     = true
  default_root_object = "feed.xml"

  origin {
    origin_id                = "S3ContentOrigin"
    domain_name              = aws_s3_bucket.content.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.content.id
  }

  # Default behaviour: cache audio files aggressively (24h)
  default_cache_behavior {
    target_origin_id       = "S3ContentOrigin"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    # Managed cache policy: CachingOptimized
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  }

  # RSS feed: short TTL so listeners get fresh episodes quickly
  ordered_cache_behavior {
    path_pattern           = "/rss/feed.xml"
    target_origin_id       = "S3ContentOrigin"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    # Managed cache policy: CachingDisabled (always go to origin)
    cache_policy_id = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
