"""Self-test of check_upstream_failures.py: real evidence accepted, every rejection rule exercised.

Accepted cases use unmodified reports captured on pristine upstream 1394a3f. Rejected
cases are those reports with one targeted alteration each. Exits non-zero if any case
gets the wrong verdict. Output is redacted (home path, user name).
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import tempfile
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from check_upstream_failures import check  # noqa: E402

EXC = os.path.join(HERE, "windows_exceptions.json")
EVID = os.path.join(HERE, "evidence")
TODAY = date(2026, 10, 4)
CC = "tests/test_memory_log.py::test_concurrent_writers_keep_every_decision_and_outcome"


def records(name):
    with open(os.path.join(EVID, name), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def failing(recs):
    return next(r for r in recs if r["kind"] == "test" and r["outcome"] == "failed")


def write(recs, raw_suffix=""):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
        f.write(raw_suffix)
    return path


def pick(prefix, n_errors):
    for name in sorted(os.listdir(EVID)):
        if name.startswith(prefix):
            recs = records(name)
            fail = failing(recs)
            if prefix != "pristine_cc_" or len(fail["evidence"]["errors"]) == n_errors:
                return name, recs
    raise SystemExit(f"no evidence file {prefix} with {n_errors} errors")


def mutate(recs, fn):
    recs = copy.deepcopy(recs)
    fn(failing(recs), recs)
    return recs


def main() -> int:
    cc1_name, cc1 = pick("pristine_cc_", 1)
    yf_name, yf = pick("pristine_yf_", 0)
    cases = [("A1 accepted: real concurrency failure, 1 PermissionError(13)", cc1, True, {})]
    try:
        cc2_name, cc2 = pick("pristine_cc_", 2)
        cases.append(("A2 accepted: real concurrency failure, 2 PermissionError(13)", cc2, True, {}))
    except SystemExit:
        pass
    cases.append(("A3 accepted: real yfinance home-path failure", yf, True, {}))
    combined = [r for r in cc1 if r["kind"] != "session_finish"] + [failing(yf)] + [r for r in cc1 if r["kind"] == "session_finish"]
    cases.append(("A4 accepted: both known failures in one run", combined, True, {}))

    def add_error(f, _):
        f["evidence"]["errors"].append({"type": "ValueError", "errno": None, "winerror": None, "strerror": None})

    def lose_other_writer(f, _):
        writers = f["evidence"]["per_writer"]
        complete = next(w for w, s in writers.items() if s["count"] == 12 and s["pending"] == 0)
        writers[complete]["count"] = 11

    cases += [
        ("R1 rejected: mixed errors (PermissionError + ValueError)", mutate(cc1, add_error), False, {}),
        ("R2 rejected: empty errors collection", mutate(cc1, lambda f, _: f["evidence"].update(errors=[])), False, {}),
        ("R3 rejected: errors evidence missing", mutate(cc1, lambda f, _: f.update(evidence=None)), False, {}),
        ("R4 rejected: unparseable report line", cc1, False, {"raw": "{not json\n"}),
        ("R5 rejected: a different test failed", mutate(cc1, lambda f, _: f.update(nodeid="tests/test_memory_log.py::test_other")), False, {}),
        ("R6 rejected: PermissionError with errno 32", mutate(cc1, lambda f, _: f["evidence"]["errors"][0].update(errno=32)), False, {}),
        ("R7 rejected: winerror 32 (sharing violation), not 5", mutate(cc1, lambda f, _: f["evidence"]["errors"][0].update(winerror=32)), False, {}),
        ("R8 rejected: exception expired", cc1, False, {"today": date(2026, 11, 1)}),
        ("R9 rejected: wrong platform (linux)", cc1, False, {"platform": "linux"}),
        ("R10 rejected: no tests collected", mutate(cc1, lambda f, rs: next(r for r in rs if r["kind"] == "session_finish").update(testscollected=0)), False, {}),
        ("R11 rejected: another writer's data lost", mutate(cc1, lose_other_writer), False, {}),
        ("R12 rejected: duplicate entries", mutate(cc1, lambda f, _: f["evidence"].update(duplicate_entries=1)), False, {}),
        ("R13 rejected: different failing assertion", mutate(cc1, lambda f, _: f.update(failing_statement="assert len(entries) == len(tickers) * len(dates)")), False, {}),
        ("R14 rejected: failure in setup, not the test call", mutate(cc1, lambda f, _: f.update(when="setup")), False, {}),
        ("R15 rejected: collection error", cc1 + [{"kind": "collect_error", "nodeid": "tests/test_x.py", "longrepr": "ImportError"}], False, {}),
        ("R16 rejected: truncated report (no session finish)", [r for r in cc1 if r["kind"] != "session_finish"], False, {}),
        ("R17 rejected: yfinance test failing with another statement", mutate(yf, lambda f, _: f.update(failing_statement="assert False")), False, {}),
    ]

    wrong = 0
    print(f"evidence: {cc1_name} (1 error), {yf_name}; exceptions: windows_exceptions.json; today={TODAY}")
    for title, recs, expect, opts in cases:
        path = write(recs, opts.get("raw", ""))
        try:
            ok, lines = check(path, EXC, opts.get("platform", "win32"), opts.get("today", TODAY))
        finally:
            os.unlink(path)
        verdict = "as expected" if ok == expect else "WRONG VERDICT"
        wrong += ok != expect
        print(f"\n## {title}: {'PASS' if ok else 'FAIL'} ({verdict})")
        for line in lines:
            print("   " + line)
    print(f"\nSELFTEST: {len(cases) - wrong}/{len(cases)} verdicts correct")
    return 1 if wrong else 0


def redact(text: str) -> str:
    text = re.sub(r"[A-Za-z]:\\\\?Users\\\\?[^\\\s/]+", "<HOME>", text)
    return re.sub(r"<HOME>[^/\s]+", "<HOME>", text)


if __name__ == "__main__":
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main()
    print(redact(buffer.getvalue()))
    sys.exit(code)
