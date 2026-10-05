"""Observation-only pytest plugin for merge validation evidence.

Loaded with ``-p sid_validation_plugin`` (this directory on PYTHONPATH) and
``SID_VALIDATION_REPORT=<path>``. It changes no test behaviour: it records each
test outcome as one JSON line, and for a failure records the exception type,
message, the failing statement and, when the failing test function has a local
named ``errors`` holding exceptions, a structured description of each one taken
from the real objects (type, errno, winerror, strerror). Text parsing of pytest's
truncated output is not relied on.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

_out = None


def _write(record: dict) -> None:
    if _out is not None:
        _out.write(json.dumps(record, default=str) + "\n")
        _out.flush()


def _describe_exception(exc: BaseException) -> dict:
    return {
        "type": type(exc).__name__,
        "errno": getattr(exc, "errno", None),
        "winerror": getattr(exc, "winerror", None),
        "strerror": getattr(exc, "strerror", None),
        "repr": repr(exc)[:300],
    }


def _evidence(item, excinfo) -> tuple[dict | None, str | None]:
    """Locals evidence and failing statement from the test function's own frame."""
    test_name = getattr(item, "originalname", None) or item.name
    for entry in reversed(excinfo.traceback):
        if entry.frame.code.name != test_name:
            continue
        statement = None
        try:
            statement = str(entry.statement).strip()
        except Exception:  # noqa: BLE001 - evidence collection must never break the run
            statement = None
        evidence: dict = {}
        errors = entry.frame.f_locals.get("errors")
        if isinstance(errors, list) and all(isinstance(e, BaseException) for e in errors):
            evidence["errors"] = [_describe_exception(e) for e in errors]
        entries = entry.frame.f_locals.get("entries")
        if isinstance(entries, list):
            evidence["entries_count"] = len(entries)
            if all(isinstance(e, dict) and "ticker" in e and "date" in e for e in entries):
                per_writer: dict = {}
                seen, duplicates = set(), 0
                for e in entries:
                    key = (e["ticker"], e["date"])
                    duplicates += key in seen
                    seen.add(key)
                    stats = per_writer.setdefault(e["ticker"], {"count": 0, "pending": 0})
                    stats["count"] += 1
                    stats["pending"] += bool(e.get("pending"))
                evidence["per_writer"] = per_writer
                evidence["duplicate_entries"] = duplicates
        return evidence, statement
    return None, None


def pytest_sessionstart(session):
    global _out
    path = os.environ.get("SID_VALIDATION_REPORT")
    if path:
        _out = open(path, "w", encoding="utf-8")  # noqa: SIM115 - closed at session finish
    _write({"kind": "session_start", "platform": sys.platform, "python": sys.version.split()[0]})


def pytest_collectreport(report):
    if report.failed:
        _write({"kind": "collect_error", "nodeid": report.nodeid, "longrepr": str(report.longrepr)[:4000]})


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when != "call" and not rep.failed:
        return
    record = {"kind": "test", "nodeid": rep.nodeid, "when": rep.when, "outcome": rep.outcome}
    if rep.failed and call.excinfo is not None:
        record["exc_type"] = call.excinfo.typename
        record["exc_message"] = str(call.excinfo.value)[:2000]
        evidence, statement = _evidence(item, call.excinfo)
        record["failing_statement"] = statement
        record["evidence"] = evidence
    _write(record)


def pytest_sessionfinish(session, exitstatus):
    global _out
    _write({"kind": "session_finish", "exitstatus": int(exitstatus),
            "testscollected": session.testscollected, "testsfailed": session.testsfailed})
    if _out is not None:
        _out.close()
        _out = None
