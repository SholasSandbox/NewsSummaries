# ─────────────────────────────────────────────────────────────────────────────
# SQS — Dead Letter Queues for all Lambda functions
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_sqs_queue" "ingest_dlq" {
  name                       = "${local.prefix}-ingest-dlq"
  message_retention_seconds  = 1209600 # 14 days
  visibility_timeout_seconds = 30
  sqs_managed_sse_enabled    = true
}

resource "aws_sqs_queue" "summaries_dlq" {
  name                       = "${local.prefix}-summaries-dlq"
  message_retention_seconds  = 1209600
  visibility_timeout_seconds = 30
  sqs_managed_sse_enabled    = true
}

resource "aws_sqs_queue" "audio_dlq" {
  name                       = "${local.prefix}-audio-dlq"
  message_retention_seconds  = 1209600
  visibility_timeout_seconds = 30
  sqs_managed_sse_enabled    = true
}

# ── CloudWatch alarm: alert when any DLQ receives a message ──────────────────
resource "aws_cloudwatch_metric_alarm" "ingest_dlq_messages" {
  alarm_name          = "${local.prefix}-ingest-dlq-messages"
  alarm_description   = "IngestNews Lambda failures reached the Dead Letter Queue"
  namespace           = "AWS/SQS"
  metric_name         = "NumberOfMessagesSent"
  dimensions          = { QueueName = aws_sqs_queue.ingest_dlq.name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alert_email != "" ? [aws_sns_topic.errors.arn] : []
}

resource "aws_cloudwatch_metric_alarm" "summaries_dlq_messages" {
  alarm_name          = "${local.prefix}-summaries-dlq-messages"
  alarm_description   = "GenerateSummaries Lambda failures reached the Dead Letter Queue"
  namespace           = "AWS/SQS"
  metric_name         = "NumberOfMessagesSent"
  dimensions          = { QueueName = aws_sqs_queue.summaries_dlq.name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alert_email != "" ? [aws_sns_topic.errors.arn] : []
}
