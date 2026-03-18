output "content_bucket_name" {
  description = "S3 bucket storing raw articles, summaries, audio, and the RSS feed"
  value       = aws_s3_bucket.content.bucket
}

output "episodes_table_name" {
  description = "DynamoDB table name for episode metadata"
  value       = aws_dynamodb_table.episodes.name
}

output "cloudfront_domain" {
  description = "CloudFront domain used for audio CDN and RSS feed delivery"
  value       = aws_cloudfront_distribution.cdn.domain_name
}

output "podcast_feed_url" {
  description = "Public URL of the podcast RSS feed"
  value       = "https://${aws_cloudfront_distribution.cdn.domain_name}/rss/feed.xml"
}

output "ingest_news_function_arn" {
  description = "ARN of the IngestNews Lambda function"
  value       = aws_lambda_function.ingest_news.arn
}

output "generate_summaries_function_arn" {
  description = "ARN of the GenerateSummaries Lambda function"
  value       = aws_lambda_function.generate_summaries.arn
}

output "generate_audio_function_arn" {
  description = "ARN of the GenerateAudio Lambda function"
  value       = aws_lambda_function.generate_audio.arn
}

output "ingest_dlq_url" {
  description = "URL of the IngestNews Dead Letter Queue"
  value       = aws_sqs_queue.ingest_dlq.url
}

output "error_topic_arn" {
  description = "ARN of the SNS topic for error alerts"
  value       = aws_sns_topic.errors.arn
}

output "episodes_api_function_arn" {
  description = "ARN of the Episodes API Lambda function (Lambda 4)"
  value       = aws_lambda_function.episodes_api.arn
}

output "episodes_api_url" {
  description = "API Gateway URL for the Episodes API (empty when enable_api_gateway = false)"
  value       = var.enable_api_gateway ? aws_apigatewayv2_api.episodes[0].api_endpoint : ""
}
