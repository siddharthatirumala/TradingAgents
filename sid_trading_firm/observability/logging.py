"""Structured JSON logging on the standard library.

Every line carries the run context (run_id, agent, instrument, strategy,
environment) and any ``extra=`` fields. Strings that look like credentials are
redacted before a line is written, whichever logger produced it.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

from sid_trading_firm.runtime.context import log_fields

CONTEXT_FIELDS = ("run_id", "agent", "instrument", "strategy", "environment")

# LogRecord's own attributes; anything else on a record came from ``extra=``.
_RECORD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}

_SECRET_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),            # Anthropic keys
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{16,}"),      # OpenAI-style keys
    re.compile(r"AKIA[0-9A-Z]{16}"),                      # AWS access key ids
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"),    # bearer tokens
    re.compile(r"(?i)(\b(?:api[_-]?key|token|secret|password)\b\s*[=:]\s*)[^\s,;&\"']+"),
    re.compile(r"(://[^:/@\s]+:)[^@/\s]+(@)"),            # passwords in URLs
)
REDACTED = "***"


def redact(text: str) -> str:
    """Mask substrings that look like credentials."""
    for pattern in _SECRET_PATTERNS:
        if pattern.groups == 2:
            text = pattern.sub(rf"\g<1>{REDACTED}\g<2>", text)
        elif pattern.groups == 1:
            text = pattern.sub(rf"\g<1>{REDACTED}", text)
        else:
            text = pattern.sub(REDACTED, text)
    return text


class ContextFilter(logging.Filter):
    """Copy the current run context onto each record, unless ``extra=`` set a field."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in log_fields().items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


def _jsonable(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return redact(str(value))


class JsonFormatter(logging.Formatter):
    """One JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        for key in CONTEXT_FIELDS:
            entry[key] = getattr(record, key, None)
        for key, value in vars(record).items():
            if key not in _RECORD_ATTRS and key not in entry:
                entry[key] = _jsonable(value)
        if record.exc_info:
            entry["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Readable lines for a terminal, still redacted and still carrying the run id."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s [run=%(run_id)s agent=%(agent)s] %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


_HANDLER_NAME = "sid_trading_firm"


def configure_logging(level: str = "INFO", fmt: str = "json", stream=None) -> logging.Handler:
    """Install the SID handler on the root logger, replacing a previous one.

    Idempotent; other handlers (a CLI's, pytest's) are left alone.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        if handler.get_name() == _HANDLER_NAME:
            root.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.set_name(_HANDLER_NAME)
    handler.addFilter(ContextFilter())
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    return handler
