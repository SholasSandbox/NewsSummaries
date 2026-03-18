# ─────────────────────────────────────────────────────────────────────────────
# API Gateway (HTTP API) — Optional Admin/Observability layer
#
# Corresponds to "Lambda 4 (API Gateway optional) — Episodes API"
# in the architecture diagram.
#
# Set enable_api_gateway = true in terraform.tfvars to activate.
# When disabled (default for dev cost control), Lambda 4 can still be
# invoked directly via the AWS console or CLI for ad-hoc queries.
# ─────────────────────────────────────────────────────────────────────────────

# ── HTTP API (API Gateway v2) ─────────────────────────────────────────────────
resource "aws_apigatewayv2_api" "episodes" {
  count         = var.enable_api_gateway ? 1 : 0
  name          = "${local.prefix}-episodes-api"
  description   = "Internal Episodes API for Admin/Observability — ${var.stage}"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "OPTIONS"]
    allow_headers = ["authorization", "content-type"]
    max_age       = 300
  }
}

# ── Auto-deploy stage ($default) ─────────────────────────────────────────────
resource "aws_apigatewayv2_stage" "episodes_default" {
  count       = var.enable_api_gateway ? 1 : 0
  api_id      = aws_apigatewayv2_api.episodes[0].id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gateway[0].arn
    format = jsonencode({
      requestId      = "$context.requestId"
      ip             = "$context.identity.sourceIp"
      requestTime    = "$context.requestTime"
      httpMethod     = "$context.httpMethod"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      responseLength = "$context.responseLength"
      integrationError = "$context.integrationErrorMessage"
    })
  }

  default_route_settings {
    throttling_burst_limit = 10
    throttling_rate_limit  = 5
  }
}

# ── Lambda integration ────────────────────────────────────────────────────────
resource "aws_apigatewayv2_integration" "episodes_lambda" {
  count                  = var.enable_api_gateway ? 1 : 0
  api_id                 = aws_apigatewayv2_api.episodes[0].id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.episodes_api.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 29000
}

# ── Routes ────────────────────────────────────────────────────────────────────
resource "aws_apigatewayv2_route" "list_episodes" {
  count     = var.enable_api_gateway ? 1 : 0
  api_id    = aws_apigatewayv2_api.episodes[0].id
  route_key = "GET /episodes"
  target    = "integrations/${aws_apigatewayv2_integration.episodes_lambda[0].id}"
}

resource "aws_apigatewayv2_route" "get_episode" {
  count     = var.enable_api_gateway ? 1 : 0
  api_id    = aws_apigatewayv2_api.episodes[0].id
  route_key = "GET /episodes/{episode_id}"
  target    = "integrations/${aws_apigatewayv2_integration.episodes_lambda[0].id}"
}

resource "aws_apigatewayv2_route" "get_audio" {
  count     = var.enable_api_gateway ? 1 : 0
  api_id    = aws_apigatewayv2_api.episodes[0].id
  route_key = "GET /episodes/{episode_id}/audio"
  target    = "integrations/${aws_apigatewayv2_integration.episodes_lambda[0].id}"
}

resource "aws_apigatewayv2_route" "get_transcript" {
  count     = var.enable_api_gateway ? 1 : 0
  api_id    = aws_apigatewayv2_api.episodes[0].id
  route_key = "GET /episodes/{episode_id}/transcript"
  target    = "integrations/${aws_apigatewayv2_integration.episodes_lambda[0].id}"
}

# ── Permission: API Gateway may invoke Lambda ─────────────────────────────────
resource "aws_lambda_permission" "api_gateway_invoke_episodes_api" {
  count         = var.enable_api_gateway ? 1 : 0
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.episodes_api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.episodes[0].execution_arn}/*"
}

# ── CloudWatch log group for API Gateway access logs ─────────────────────────
resource "aws_cloudwatch_log_group" "api_gateway" {
  count             = var.enable_api_gateway ? 1 : 0
  name              = "/aws/apigateway/${local.prefix}-episodes-api"
  retention_in_days = var.log_retention_days
}
