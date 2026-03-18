# ─────────────────────────────────────────────────────────────────────────────
# EventBridge Scheduler — Trigger IngestNews twice daily
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_scheduler_schedule" "morning_ingest" {
  name                         = "${local.prefix}-morning-ingest"
  description                  = "Morning news ingestion at 06:00 UTC"
  schedule_expression          = "cron(0 6 * * ? *)"
  schedule_expression_timezone = "UTC"
  state                        = "ENABLED"

  flexible_time_window {
    mode                      = "FLEXIBLE"
    maximum_window_in_minutes = 10
  }

  target {
    arn      = aws_lambda_function.ingest_news.arn
    role_arn = aws_iam_role.eventbridge_scheduler.arn

    retry_policy {
      maximum_retry_attempts = 2
    }
  }
}

resource "aws_scheduler_schedule" "evening_ingest" {
  name                         = "${local.prefix}-evening-ingest"
  description                  = "Evening news ingestion at 18:00 UTC"
  schedule_expression          = "cron(0 18 * * ? *)"
  schedule_expression_timezone = "UTC"
  state                        = "ENABLED"

  flexible_time_window {
    mode                      = "FLEXIBLE"
    maximum_window_in_minutes = 10
  }

  target {
    arn      = aws_lambda_function.ingest_news.arn
    role_arn = aws_iam_role.eventbridge_scheduler.arn

    retry_policy {
      maximum_retry_attempts = 2
    }
  }
}
