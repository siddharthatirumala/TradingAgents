"""No credential is stored in the database: SQLite (unit) and PostgreSQL (integration, in CI)."""

import os

import pytest
from sqlalchemy import text

from sid_trading_firm.persistence import Database, make_engine
from sid_trading_firm.persistence.migrate import upgrade
from sid_trading_firm.persistence.models import Base
from sid_trading_firm.persistence.sanitize import is_sensitive_key, sanitize, sanitize_text
from tests_sid import redaction_checks as checks

PG_URL = os.environ.get("SID_TEST_DATABASE_URL")
CHECKS = [
    checks.check_run_error_and_summary_are_masked,
    checks.check_audit_messages_and_nested_payloads_are_masked,
    checks.check_usage_error_messages_are_masked,
    checks.check_numbers_and_ordinary_text_are_untouched,
    checks.check_quoted_and_stringified_credentials_are_masked,
]


@pytest.fixture
def sqlite_db():
    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    yield Database(engine)
    engine.dispose()


@pytest.fixture
def postgres_db():
    upgrade(PG_URL)
    engine = make_engine(PG_URL)
    yield Database(engine)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE audit_events, llm_usage, research_runs CASCADE"))
    engine.dispose()


# ------------------------------------------------------------------ SQLite (unit)

@pytest.mark.unit
@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__.removeprefix("check_"))
def test_sqlite(sqlite_db, check):
    check(sqlite_db)


@pytest.mark.unit
def test_sqlite_config_snapshot(sqlite_db, monkeypatch):
    checks.check_config_snapshot_never_holds_the_database_password(sqlite_db, monkeypatch)


# ------------------------------------------------------- PostgreSQL (integration)

@pytest.mark.integration
@pytest.mark.skipif(not PG_URL, reason="SID_TEST_DATABASE_URL is not set")
@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__.removeprefix("check_"))
def test_postgres(postgres_db, check):
    check(postgres_db)


@pytest.mark.integration
@pytest.mark.skipif(not PG_URL, reason="SID_TEST_DATABASE_URL is not set")
def test_postgres_config_snapshot(postgres_db, monkeypatch):
    checks.check_config_snapshot_never_holds_the_database_password(postgres_db, monkeypatch)


# --------------------------------------------------------------- the sanitiser

@pytest.mark.unit
@pytest.mark.parametrize("key, sensitive", [
    ("password", True), ("Authorization", True), ("api_key", True), ("X-API-Key", True),
    ("access_token", True), ("client_secret", True), ("db_password", True), ("dsn", True),
    ("input_tokens", False), ("output_tokens", False), ("max_tokens", False), ("tokens", False),
    ("ticker", False), ("cache_key", False), ("url", False),
])
def test_sensitive_keys(key, sensitive):
    assert is_sensitive_key(key) is sensitive


@pytest.mark.unit
def test_sanitize_masks_urls_pairs_and_keys_but_keeps_structure():
    value = {"a": ["https://u:" + "pw" + "x@h/p", ("apikey=" + "Q" * 12,)], "token": None, "n": 3}
    out = sanitize(value)
    assert out == {"a": ["https://***@h/p", ["apikey=***"]], "token": None, "n": 3}
    assert sanitize_text("plain text, input_tokens=1200") == "plain text, input_tokens=1200"


@pytest.mark.unit
def test_sanitize_bounds_deeply_nested_values():
    deep = current = {}
    for _ in range(50):
        current["next"] = {}
        current = current["next"]
    assert "omitted" in str(sanitize(deep))


QUOTED = "synth" + "-quoted-77"


@pytest.mark.unit
@pytest.mark.parametrize("raw, masked", [
    ("password='" + QUOTED + "'", "password='***'"),
    ('apikey="' + QUOTED + '"', 'apikey="***"'),
    ("secret = '" + QUOTED + "'", "secret = '***'"),
    ('"token": "' + QUOTED + '"', '"token": "***"'),
    ("{'access_token': '" + QUOTED + "', 'max_tokens': 8192}", "{'access_token': '***', 'max_tokens': 8192}"),
    ('{"password": "' + QUOTED + '", "input_tokens": 1200}', '{"password": "***", "input_tokens": 1200}'),
    ("Authorization: Basic " + QUOTED, "Authorization: ***"),
    ('"Authorization": "Bearer ' + QUOTED + '", "n": 1', '"Authorization": "***", "n": 1'),
    ('password="a \\"b\\" ' + QUOTED + '"', 'password="***"'),
    ("pwd: " + QUOTED + ", next=1", "pwd: ***, next=1"),
])
def test_quoted_and_stringified_credentials(raw, masked):
    assert sanitize_text(raw) == masked


@pytest.mark.unit
@pytest.mark.parametrize("text", [
    '{"input_tokens": 1200, "output_tokens": 300, "max_tokens": 8192}',
    "tokens: 1500, rating Overweight",
    "password reset failed for user sid",
    "{'calls': 17, 'cost_usd': '0.800384'}",
])
def test_ordinary_diagnostics_are_unchanged(text):
    assert sanitize_text(text) == text
