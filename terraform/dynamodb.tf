# ─────────────────────────────────────────────────────────────────────────────
# DynamoDB — Episode metadata table (on-demand billing)
# ─────────────────────────────────────────────────────────────────────────────

resource "aws_dynamodb_table" "episodes" {
  name         = "${local.prefix}-episodes"
  billing_mode = "PAY_PER_REQUEST"
  table_class  = "STANDARD"

  # Primary key: episode_id (partition) + date (sort) matches the handler Key used in UpdateItem
  hash_key  = "episode_id"
  range_key = "date"

  attribute {
    name = "episode_id"
    type = "S"
  }

  attribute {
    name = "date"
    type = "S"
  }

  attribute {
    name = "category"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  # GSI: query all episodes for a given date, newest first (used by RSS feed builder)
  global_secondary_index {
    name            = "date-created_at-index"
    hash_key        = "date"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  # GSI: query episodes by category and date (for category-filtered feeds)
  global_secondary_index {
    name            = "category-date-index"
    hash_key        = "category"
    range_key       = "date"
    projection_type = "ALL"
  }

  # Expire old records after ~1 year to control storage costs
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  # DynamoDB Streams: triggers GenerateAudio when a new episode is summarised
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  point_in_time_recovery {
    enabled = true
  }
}
