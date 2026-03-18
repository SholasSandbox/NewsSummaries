# ─────────────────────────────────────────────────────────────────────────────
# Lambda — Package and deploy all three pipeline functions
#
# Build step:  `make build` (pip install → dist/, then Terraform archives them)
# ─────────────────────────────────────────────────────────────────────────────

# ── Build Lambda deployment packages ─────────────────────────────────────────

# IngestNews
resource "null_resource" "build_ingest_news" {
  triggers = {
    handler      = filemd5("${local.src_root}/ingest_news/handler.py")
    requirements = filemd5("${local.src_root}/ingest_news/requirements.txt")
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -e
      rm -rf "${local.dist_root}/ingest_news"
      mkdir -p "${local.dist_root}/ingest_news"
      cp "${local.src_root}/ingest_news/handler.py" "${local.dist_root}/ingest_news/"
      cp -r "${local.src_root}/shared" "${local.dist_root}/ingest_news/"
      pip install \
        -r "${local.src_root}/ingest_news/requirements.txt" \
        -t "${local.dist_root}/ingest_news/" \
        --quiet --upgrade
    EOT
  }
}

data "archive_file" "ingest_news" {
  depends_on  = [null_resource.build_ingest_news]
  type        = "zip"
  source_dir  = "${local.dist_root}/ingest_news"
  output_path = "${local.dist_root}/ingest_news.zip"
}

# GenerateSummaries
resource "null_resource" "build_generate_summaries" {
  triggers = {
    handler      = filemd5("${local.src_root}/generate_summaries/handler.py")
    requirements = filemd5("${local.src_root}/generate_summaries/requirements.txt")
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -e
      rm -rf "${local.dist_root}/generate_summaries"
      mkdir -p "${local.dist_root}/generate_summaries"
      cp "${local.src_root}/generate_summaries/handler.py" "${local.dist_root}/generate_summaries/"
      cp -r "${local.src_root}/shared" "${local.dist_root}/generate_summaries/"
      pip install \
        -r "${local.src_root}/generate_summaries/requirements.txt" \
        -t "${local.dist_root}/generate_summaries/" \
        --quiet --upgrade
    EOT
  }
}

data "archive_file" "generate_summaries" {
  depends_on  = [null_resource.build_generate_summaries]
  type        = "zip"
  source_dir  = "${local.dist_root}/generate_summaries"
  output_path = "${local.dist_root}/generate_summaries.zip"
}

# GenerateAudio
resource "null_resource" "build_generate_audio" {
  triggers = {
    handler      = filemd5("${local.src_root}/generate_audio/handler.py")
    requirements = filemd5("${local.src_root}/generate_audio/requirements.txt")
  }

  provisioner "local-exec" {
    command = <<-EOT
      set -e
      rm -rf "${local.dist_root}/generate_audio"
      mkdir -p "${local.dist_root}/generate_audio"
      cp "${local.src_root}/generate_audio/handler.py" "${local.dist_root}/generate_audio/"
      cp -r "${local.src_root}/shared" "${local.dist_root}/generate_audio/"
      pip install \
        -r "${local.src_root}/generate_audio/requirements.txt" \
        -t "${local.dist_root}/generate_audio/" \
        --quiet --upgrade
    EOT
  }
}

data "archive_file" "generate_audio" {
  depends_on  = [null_resource.build_generate_audio]
  type        = "zip"
  source_dir  = "${local.dist_root}/generate_audio"
  output_path = "${local.dist_root}/generate_audio.zip"
}

# ── Lambda Functions ──────────────────────────────────────────────────────────

resource "aws_lambda_function" "ingest_news" {
  function_name    = "${local.prefix}-ingest-news"
  description      = "Fetches news from RSS feeds and NewsAPI.org, stores raw articles in S3"
  role             = aws_iam_role.ingest_news.arn
  filename         = data.archive_file.ingest_news.output_path
  source_code_hash = data.archive_file.ingest_news.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.11"
  architectures    = ["arm64"]
  memory_size      = var.lambda_memory_ingest
  timeout          = var.lambda_timeout

  environment {
    variables = merge(local.common_lambda_env, {
      NEWS_API_KEY = var.news_api_key
      RSS_FEEDS    = var.rss_feeds
    })
  }

  dead_letter_config {
    target_arn = aws_sqs_queue.ingest_dlq.arn
  }

  tracing_config {
    mode = "Active"
  }

  depends_on = [
    aws_iam_role_policy_attachment.ingest_news_basic,
    aws_cloudwatch_log_group.ingest_news,
  ]
}

resource "aws_lambda_function" "generate_summaries" {
  function_name    = "${local.prefix}-generate-summaries"
  description      = "Generates AI summaries from raw articles using OpenAI o3-mini"
  role             = aws_iam_role.generate_summaries.arn
  filename         = data.archive_file.generate_summaries.output_path
  source_code_hash = data.archive_file.generate_summaries.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.11"
  architectures    = ["arm64"]
  memory_size      = var.lambda_memory_summaries
  timeout          = var.lambda_timeout

  environment {
    variables = merge(local.common_lambda_env, {
      OPENAI_API_KEY = var.openai_api_key
      OPENAI_MODEL   = "o3-mini"
    })
  }

  dead_letter_config {
    target_arn = aws_sqs_queue.summaries_dlq.arn
  }

  tracing_config {
    mode = "Active"
  }

  depends_on = [
    aws_iam_role_policy_attachment.generate_summaries_basic,
    aws_cloudwatch_log_group.generate_summaries,
  ]
}

resource "aws_lambda_function" "generate_audio" {
  function_name    = "${local.prefix}-generate-audio"
  description      = "Converts summaries to audio with OpenAI TTS and publishes RSS feed"
  role             = aws_iam_role.generate_audio.arn
  filename         = data.archive_file.generate_audio.output_path
  source_code_hash = data.archive_file.generate_audio.output_base64sha256
  handler          = "handler.lambda_handler"
  runtime          = "python3.11"
  architectures    = ["arm64"]
  memory_size      = var.lambda_memory_audio
  timeout          = var.lambda_timeout

  environment {
    variables = merge(local.common_lambda_env, {
      OPENAI_API_KEY      = var.openai_api_key
      TTS_MODEL           = "tts-1"
      TTS_VOICE           = var.tts_voice
      PODCAST_TITLE       = var.podcast_title
      PODCAST_DESCRIPTION = var.podcast_description
      PODCAST_AUTHOR      = var.podcast_author
      PODCAST_EMAIL       = var.podcast_email
    })
  }

  dead_letter_config {
    target_arn = aws_sqs_queue.audio_dlq.arn
  }

  tracing_config {
    mode = "Active"
  }

  depends_on = [
    aws_iam_role_policy_attachment.generate_audio_basic,
    aws_cloudwatch_log_group.generate_audio,
  ]
}

# ── Lambda Triggers / Permissions ─────────────────────────────────────────────

# Allow S3 to invoke GenerateSummaries when raw articles are stored
resource "aws_lambda_permission" "s3_invoke_generate_summaries" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.generate_summaries.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.content.arn
}

# DynamoDB Streams → GenerateAudio: fires when an episode reaches "summarized" status
resource "aws_lambda_event_source_mapping" "dynamodb_to_generate_audio" {
  event_source_arn               = aws_dynamodb_table.episodes.stream_arn
  function_name                  = aws_lambda_function.generate_audio.arn
  starting_position              = "LATEST"
  bisect_batch_on_function_error = true
  maximum_retry_attempts         = 2

  filter_criteria {
    filter {
      pattern = jsonencode({
        eventName = ["INSERT"]
        dynamodb = {
          newImage = {
            status = { S = ["summarized"] }
          }
        }
      })
    }
  }

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.audio_dlq.arn
    }
  }
}
