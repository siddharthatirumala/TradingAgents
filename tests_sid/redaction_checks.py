"""Credential-masking checks for every database write path, shared by SQLite and PostgreSQL tests.

All credentials here are synthetic and assembled at runtime, so the repository holds
no credential-shaped literal. Rows are read back with raw SQL, so the checks see what
was stored, not an object cached by the ORM.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import text

from sid_trading_firm.llm.budget import BudgetStopEvent
from sid_trading_firm.llm.pricing import CostStatus
from sid_trading_firm.llm.usage import LLMCallRecord
from sid_trading_firm.persistence import AuditLog, RunRepository, SqlUsageStore
from sid_trading_firm.runtime import run_context
from tests_sid.fakes import settings

PROVIDER_KEY = "sk-ant-api03-" + "Synthetic" + "0123456789abcdef"
DB_PASSWORD = "synthetic" + "-p4ssw0rd"
DSN = "postgresql+psycopg://sid:" + DB_PASSWORD + "@db.internal:5432/sid"
BEARER_VALUE = "synthetic" + "bearer0123456789"
QUERY_KEY = "AV" + "SYNTHKEY123456"
QUERY_URL = "https://www.alphavantage.co/query?function=OVERVIEW&apikey=" + QUERY_KEY
ACCESS_TOKEN = "acc" + "ess-tok-0123456789"
TOKEN_VALUE = "tok-" + "synthetic-value-77"
CLIENT_SECRET = "cs-" + "synthetic-9876"
BASIC_VALUE = "c3lu" + "dGhldGljOnVzZXI="
QUOTED_PASSWORD = "quoted" + "-synthetic-pw"

SECRETS = (PROVIDER_KEY, DB_PASSWORD, BEARER_VALUE, QUERY_KEY, ACCESS_TOKEN, TOKEN_VALUE, CLIENT_SECRET,
           BASIC_VALUE, QUOTED_PASSWORD)

# Diagnostic text in the shapes exceptions and libraries actually produce.
QUOTED_DIAGNOSTICS = [
    f"connect(host='db.internal', user='sid', password='{QUOTED_PASSWORD}')",
    f'request failed: apikey="{QUERY_KEY}" status=401',
    f"secret = '{CLIENT_SECRET}'",
    json.dumps({"password": DB_PASSWORD, "api_key": QUERY_KEY, "input_tokens": 1200, "calls": 15}),
    repr({"client_secret": CLIENT_SECRET, "access_token": ACCESS_TOKEN, "max_tokens": 8192}),
    f'{{"headers": {{"Authorization": "Bearer {BEARER_VALUE}"}}, "token": "{TOKEN_VALUE}"}}',
    f"Authorization: Basic {BASIC_VALUE}",
    'password="with \\"escaped\\" quotes ' + QUOTED_PASSWORD + '"',
]


def _stored(db, sql: str) -> str:
    """Every value the query returns, as one string, straight from the database."""
    with db.engine.connect() as connection:
        rows = connection.execute(text(sql)).all()
    return json.dumps([[str(v) for v in row] for row in rows])


def _assert_masked(stored: str) -> None:
    leaked = [s for s in SECRETS if s in stored]
    assert leaked == [], f"credentials reached the database: {len(leaked)} value(s)"
    assert "***" in stored


def _start(db):
    runs = RunRepository(db)
    with run_context(instrument="NVDA", strategy="baseline") as run:
        runs.start(run, kind="analysis", settings=settings())
    return runs, run.run_id


def check_run_error_and_summary_are_masked(db):
    runs, run_id = _start(db)
    runs.finish(
        run_id, status="failed",
        error=f"OperationalError: could not connect to {DSN}: connection refused (key {PROVIDER_KEY})",
        summary={
            "calls": 15, "input_tokens": 1200, "output_tokens": 300, "max_tokens": 8192,
            "last_error": f"HTTP 401 for {QUERY_URL}",
            "request": {"headers": {"Authorization": f"Bearer {BEARER_VALUE}", "Accept": "application/json"}},
            "steps": [{"url": f"https://user:{DB_PASSWORD}@example.com/x"}, {"token": TOKEN_VALUE},
                      f"access_token={ACCESS_TOKEN}&page=2"],
            "client_secret": {"value": CLIENT_SECRET},
        },
    )
    stored = _stored(db, f"SELECT error, summary FROM research_runs WHERE run_id = '{_uuid_literal(db, run_id)}'")
    _assert_masked(stored)
    # Context and usage figures survive.
    assert "connection refused" in stored and "db.internal" in stored
    row = runs.get(run_id)
    assert (row.summary["calls"], row.summary["input_tokens"], row.summary["max_tokens"]) == (15, 1200, 8192)
    assert row.summary["request"]["headers"]["Accept"] == "application/json"
    assert row.summary["client_secret"] == "***"


def check_audit_messages_and_nested_payloads_are_masked(db):
    _, run_id = _start(db)
    audit = AuditLog(db)
    audit.record("vendor.error", f"fetch failed: {QUERY_URL}", run_id=run_id, severity="warning",
                 payload={"dsn": DSN, "attempts": 3, "context": {"cookie": "session=abc",
                          "detail": [f"password={DB_PASSWORD}", {"api_key": QUERY_KEY}]}})
    audit.budget_stop_listener()(BudgetStopEvent(reason="ledger_unavailable", run_id=run_id, agent="cio",
                                                 detail=f"could not reach {DSN} with {PROVIDER_KEY}"))
    stored = _stored(db, "SELECT message, payload, actor FROM audit_events")
    _assert_masked(stored)
    (event, stop) = audit.for_run(run_id)
    assert event.payload["attempts"] == 3 and event.payload["dsn"] == "***"
    assert stop.payload["reason"] == "ledger_unavailable"


def check_usage_error_messages_are_masked(db):
    _, run_id = _start(db)
    now = datetime.now(UTC)
    SqlUsageStore(db).add(LLMCallRecord(
        run_id=run_id, agent="cio", provider="anthropic", model="claude-sonnet-5-5", started_at=now,
        finished_at=now, latency_ms=10.0, success=False, input_tokens=None, output_tokens=None,
        cache_read_tokens=None, cache_write_tokens=None, usage_available=False, estimated_cost_usd=None,
        cost_status=CostStatus.NO_USAGE, estimated_input_tokens=100, prompt_chars=300,
        error_type="AuthenticationError",
        error_message=f"401 invalid x-api-key {PROVIDER_KEY}; retry via {DSN}"))
    stored = _stored(db, "SELECT error_message, error_type FROM llm_usage")
    _assert_masked(stored)
    assert "AuthenticationError" in stored


def check_config_snapshot_never_holds_the_database_password(db, monkeypatch):
    monkeypatch.setenv("SID_DATABASE__URL", DSN)
    _, _run_id = _start(db)
    stored = _stored(db, "SELECT config_snapshot FROM research_runs")
    assert DB_PASSWORD not in stored


def check_numbers_and_ordinary_text_are_untouched(db):
    runs, run_id = _start(db)
    summary = {"calls": 17, "input_tokens": 167672, "cost_usd": str(Decimal("0.800384")),
               "note": "tokens: 1500, rating Overweight", "agents": ["technical_analyst", "cio"]}
    runs.finish(run_id, status="completed", summary=summary)
    assert runs.get(run_id).summary == summary


def check_quoted_and_stringified_credentials_are_masked(db):
    """password='...', apikey="...", JSON and Python-repr dictionaries in every text column."""
    runs, run_id = _start(db)
    blob = " | ".join(QUOTED_DIAGNOSTICS)
    runs.finish(run_id, status="failed", error=blob,
                summary={"last_error": blob, "attempts": QUOTED_DIAGNOSTICS, "input_tokens": 1200,
                         "output_tokens": 300, "max_tokens": 8192, "cost_usd": "0.004"})
    AuditLog(db).record("vendor.error", blob, run_id=run_id, payload={"raw": QUOTED_DIAGNOSTICS, "retries": 2})
    now = datetime.now(UTC)
    SqlUsageStore(db).add(LLMCallRecord(
        run_id=run_id, agent="cio", provider="anthropic", model="claude-sonnet-5-5", started_at=now,
        finished_at=now, latency_ms=10.0, success=False, input_tokens=None, output_tokens=None,
        cache_read_tokens=None, cache_write_tokens=None, usage_available=False, estimated_cost_usd=None,
        cost_status=CostStatus.NO_USAGE, estimated_input_tokens=100, prompt_chars=300,
        error_type="ValueError", error_message=blob))

    run_id_sql = _uuid_literal(db, run_id)
    for sql in (f"SELECT error, summary FROM research_runs WHERE run_id = '{run_id_sql}'",
                f"SELECT message, payload FROM audit_events WHERE run_id = '{run_id_sql}'",
                f"SELECT error_message FROM llm_usage WHERE run_id = '{run_id_sql}'"):
        _assert_masked(_stored(db, sql))

    # Numbers survive, both as values and inside the stringified diagnostics.
    row = runs.get(run_id)
    assert (row.summary["input_tokens"], row.summary["output_tokens"], row.summary["max_tokens"]) == (1200, 300, 8192)
    assert row.summary["cost_usd"] == "0.004"
    stored_error = _stored(db, f"SELECT error FROM research_runs WHERE run_id = '{run_id_sql}'")
    for kept in ('\\"input_tokens\\": 1200', '\\"calls\\": 15', "'max_tokens': 8192", "status=401",
                 "host='db.internal'"):
        assert kept in stored_error, kept
    audit = AuditLog(db).for_run(run_id)[0]
    assert audit.payload["retries"] == 2


def _uuid_literal(db, run_id: str) -> str:
    # SQLite stores UUIDs as 32 hex characters; PostgreSQL as a uuid.
    return run_id.replace("-", "") if db.engine.dialect.name == "sqlite" else run_id
