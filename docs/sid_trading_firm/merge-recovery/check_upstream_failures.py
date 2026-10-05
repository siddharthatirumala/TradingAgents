"""Decide whether a local upstream test run may count as passing, given recorded exceptions.

usage: check_upstream_failures.py <report.jsonl> <exceptions.json> [--platform P] [--today YYYY-MM-DD]

PASS only when the report is complete and parseable and every failed test matches
an exception that is active (same platform, not expired, owner-approved) and whose
evidence matches its signature exactly. Everything else is FAIL:

- an unparseable line, a missing session start/finish, no tests collected
- any collection error
- a failure with no exception, or with an inactive exception
- an exception whose signature or evidence does not match, including missing or
  mixed evidence
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date


class Reject(Exception):
    pass


def load_report(path: str) -> list[dict]:
    records = []
    with open(path, encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise Reject(f"report line {number} is not valid JSON ({exc.msg})") from None
            if not isinstance(record, dict) or "kind" not in record:
                raise Reject(f"report line {number} has no record kind")
            records.append(record)
    return records


def match_signature(failure: dict, exception: dict) -> str:
    """The reason the failure matches, or raise Reject."""
    sig = exception["signature"]
    if failure.get("when") != "call":
        raise Reject(f"failed in '{failure.get('when')}', not in the test call")
    if failure.get("exc_type") != sig["exc_type"]:
        raise Reject(f"exception type {failure.get('exc_type')!r} != {sig['exc_type']!r}")
    if failure.get("failing_statement") != sig["failing_statement"]:
        raise Reject(f"failing statement {failure.get('failing_statement')!r} != {sig['failing_statement']!r}")

    if sig["matcher"] == "statement_only":
        return f"{sig['exc_type']} at `{sig['failing_statement']}`"

    if sig["matcher"] == "exclusive_error_collection":
        evidence = failure.get("evidence")
        if not isinstance(evidence, dict) or "errors" not in evidence:
            raise Reject("evidence missing: the test's `errors` collection was not captured")
        errors = evidence["errors"]
        if not isinstance(errors, list) or not errors:
            raise Reject("evidence empty: the `errors` collection has no items")
        want = sig["each_error"]
        for i, err in enumerate(errors):
            if not isinstance(err, dict):
                raise Reject(f"evidence unparseable: error {i} is not a record")
            for key, value in want.items():
                if err.get(key) != value:
                    raise Reject(f"error {i} has {key}={err.get(key)!r}, required {value!r} (mixed evidence)")
        integrity = sig.get("writer_integrity")
        detail = ""
        if integrity:
            detail = "; " + check_writer_integrity(evidence, integrity, len(errors))
        return f"{len(errors)} collected error(s), all {want}{detail}"

    raise Reject(f"unknown matcher {sig['matcher']!r}")


def check_writer_integrity(evidence: dict, integrity: dict, aborted: int) -> str:
    """Only the writers that raised may be incomplete; every other write must be present and settled."""
    per_writer = evidence.get("per_writer")
    if not isinstance(per_writer, dict):
        raise Reject("evidence missing: per-writer entry counts were not captured")
    if evidence.get("duplicate_entries") != 0:
        raise Reject(f"data integrity: {evidence.get('duplicate_entries')} duplicate entries")
    writers, each = integrity["writers"], integrity["entries_per_writer"]
    if len(per_writer) > writers:
        raise Reject(f"data integrity: {len(per_writer)} writers found, at most {writers} expected")
    complete = [w for w, s in per_writer.items() if s["count"] == each and s["pending"] == 0]
    incomplete = {w: s for w, s in per_writer.items() if w not in complete}
    missing_writers = writers - len(per_writer)   # a writer that raised before its first entry
    if any(s["count"] > each for s in incomplete.values()):
        raise Reject("data integrity: a writer has more entries than it wrote")
    if any(s["pending"] > 1 for s in incomplete.values()):
        raise Reject("data integrity: an incomplete writer has more than one unsettled entry")
    if len(incomplete) + missing_writers > aborted:
        raise Reject(f"data integrity: {len(incomplete) + missing_writers} writer(s) incomplete but only "
                     f"{aborted} raised; another writer's data was lost")
    return (f"{len(complete)}/{writers} writers complete, {len(incomplete) + missing_writers} incomplete "
            f"= the {aborted} that raised, no duplicates")


def exception_active(exception: dict, platform: str, today: date) -> None:
    if exception["platform"] != platform:
        raise Reject(f"exception {exception['id']} applies to {exception['platform']}, not {platform}")
    if today > date.fromisoformat(exception["expires"]):
        raise Reject(f"exception {exception['id']} expired on {exception['expires']}")
    if exception.get("owner_approval", {}).get("status") != "approved":
        raise Reject(f"exception {exception['id']} lacks owner approval")


def check(report_path: str, exceptions_path: str, platform: str, today: date) -> tuple[bool, list[str]]:
    lines: list[str] = []
    try:
        records = load_report(report_path)
    except (OSError, Reject) as exc:
        return False, [f"REJECTED report: {exc}"]
    kinds = [r["kind"] for r in records]
    if "session_start" not in kinds or "session_finish" not in kinds:
        return False, ["REJECTED report: incomplete (session start or finish missing)"]
    finish = next(r for r in records if r["kind"] == "session_finish")
    if not finish.get("testscollected"):
        return False, ["REJECTED report: no tests were collected"]
    collect_errors = [r for r in records if r["kind"] == "collect_error"]
    if collect_errors:
        return False, [f"REJECTED collection error: {r.get('nodeid')}" for r in collect_errors]

    with open(exceptions_path, encoding="utf-8") as f:
        exceptions = {e["nodeid"]: e for e in json.load(f)["exceptions"]}

    tests = [r for r in records if r["kind"] == "test"]
    failures = [r for r in tests if r.get("outcome") == "failed"]
    passed = sum(1 for r in tests if r.get("outcome") == "passed" and r.get("when") == "call")
    ok = True
    for failure in failures:
        nodeid = failure.get("nodeid")
        exception = exceptions.get(nodeid)
        try:
            if exception is None:
                raise Reject("no recorded exception for this test")
            exception_active(exception, platform, today)
            reason = match_signature(failure, exception)
            lines.append(f"ACCEPTED {nodeid}: exception {exception['id']} ({reason})")
        except Reject as exc:
            ok = False
            lines.append(f"REJECTED {nodeid}: {exc}")
    lines.append(f"tests collected={finish.get('testscollected')} passed={passed} failed={len(failures)}")
    lines.append(f"RESULT: {'PASS' if ok else 'FAIL'}")
    return ok, lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    parser.add_argument("exceptions")
    parser.add_argument("--platform", default=sys.platform)
    parser.add_argument("--today", default=date.today().isoformat())
    args = parser.parse_args(argv)
    ok, lines = check(args.report, args.exceptions, args.platform, date.fromisoformat(args.today))
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
