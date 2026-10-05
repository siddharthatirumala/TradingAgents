"""Decide whether a local upstream test run may count as passing, given recorded exceptions.

usage: check_upstream_failures.py <report.jsonl> <exceptions.json> --pytest-exit-code N
           --phase PHASE --gate-records docs/PHASES.md [--platform P] [--today YYYY-MM-DD]

Fails closed. PASS only when all of the following hold; anything else is FAIL:

Session integrity
- every line is a JSON record (schema 2 of ``sid_validation_plugin``);
- exactly one ``session_start`` (the first line), exactly one ``collection_finish``
  (before any test record) and exactly one ``session_finish`` (the last line), so a
  missing, truncated or interrupted report is rejected;
- pytest's exit status, as returned to the shell, equals the recorded one and is 0
  (all passed) or 1 (tests failed); interrupted (2), internal error (3), usage error
  (4) and no tests (5) are rejected, as is a run stopped early (``-x``/``--maxfail``);
- no collection error.

Outcome accounting
- at least one test was collected and the selected test ids are unique;
- every test record belongs to a collected test, and every collected test has
  exactly one setup and one teardown record and exactly one call record unless its
  setup failed or was skipped;
- the failed reports counted here equal pytest's own failure counter (pytest 9
  counts a test with failed subtests once; older pytest-subtests counts each), and
  exit status 0 comes with no failure while 1 comes with at least one.

Exceptions
- every failed report is a test call (not setup, teardown or a subtest) whose test
  has a recorded exception that is active: same platform, not expired, owner
  approved, the validation ``--phase`` is in its ``scope.phases`` and the gate record
  that ends it (``scope.ends_at_gate``) is not yet in ``--gate-records``. An exception
  without a machine-readable scope never applies;
- the failure's evidence matches the exception's signature exactly, including
  missing or mixed evidence.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date

SCHEMA = 2
ALLOWED_EXIT = {0: "all tests passed", 1: "tests failed"}
PYTEST_EXIT = {2: "interrupted", 3: "internal error", 4: "usage error", 5: "no tests collected"}


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


def recorded_gates(path: str) -> set[str]:
    """Phase gate records present in docs/PHASES.md (headings '## Phase <id>: ...')."""
    with open(path, encoding="utf-8") as f:
        return set(re.findall(r"^## Phase (\S+?):", f.read(), flags=re.MULTILINE))


def check_session(records: list[dict], exit_code: int) -> dict:
    """Session integrity; returns the session_finish record or raises Reject."""
    if not records:
        raise Reject("report is empty")
    kinds = Counter(r["kind"] for r in records)
    for kind in ("session_start", "collection_finish", "session_finish"):
        if kinds[kind] != 1:
            raise Reject(f"expected exactly one {kind} record, found {kinds[kind]} (missing, repeated or interrupted)")
    if records[0]["kind"] != "session_start":
        raise Reject("the first record is not session_start")
    if records[-1]["kind"] != "session_finish":
        raise Reject("the last record is not session_finish (report truncated or session interrupted)")
    if records[0].get("schema") != SCHEMA:
        raise Reject(f"report schema {records[0].get('schema')!r} is not {SCHEMA}")
    first_test = next((i for i, r in enumerate(records) if r["kind"] == "test"), len(records))
    collected_at = next(i for i, r in enumerate(records) if r["kind"] == "collection_finish")
    if collected_at > first_test:
        raise Reject("test records appear before collection finished")
    unknown = set(kinds) - {"session_start", "collection_finish", "session_finish", "collect_error", "test"}
    if unknown:
        raise Reject(f"unknown record kinds {sorted(unknown)}")
    finish = records[-1]
    if finish.get("exitstatus") != exit_code:
        raise Reject(f"pytest exited with {exit_code} but the report records {finish.get('exitstatus')!r}")
    if exit_code not in ALLOWED_EXIT:
        raise Reject(f"pytest exit status {exit_code} ({PYTEST_EXIT.get(exit_code, 'unknown')})")
    if finish.get("shouldstop") or finish.get("shouldfail"):
        raise Reject("the session was stopped early (-x / --maxfail)")
    errors = [r for r in records if r["kind"] == "collect_error"]
    if errors:
        raise Reject("collection error(s): " + ", ".join(str(r.get("nodeid")) for r in errors))
    return finish


def account_outcomes(records: list[dict], finish: dict) -> tuple[dict[str, str], list[dict], dict]:
    """Per-test final outcomes and failed reports; raises Reject on any gap or excess."""
    collected = next(r for r in records if r["kind"] == "collection_finish").get("nodeids")
    if not isinstance(collected, list) or not collected:
        raise Reject("no tests were collected")
    if len(set(collected)) != len(collected):
        raise Reject("collected test ids are not unique")
    if finish.get("testscollected") != len(collected):
        raise Reject(f"pytest counted {finish.get('testscollected')} collected tests, the report lists {len(collected)}")

    tests = [r for r in records if r["kind"] == "test"]
    phases: dict[str, Counter] = defaultdict(Counter)
    by_phase: dict[tuple[str, str], dict] = {}
    subtests: dict[str, list[dict]] = defaultdict(list)
    wanted = set(collected)
    for r in tests:
        nodeid, when = r.get("nodeid"), r.get("when")
        if nodeid not in wanted:
            raise Reject(f"a test record belongs to {nodeid!r}, which was not collected")
        if r.get("outcome") not in ("passed", "failed", "skipped"):
            raise Reject(f"{nodeid}: unknown outcome {r.get('outcome')!r}")
        if r.get("subtest"):
            if when != "call":
                raise Reject(f"{nodeid}: subtest record outside the call phase")
            subtests[nodeid].append(r)
            continue
        if when not in ("setup", "call", "teardown"):
            raise Reject(f"{nodeid}: unknown phase {when!r}")
        phases[nodeid][when] += 1
        by_phase[(nodeid, when)] = r

    outcomes: dict[str, str] = {}
    for nodeid in collected:
        count = phases[nodeid]
        if count["setup"] != 1 or count["teardown"] != 1:
            raise Reject(f"{nodeid}: {count['setup']} setup and {count['teardown']} teardown record(s), expected 1 each "
                         "(test not run to completion)")
        setup = by_phase[(nodeid, "setup")]
        expect_call = 1 if setup["outcome"] == "passed" else 0
        if count["call"] != expect_call:
            raise Reject(f"{nodeid}: {count['call']} call record(s), expected {expect_call}")
        teardown = by_phase[(nodeid, "teardown")]
        if setup["outcome"] == "failed" or teardown["outcome"] == "failed":
            outcomes[nodeid] = "error"
        elif setup["outcome"] == "skipped":
            outcomes[nodeid] = "skipped"
        else:
            call = by_phase[(nodeid, "call")]
            if call["outcome"] == "failed" or any(s["outcome"] == "failed" and not s.get("xfail")
                                                   for s in subtests[nodeid]):
                outcomes[nodeid] = "failed"
            elif call["outcome"] == "skipped":
                outcomes[nodeid] = "xfailed" if call.get("xfail") else "skipped"
            else:
                outcomes[nodeid] = "xpassed" if call.get("xfail") else "passed"

    failed_reports = [r for r in tests if r["outcome"] == "failed" and not r.get("xfail")]
    # pytest 9 counts a test whose subtest failed once (its own call report), not each
    # failed subtest; the pytest-subtests plugin on older pytest counts both. Either
    # count is derived from the same records, so a lost or extra record breaks both.
    top_level = [r for r in failed_reports if not r.get("subtest")]
    if finish.get("testsfailed") not in (len(top_level), len(failed_reports)):
        raise Reject(f"pytest counted {finish.get('testsfailed')} failed report(s), the report holds "
                     f"{len(top_level)} ({len(failed_reports)} with subtests)")
    if finish["exitstatus"] == 0 and failed_reports:
        raise Reject("exit status 0 but failed reports are present")
    if finish["exitstatus"] == 1 and not top_level:
        raise Reject("exit status 1 but no failed report is present")
    summary = Counter(outcomes.values())
    summary["subtests"] = sum(len(v) for v in subtests.values())
    return outcomes, failed_reports, summary


def match_signature(failure: dict, exception: dict) -> str:
    """The reason the failure matches, or raise Reject."""
    sig = exception["signature"]
    if failure.get("subtest"):
        raise Reject("failed in a subtest; exceptions cover test calls only")
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


def exception_active(exception: dict, platform: str, today: date, phase: str, gates: set[str]) -> None:
    if exception["platform"] != platform:
        raise Reject(f"exception {exception['id']} applies to {exception['platform']}, not {platform}")
    if today > date.fromisoformat(exception["expires"]):
        raise Reject(f"exception {exception['id']} expired on {exception['expires']}")
    if exception.get("owner_approval", {}).get("status") != "approved":
        raise Reject(f"exception {exception['id']} lacks owner approval")
    scope = exception.get("scope")
    if not isinstance(scope, dict) or not isinstance(scope.get("phases"), list) or not scope.get("ends_at_gate"):
        raise Reject(f"exception {exception['id']} has no machine-readable scope (phases, ends_at_gate)")
    if phase not in scope["phases"]:
        raise Reject(f"exception {exception['id']} applies to phase(s) {scope['phases']}, not {phase!r}")
    if scope["ends_at_gate"] in gates:
        raise Reject(f"exception {exception['id']} ended at the Phase {scope['ends_at_gate']} gate record")


def check(report_path: str, exceptions_path: str, *, exit_code: int, phase: str, gate_records: str,
          platform: str, today: date) -> tuple[bool, list[str]]:
    try:
        records = load_report(report_path)
        finish = check_session(records, exit_code)
        outcomes, failed_reports, summary = account_outcomes(records, finish)
        gates = recorded_gates(gate_records)
        with open(exceptions_path, encoding="utf-8") as f:
            exceptions = {e["nodeid"]: e for e in json.load(f)["exceptions"]}
    except (OSError, ValueError, KeyError, Reject) as exc:
        return False, [f"REJECTED report: {exc}", "RESULT: FAIL"]

    lines: list[str] = []
    ok = True
    for failure in failed_reports:
        nodeid = failure.get("nodeid")
        exception = exceptions.get(nodeid)
        try:
            if exception is None:
                raise Reject("no recorded exception for this test")
            exception_active(exception, platform, today, phase, gates)
            reason = match_signature(failure, exception)
            lines.append(f"ACCEPTED {nodeid}: exception {exception['id']} ({reason})")
        except Reject as exc:
            ok = False
            lines.append(f"REJECTED {nodeid} ({failure.get('when')}): {exc}")
    lines.append("tests collected={} passed={} failed={} errors={} skipped={} xfailed={} xpassed={} subtests={}".format(
        len(outcomes), summary["passed"], summary["failed"], summary["error"], summary["skipped"],
        summary["xfailed"], summary["xpassed"], summary["subtests"]))
    lines.append(f"pytest exit status {exit_code} ({ALLOWED_EXIT[exit_code]}); phase {phase}")
    lines.append(f"RESULT: {'PASS' if ok else 'FAIL'}")
    return ok, lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report")
    parser.add_argument("exceptions")
    parser.add_argument("--pytest-exit-code", type=int, required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--gate-records", required=True)
    parser.add_argument("--platform", default=sys.platform)
    parser.add_argument("--today", default=date.today().isoformat())
    args = parser.parse_args(argv)
    ok, lines = check(args.report, args.exceptions, exit_code=args.pytest_exit_code, phase=args.phase,
                      gate_records=args.gate_records, platform=args.platform, today=date.fromisoformat(args.today))
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
