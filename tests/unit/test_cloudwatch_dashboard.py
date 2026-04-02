"""
tests/unit/test_cloudwatch_dashboard.py

Static-analysis tests for terraform/cloudwatch.tf.

These tests parse the raw Terraform HCL text and verify the structural
guarantees of the CloudWatch dashboard introduced in the #4 enhancement:
  - All four Lambda functions (ingest_news, generate_summaries,
    generate_audio, episodes_api) appear in every Lambda metric widget
  - Duration widget uses p99 (not Average)
  - CloudFront Requests widget exists (Sum stat)
  - CloudFront Error Rates widget exists with separate Average stat
  - No mixing of incompatible unit types within a single widget
"""

from __future__ import annotations

import os
import re
from typing import Iterator

import pytest

# ── Path to the Terraform file under test ────────────────────────────────────

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CLOUDWATCH_TF = os.path.join(REPO_ROOT, "terraform", "cloudwatch.tf")


# ── Helpers ───────────────────────────────────────────────────────────────────


def read_tf() -> str:
    """Return the full text content of cloudwatch.tf."""
    with open(CLOUDWATCH_TF, encoding="utf-8") as fh:
        return fh.read()


def extract_widget_blocks(tf_text: str) -> list[str]:
    """
    Split the dashboard_body widgets array into individual widget blocks.
    Each block is the text between a pair of balanced braces that starts
    with 'type = "metric"'.
    """
    # Find the start of each widget block
    widget_pattern = re.compile(r'\{\s*\n\s*type\s*=\s*"metric"', re.MULTILINE)
    starts = [m.start() for m in widget_pattern.finditer(tf_text)]

    blocks: list[str] = []
    for start in starts:
        # Walk forward counting braces to find the matching close
        depth = 0
        end = start
        for i, ch in enumerate(tf_text[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        blocks.append(tf_text[start:end])

    return blocks


def widget_title(block: str) -> str:
    """Extract the title string from a widget block."""
    m = re.search(r'title\s*=\s*"([^"]+)"', block)
    return m.group(1) if m else ""


def lambda_functions_in_widget(block: str) -> list[str]:
    """
    Return the Terraform resource references used as FunctionName values
    inside a widget's metrics array (e.g. 'aws_lambda_function.episodes_api').
    """
    return re.findall(
        r'aws_lambda_function\.([a-zA-Z0-9_]+)\.function_name',
        block,
    )


def widget_stat(block: str) -> str | None:
    """Return the stat value of a widget (e.g. 'Sum', 'p99', 'Average')."""
    m = re.search(r'\bstat\s*=\s*"([^"]+)"', block)
    return m.group(1) if m else None


def metric_names_in_widget(block: str) -> list[str]:
    """
    Return all CloudWatch metric names referenced in the widget's metrics list.
    E.g. ["Invocations"], ["Errors"], ["4xxErrorRate", "5xxErrorRate"]
    """
    # Metrics entries look like: ["AWS/Lambda", "Invocations", ...]
    return re.findall(r'"AWS/Lambda",\s*"([^"]+)"', block) + \
           re.findall(r'"AWS/CloudFront",\s*"([^"]+)"', block) + \
           re.findall(r'"AWS/SQS",\s*"([^"]+)"', block)


def lambda_widgets(tf_text: str) -> Iterator[tuple[str, str]]:
    """
    Yield (title, block) for every widget that tracks Lambda metrics.
    """
    for block in extract_widget_blocks(tf_text):
        if "AWS/Lambda" in block:
            yield widget_title(block), block


# ── Required Lambda functions in every Lambda widget ─────────────────────────

ALL_LAMBDA_FUNCTIONS = {
    "ingest_news",
    "generate_summaries",
    "generate_audio",
    "episodes_api",
}


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestCloudWatchDashboardFile:
    """Verify the cloudwatch.tf file exists and is non-empty."""

    def test_file_exists(self) -> None:
        assert os.path.isfile(CLOUDWATCH_TF), f"Missing file: {CLOUDWATCH_TF}"

    def test_file_is_non_empty(self) -> None:
        assert os.path.getsize(CLOUDWATCH_TF) > 0

    def test_dashboard_resource_present(self) -> None:
        tf = read_tf()
        assert 'resource "aws_cloudwatch_dashboard" "main"' in tf

    def test_dashboard_body_uses_jsonencode(self) -> None:
        tf = read_tf()
        assert "jsonencode(" in tf, "dashboard_body should use jsonencode()"


class TestLambdaWidgetCompleteness:
    """
    Every Lambda metric widget must track all four Lambda functions,
    including episodes_api (Lambda 4) which was added in the #4 enhancement.
    """

    def test_at_least_three_lambda_widgets_exist(self) -> None:
        tf = read_tf()
        titles = [t for t, _ in lambda_widgets(tf)]
        assert len(titles) >= 3, (
            f"Expected at least 3 Lambda metric widgets, found: {titles}"
        )

    @pytest.mark.parametrize(
        "fn_name",
        sorted(ALL_LAMBDA_FUNCTIONS),
    )
    def test_invocations_widget_includes_lambda(self, fn_name: str) -> None:
        tf = read_tf()
        for title, block in lambda_widgets(tf):
            if "Invocations" in title:
                fns = set(lambda_functions_in_widget(block))
                assert fn_name in fns, (
                    f"Widget '{title}' is missing Lambda function '{fn_name}'. "
                    f"Found: {fns}"
                )

    @pytest.mark.parametrize(
        "fn_name",
        sorted(ALL_LAMBDA_FUNCTIONS),
    )
    def test_errors_widget_includes_lambda(self, fn_name: str) -> None:
        tf = read_tf()
        for title, block in lambda_widgets(tf):
            if "Error" in title:
                fns = set(lambda_functions_in_widget(block))
                assert fn_name in fns, (
                    f"Widget '{title}' is missing Lambda function '{fn_name}'. "
                    f"Found: {fns}"
                )

    @pytest.mark.parametrize(
        "fn_name",
        sorted(ALL_LAMBDA_FUNCTIONS),
    )
    def test_duration_widget_includes_lambda(self, fn_name: str) -> None:
        tf = read_tf()
        for title, block in lambda_widgets(tf):
            if "Duration" in title:
                fns = set(lambda_functions_in_widget(block))
                assert fn_name in fns, (
                    f"Widget '{title}' is missing Lambda function '{fn_name}'. "
                    f"Found: {fns}"
                )


class TestDurationWidgetStat:
    """The Duration widget must use p99 (not the old 'Average') for actionable latency data."""

    def test_duration_widget_uses_p99(self) -> None:
        tf = read_tf()
        for title, block in lambda_widgets(tf):
            if "Duration" in title:
                stat = widget_stat(block)
                assert stat == "p99", (
                    f"Duration widget '{title}' should use stat='p99', got '{stat}'"
                )


class TestCloudFrontWidgets:
    """
    The CloudFront Requests and Error Rates widgets must exist as separate
    blocks with appropriate stats to avoid mixing incompatible unit types.
    """

    def test_cloudfront_requests_widget_exists(self) -> None:
        tf = read_tf()
        titles = [widget_title(b) for b in extract_widget_blocks(tf)]
        assert "CloudFront Requests" in titles, (
            f"Missing 'CloudFront Requests' widget. Found widgets: {titles}"
        )

    def test_cloudfront_error_rates_widget_exists(self) -> None:
        tf = read_tf()
        titles = [widget_title(b) for b in extract_widget_blocks(tf)]
        assert any("Error Rate" in t or "Error Rates" in t for t in titles), (
            f"Missing CloudFront Error Rates widget. Found widgets: {titles}"
        )

    def test_cloudfront_requests_uses_sum_stat(self) -> None:
        tf = read_tf()
        for block in extract_widget_blocks(tf):
            if widget_title(block) == "CloudFront Requests":
                stat = widget_stat(block)
                assert stat == "Sum", (
                    f"CloudFront Requests widget should use stat='Sum', got '{stat}'"
                )

    def test_cloudfront_error_rates_uses_average_stat(self) -> None:
        tf = read_tf()
        for block in extract_widget_blocks(tf):
            if "Error Rate" in widget_title(block) or "Error Rates" in widget_title(block):
                stat = widget_stat(block)
                assert stat == "Average", (
                    f"CloudFront Error Rates widget should use stat='Average', got '{stat}'"
                )

    def test_cloudfront_requests_widget_does_not_contain_error_rate_metrics(self) -> None:
        """
        Guard against regression where error rate metrics were mixed into the
        Requests widget — they use different units (count vs %).
        """
        tf = read_tf()
        for block in extract_widget_blocks(tf):
            if widget_title(block) == "CloudFront Requests":
                assert "ErrorRate" not in block, (
                    "CloudFront Requests widget must not contain ErrorRate metrics "
                    "(incompatible units — count vs %). Use a separate widget."
                )

    def test_cloudfront_error_rates_widget_tracks_both_4xx_and_5xx(self) -> None:
        tf = read_tf()
        for block in extract_widget_blocks(tf):
            if "Error Rate" in widget_title(block) or "Error Rates" in widget_title(block):
                assert "4xxErrorRate" in block, "Missing 4xxErrorRate metric"
                assert "5xxErrorRate" in block, "Missing 5xxErrorRate metric"


class TestEpisodesApiAlarm:
    """The episodes_api Lambda must have its own CloudWatch alarm like the other three."""

    def test_episodes_api_alarm_resource_exists(self) -> None:
        tf = read_tf()
        assert 'resource "aws_cloudwatch_metric_alarm" "episodes_api_errors"' in tf

    def test_episodes_api_alarm_references_correct_function(self) -> None:
        tf = read_tf()
        # The alarm should reference the episodes_api function name
        block_match = re.search(
            r'resource "aws_cloudwatch_metric_alarm" "episodes_api_errors"(.+?)^}',
            tf,
            re.MULTILINE | re.DOTALL,
        )
        assert block_match, "episodes_api_errors alarm block not found"
        block = block_match.group(1)
        assert "aws_lambda_function.episodes_api.function_name" in block

    def test_all_four_lambda_alarms_exist(self) -> None:
        tf = read_tf()
        expected_alarms = [
            "ingest_news_errors",
            "generate_summaries_errors",
            "generate_audio_errors",
            "episodes_api_errors",
        ]
        for alarm in expected_alarms:
            assert f'"aws_cloudwatch_metric_alarm" "{alarm}"' in tf, (
                f"Missing CloudWatch alarm resource: {alarm}"
            )


class TestDashboardWidgetCount:
    """Sanity-check that the dashboard has the expected number of widgets."""

    def test_dashboard_has_at_least_six_widgets(self) -> None:
        tf = read_tf()
        widgets = extract_widget_blocks(tf)
        assert len(widgets) >= 6, (
            f"Expected at least 6 dashboard widgets, found {len(widgets)}: "
            f"{[widget_title(b) for b in widgets]}"
        )
