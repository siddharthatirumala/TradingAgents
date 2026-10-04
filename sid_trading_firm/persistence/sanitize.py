"""Credential masking for everything written to the database.

Diagnostic text reaches the database from many places: a run's error, its
summary, audit messages and payloads, a failed model call's error message. Any
of them can carry a credential (a connection error quoting a DSN with its
password, an HTTP error echoing an Authorization header). Every value is passed
through :func:`sanitize` before it is written, so a credential never lands in a
research table, whoever produced the text.

Rules:
- strings: the logging redaction patterns (provider keys, bearer tokens, AWS key
  ids, ``password=``-style pairs, passwords in URLs), plus any ``*key=``/``*token=``
  style pair and the user-info part of any URL;
- mappings: the value of a credential-bearing key is replaced whole, whatever its
  type; other values are sanitised recursively;
- lists and tuples: each item sanitised; other types unchanged.

Usage counters such as ``input_tokens`` are not credential-bearing keys and stay intact.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sid_trading_firm.observability.logging import REDACTED, redact

MAX_DEPTH = 20

# Keys whose value is a credential, matched on the whole (lower-cased) key or its suffix.
_SENSITIVE_KEYS = frozenset({
    "password", "passwd", "passphrase", "pwd", "secret", "token", "apikey", "api_key", "api-key",
    "x-api-key", "authorization", "proxy-authorization", "credential", "credentials", "cookie",
    "set-cookie", "dsn", "private_key", "access_token", "refresh_token", "id_token",
    "client_secret", "connection_string", "database_url", "session_token",
})
_SENSITIVE_SUFFIXES = ("_token", "-token", "_secret", "-secret", "_password", "-password",
                       "_passwd", "_apikey", "_api_key", "-api-key", "_credential", "_credentials")

# key=value / key: value where the key ends in a credential word (access_token=, apikey=...).
_PAIR = re.compile(
    r"(?i)([A-Za-z0-9_\-]*(?:api[_-]?key|token|secret|password|passwd|pwd|credential)\s*[=:]\s*)"
    r"([^\s,;&\"'}\]]+)"
)
# scheme://user:password@host  and  scheme://token@host
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s@]+@")


def is_sensitive_key(key: object) -> bool:
    name = str(key).strip().lower()
    return name in _SENSITIVE_KEYS or name.endswith(_SENSITIVE_SUFFIXES)


def sanitize_text(text: str) -> str:
    text = redact(text)
    text = _URL_USERINFO.sub(rf"\g<1>{REDACTED}@", text)
    return _PAIR.sub(rf"\g<1>{REDACTED}", text)


def sanitize(value: Any, _depth: int = 0) -> Any:
    """A copy of ``value`` with credentials masked (see module docstring)."""
    if _depth > MAX_DEPTH:
        return "<omitted: nested too deeply>"
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, Mapping):
        return {k: (REDACTED if is_sensitive_key(k) and v is not None else sanitize(v, _depth + 1))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v, _depth + 1) for v in value]
    return value


# Columns that hold free text or structured diagnostics, per mapped class name.
SANITIZED_COLUMNS = {
    "ResearchRun": ("error", "summary", "config_snapshot"),
    "AuditEvent": ("message", "payload", "actor"),
    "LLMUsage": ("error_message", "error_type"),
}


def sanitize_pending_rows(session, flush_context=None, instances=None) -> None:
    """SQLAlchemy ``before_flush`` hook: mask credentials in new and changed rows."""
    for obj in list(session.new) + list(session.dirty):
        for column in SANITIZED_COLUMNS.get(type(obj).__name__, ()):
            current = getattr(obj, column, None)
            if current is not None:
                cleaned = sanitize(current)
                if cleaned != current:
                    setattr(obj, column, cleaned)
