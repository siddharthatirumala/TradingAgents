"""Structured JSON logging: context fields, extras, exceptions and redaction."""

import io
import json
import logging

import pytest

from sid_trading_firm.observability.logging import configure_logging, redact
from sid_trading_firm.runtime import agent_context, run_context

pytestmark = pytest.mark.unit

# Built at runtime so the repository holds no credential-shaped literal for
# secret scanners to flag; it is a made-up value either way.
FAKE_AWS_KEY_ID = "AKIA" + "ABCDEFGHIJKLMNOP"


@pytest.fixture
def log_lines():
    stream = io.StringIO()
    handler = configure_logging("DEBUG", "json", stream=stream)
    yield lambda: [json.loads(line) for line in stream.getvalue().splitlines()]
    logging.getLogger().removeHandler(handler)


def test_each_line_is_json_with_the_run_context(log_lines):
    log = logging.getLogger("sid.test")
    with run_context(instrument="NVDA", strategy="baseline", environment="test") as run, \
            agent_context("technical_analyst"):
        log.info("analysed %s", "NVDA")

    (line,) = log_lines()
    assert line["message"] == "analysed NVDA"
    assert line["level"] == "INFO" and line["logger"] == "sid.test"
    assert line["run_id"] == run.run_id
    assert (line["agent"], line["instrument"], line["strategy"], line["environment"]) == (
        "technical_analyst", "NVDA", "baseline", "test")


def test_outside_a_run_the_context_fields_are_null(log_lines):
    logging.getLogger("sid.test").warning("no run")
    (line,) = log_lines()
    assert line["run_id"] is None and line["agent"] is None


def test_extra_fields_are_kept_and_explicit_context_wins(log_lines):
    with run_context():
        logging.getLogger("sid.test").info("call", extra={"latency_ms": 12.5, "agent": "cio",
                                                          "tags": ["a", "b"]})
    (line,) = log_lines()
    assert line["latency_ms"] == 12.5
    assert line["agent"] == "cio"
    assert line["tags"] == ["a", "b"]


def test_exceptions_are_included(log_lines):
    try:
        raise RuntimeError("vendor down")
    except RuntimeError:
        logging.getLogger("sid.test").exception("fetch failed")
    (line,) = log_lines()
    assert "RuntimeError: vendor down" in line["exception"]


def test_credentials_are_redacted_everywhere(log_lines):
    key = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    try:
        raise ValueError(f"auth failed for {key}")
    except ValueError:
        logging.getLogger("sid.test").exception(
            "connecting to postgresql://sid:hunter2@db/sid with %s", key,
            extra={"header": "Bearer abcdefghijklmnop"})
    raw = json.dumps(log_lines())
    for secret in (key, "hunter2", "abcdefghijklmnop"):
        assert secret not in raw


@pytest.mark.parametrize("text, secret", [
    ("OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwx", "abcdefghijklmnopqrstuvwx"),
    ("api_key: s3cr3tvalue", "s3cr3tvalue"),
    ("password=correcthorse", "correcthorse"),
    (FAKE_AWS_KEY_ID, FAKE_AWS_KEY_ID),
])
def test_redact_masks_common_credential_shapes(text, secret):
    assert secret not in redact(text)


def test_redact_leaves_ordinary_usage_fields_alone():
    text = "input_tokens=1200 output_tokens=300 tokens: 1500"
    assert redact(text) == text


def test_configure_logging_is_idempotent():
    root = logging.getLogger()
    first = configure_logging(stream=io.StringIO())
    second = configure_logging(stream=io.StringIO())
    try:
        assert first not in root.handlers and second in root.handlers
    finally:
        root.removeHandler(second)
