"""Credential masking for everything written to the database.

Diagnostic text reaches the database from many places: a run's error, its
summary, audit messages and payloads, a failed model call's error message. Any
of them can carry a credential (a connection error quoting a DSN with its
password, an HTTP error echoing an Authorization header). Every value is passed
through :func:`sanitize` before it is written, so a credential never lands in a
research table, whoever produced the text.

Rules:
- strings: any credential-named key followed by ``=`` or ``:`` and a value, with
  the key bare or quoted and the value bare or quoted (``password='x'``,
  ``apikey="x"``, ``"token": "x"``, stringified JSON and Python dicts, escaped
  quotes inside the value); ``Authorization`` values including their scheme
  (``Basic``/``Bearer``/...); the user-info part of any URL; then the logging
  redaction patterns (provider keys, bearer tokens, AWS key ids);
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

# A key that names a credential: the word itself or any key ending in it
# (access_token, client_secret, db_password, x-api-key). "input_tokens" does not
# end in "token", so usage counters are left alone.
_KEY = r"[A-Za-z0-9_\-]*(?:api[_-]?key|token|secret|password|passwd|passphrase|pwd|credentials?|cookie|dsn)"
# key=value, key: value, 'key': 'value', "key": "value", key = "va lue" - the key
# optionally quoted (JSON, Python reprs), the value quoted (either quote, escapes
# allowed) or a bare run of non-delimiter characters.
_PAIR = re.compile(
    r"(?i)(?P<lead>(?P<kq>[\"']?)\b" + _KEY + r"(?P=kq)\s*[=:]\s*)"
    r"(?:(?P<vq>[\"'])(?:\\.|(?!(?P=vq)).)*(?P=vq)|[^\s,;&\"'}\])]+)"
)
# Authorization headers carry "<scheme> <credentials>": mask both words.
_AUTHORIZATION = re.compile(
    r"(?i)(?P<lead>(?P<kq>[\"']?)\b(?:proxy-)?authorization(?P=kq)\s*[=:]\s*(?P<vq>[\"']?))"
    r"(?:(?:basic|bearer|digest|token|negotiate|ntlm)\s+)?[^\s\"',;}\]]+"
)
# scheme://user:password@host  and  scheme://token@host
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s@]+@")


def _mask_pair(match: re.Match) -> str:
    quote = match.group("vq") or ""
    return f"{match.group('lead')}{quote}{REDACTED}{quote}"


def _mask_authorization(match: re.Match) -> str:
    # The opening quote is part of the lead; the closing quote is left in the text.
    return f"{match.group('lead')}{REDACTED}"


def is_sensitive_key(key: object) -> bool:
    name = str(key).strip().lower()
    return name in _SENSITIVE_KEYS or name.endswith(_SENSITIVE_SUFFIXES)


def sanitize_text(text: str) -> str:
    text = _AUTHORIZATION.sub(_mask_authorization, text)
    text = _PAIR.sub(_mask_pair, text)
    text = _URL_USERINFO.sub(rf"\g<1>{REDACTED}@", text)
    return redact(text)


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
