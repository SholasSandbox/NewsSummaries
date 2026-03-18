# ─────────────────────────────────────────────────────────────────────────────
# CloudWatch — Log groups, metric alarms, dashboard, and SNS alerting
# ─────────────────────────────────────────────────────────────────────────────

# ── Log Groups ────────────────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "ingest_news" {
  name              = "/aws/lambda/${local.prefix}-ingest-news"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "generate_summaries" {
  name              = "/aws/lambda/${local.prefix}-generate-summaries"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "generate_audio" {
  name              = "/aws/lambda/${local.prefix}-generate-audio"
  retention_in_days = var.log_retention_days
}

# ── SNS Topic for error alerts ────────────────────────────────────────────────

resource "aws_sns_topic" "errors" {
  name         = "${local.prefix}-errors"
  display_name = "News Summaries Error Alerts"
}

resource "aws_sns_topic_subscription" "alert_email" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.errors.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ── Lambda Error Alarms ───────────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "ingest_news_errors" {
  alarm_name          = "${local.prefix}-ingest-news-errors"
  alarm_description   = "IngestNews Lambda error rate is elevated"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.ingest_news.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alert_email != "" ? [aws_sns_topic.errors.arn] : []
}

resource "aws_cloudwatch_metric_alarm" "generate_summaries_errors" {
  alarm_name          = "${local.prefix}-generate-summaries-errors"
  alarm_description   = "GenerateSummaries Lambda error rate is elevated"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.generate_summaries.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alert_email != "" ? [aws_sns_topic.errors.arn] : []
}

resource "aws_cloudwatch_metric_alarm" "generate_audio_errors" {
  alarm_name          = "${local.prefix}-generate-audio-errors"
  alarm_description   = "GenerateAudio Lambda error rate is elevated"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.generate_audio.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alert_email != "" ? [aws_sns_topic.errors.arn] : []
}

# ── Observability Dashboard ───────────────────────────────────────────────────

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "NewsSummaries-${var.stage}"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric"
        properties = {
          title  = "Lambda Invocations"
          period = 3600
          stat   = "Sum"
          view   = "timeSeries"
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.ingest_news.function_name],
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.generate_summaries.function_name],
            ["AWS/Lambda", "Invocations", "FunctionName", aws_lambda_function.generate_audio.function_name],
          ]
        }
      },
      {
        type = "metric"
        properties = {
          title  = "Lambda Errors"
          period = 3600
          stat   = "Sum"
          view   = "timeSeries"
          metrics = [
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.ingest_news.function_name],
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.generate_summaries.function_name],
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.generate_audio.function_name],
          ]
        }
      },
      {
        type = "metric"
        properties = {
          title  = "Lambda Duration (avg ms)"
          period = 3600
          stat   = "Average"
          view   = "timeSeries"
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.ingest_news.function_name],
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.generate_summaries.function_name],
            ["AWS/Lambda", "Duration", "FunctionName", aws_lambda_function.generate_audio.function_name],
          ]
        }
      },
      {
        type = "metric"
        properties = {
          title  = "DLQ Messages"
          period = 300
          stat   = "Sum"
          view   = "timeSeries"
          metrics = [
            ["AWS/SQS", "NumberOfMessagesSent", "QueueName", aws_sqs_queue.ingest_dlq.name],
            ["AWS/SQS", "NumberOfMessagesSent", "QueueName", aws_sqs_queue.summaries_dlq.name],
            ["AWS/SQS", "NumberOfMessagesSent", "QueueName", aws_sqs_queue.audio_dlq.name],
          ]
        }
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "episodes_api" {
  name              = "/aws/lambda/${local.prefix}-episodes-api"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_metric_alarm" "episodes_api_errors" {
  alarm_name          = "${local.prefix}-episodes-api-errors"
  alarm_description   = "EpisodesAPI Lambda error rate is elevated"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.episodes_api.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 3
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alert_email != "" ? [aws_sns_topic.errors.arn] : []
}
