# ─────────────────────────────────────────────────────────────────────────────
# IAM — Lambda execution roles (least-privilege)
# ─────────────────────────────────────────────────────────────────────────────

# ── Shared assume-role policy for all Lambda functions ────────────────────────
data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# ── IngestNews Lambda Role ────────────────────────────────────────────────────
resource "aws_iam_role" "ingest_news" {
  name               = "${local.prefix}-ingest-news-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy_attachment" "ingest_news_basic" {
  role       = aws_iam_role.ingest_news.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "ingest_news_xray" {
  role       = aws_iam_role.ingest_news.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

data "aws_iam_policy_document" "ingest_news_inline" {
  # Write raw articles to S3
  statement {
    sid    = "S3WriteRaw"
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.content.arn,
      "${aws_s3_bucket.content.arn}/raw/*",
    ]
  }

  # Async invoke GenerateSummaries
  statement {
    sid       = "InvokeSummaries"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.generate_summaries.arn]
  }

  # Send to Dead Letter Queue on failure
  statement {
    sid       = "SQSSendDLQ"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.ingest_dlq.arn]
  }
}

resource "aws_iam_role_policy" "ingest_news_inline" {
  name   = "${local.prefix}-ingest-news-policy"
  role   = aws_iam_role.ingest_news.id
  policy = data.aws_iam_policy_document.ingest_news_inline.json
}

# ── GenerateSummaries Lambda Role ─────────────────────────────────────────────
resource "aws_iam_role" "generate_summaries" {
  name               = "${local.prefix}-generate-summaries-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy_attachment" "generate_summaries_basic" {
  role       = aws_iam_role.generate_summaries.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "generate_summaries_xray" {
  role       = aws_iam_role.generate_summaries.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

data "aws_iam_policy_document" "generate_summaries_inline" {
  # Read raw articles from S3; write summaries
  statement {
    sid    = "S3ReadWriteSummaries"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.content.arn,
      "${aws_s3_bucket.content.arn}/raw/*",
      "${aws_s3_bucket.content.arn}/summaries/*",
    ]
  }

  # Write episode metadata to DynamoDB
  statement {
    sid    = "DynamoDBWrite"
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:GetItem",
      "dynamodb:Query",
    ]
    resources = [
      aws_dynamodb_table.episodes.arn,
      "${aws_dynamodb_table.episodes.arn}/index/*",
    ]
  }

  # Send to DLQ
  statement {
    sid       = "SQSSendDLQ"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.summaries_dlq.arn]
  }
}

resource "aws_iam_role_policy" "generate_summaries_inline" {
  name   = "${local.prefix}-generate-summaries-policy"
  role   = aws_iam_role.generate_summaries.id
  policy = data.aws_iam_policy_document.generate_summaries_inline.json
}

# ── GenerateAudio Lambda Role ─────────────────────────────────────────────────
resource "aws_iam_role" "generate_audio" {
  name               = "${local.prefix}-generate-audio-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy_attachment" "generate_audio_basic" {
  role       = aws_iam_role.generate_audio.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "generate_audio_xray" {
  role       = aws_iam_role.generate_audio.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

# Allow Lambda to read DynamoDB Streams
resource "aws_iam_role_policy_attachment" "generate_audio_dynamo_streams" {
  role       = aws_iam_role.generate_audio.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaDynamoDBExecutionRole"
}

data "aws_iam_policy_document" "generate_audio_inline" {
  # Read summaries, write audio and RSS feed
  statement {
    sid    = "S3ReadWriteAudio"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.content.arn,
      "${aws_s3_bucket.content.arn}/summaries/*",
      "${aws_s3_bucket.content.arn}/audio/*",
      "${aws_s3_bucket.content.arn}/rss/feed.xml",
    ]
  }

  # Update episode records in DynamoDB
  statement {
    sid    = "DynamoDBUpdate"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:UpdateItem",
      "dynamodb:Query",
      "dynamodb:Scan",
    ]
    resources = [
      aws_dynamodb_table.episodes.arn,
      "${aws_dynamodb_table.episodes.arn}/index/*",
    ]
  }

  # Send to DLQ
  statement {
    sid       = "SQSSendDLQ"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.audio_dlq.arn]
  }
}

resource "aws_iam_role_policy" "generate_audio_inline" {
  name   = "${local.prefix}-generate-audio-policy"
  role   = aws_iam_role.generate_audio.id
  policy = data.aws_iam_policy_document.generate_audio_inline.json
}

# ── EventBridge Scheduler role ────────────────────────────────────────────────
data "aws_iam_policy_document" "scheduler_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eventbridge_scheduler" {
  name               = "${local.prefix}-scheduler-role"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume_role.json
}

data "aws_iam_policy_document" "scheduler_invoke" {
  statement {
    sid       = "InvokeIngestNews"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.ingest_news.arn]
  }
}

resource "aws_iam_role_policy" "scheduler_invoke" {
  name   = "${local.prefix}-scheduler-invoke-policy"
  role   = aws_iam_role.eventbridge_scheduler.id
  policy = data.aws_iam_policy_document.scheduler_invoke.json
}
