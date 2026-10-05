"""The merge-validation failure checker fails closed.

Reports come from real pytest runs of small synthetic suites with the observation
plugin loaded, so the checker is exercised on what the plugin actually writes. Each
rejection case is a real run of a misbehaving suite or one targeted alteration of a
real report. The checker and plugin are review tooling in
docs/sid_trading_firm/merge-recovery/, not product code.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from datetime import date
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
TOOLING = ROOT / "docs" / "sid_trading_firm" / "merge-recovery"
TODAY = date(2026, 10, 5)

_spec = importlib.util.spec_from_file_location("check_upstream_failures", TOOLING / "check_upstream_failures.py")
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)

GOOD = """
def test_one():
    assert 1 + 1 == 2

def test_two():
    assert "a" in "abc"
"""

KNOWN_FAILURE = """
def test_ok():
    assert True

def test_flaky_writer():
    errors = [PermissionError(13, "Access is denied")]
    assert errors == []
"""


def run_suite(tmp_path: Path, source: str, *args: str, name: str = "test_sample.py") -> tuple[int, Path]:
    """Run pytest on one synthetic test file with the plugin; returns (exit code, report path)."""
    suite = tmp_path / "suite"
    suite.mkdir(exist_ok=True)
    (suite / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (suite / name).write_text(textwrap.dedent(source), encoding="utf-8")
    report = tmp_path / "report.jsonl"
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
    env.update(PYTHONPATH=str(TOOLING), SID_VALIDATION_REPORT=str(report))
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "sid_validation_plugin",
         "-c", str(suite / "pytest.ini"), "--rootdir", str(suite), *args, str(suite)],
        cwd=suite, env=env, capture_output=True, text=True, timeout=120)
    return proc.returncode, report


def exception_file(tmp_path: Path, nodeid: str, **over) -> Path:
    exc = {"id": "TEST-EXC", "nodeid": nodeid, "platform": sys.platform, "expires": "2026-10-31",
           "owner_approval": {"status": "approved"},
           "scope": {"phases": ["remediation"], "ends_at_gate": "9Z"},
           "signature": {"matcher": "exclusive_error_collection", "exc_type": "AssertionError",
                         "failing_statement": "assert errors == []",
                         "each_error": {"type": "PermissionError", "errno": 13}}}
    for key, value in over.items():
        if value is None:
            exc.pop(key, None)
        else:
            exc[key] = value
    path = tmp_path / "exceptions.json"
    path.write_text(json.dumps({"exceptions": [exc]}), encoding="utf-8")
    return path


def gates(tmp_path: Path, *ids: str) -> Path:
    path = tmp_path / "PHASES.md"
    path.write_text("# Phase gate records\n\n" + "".join(f"## Phase {i}: something\n\n" for i in ids), encoding="utf-8")
    return path


def verdict(report: Path, exceptions: Path, exit_code: int, gate_file: Path, *, phase="remediation",
            platform=sys.platform, today=TODAY):
    return checker.check(str(report), str(exceptions), exit_code=exit_code, phase=phase,
                         gate_records=str(gate_file), platform=platform, today=today)


def read(report: Path) -> list[dict]:
    return [json.loads(line) for line in report.read_text(encoding="utf-8").splitlines() if line.strip()]


def write(path: Path, records: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def flaky_nodeid() -> str:
    return "test_sample.py::test_flaky_writer"


# ------------------------------------------------------------------ accepted runs

def test_a_clean_run_passes_with_complete_accounting(tmp_path):
    code, report = run_suite(tmp_path, GOOD)
    ok, lines = verdict(report, exception_file(tmp_path, "none"), code, gates(tmp_path, "0"))
    assert code == 0 and ok, lines
    assert "tests collected=2 passed=2 failed=0" in lines[-3]


def test_a_failure_matching_an_active_scoped_exception_passes(tmp_path):
    code, report = run_suite(tmp_path, KNOWN_FAILURE)
    ok, lines = verdict(report, exception_file(tmp_path, flaky_nodeid()), code, gates(tmp_path, "0", "1A"))
    assert code == 1 and ok, lines
    assert lines[0].startswith("ACCEPTED test_sample.py::test_flaky_writer")


def test_skips_xfails_and_xpasses_are_accounted(tmp_path):
    code, report = run_suite(tmp_path, """
        import pytest

        def test_pass():
            pass

        @pytest.mark.skip(reason="not here")
        def test_skip():
            pass

        @pytest.mark.xfail(reason="known")
        def test_xfail():
            assert False

        @pytest.mark.xfail(reason="lenient")
        def test_xpass():
            pass
    """)
    ok, lines = verdict(report, exception_file(tmp_path, "none"), code, gates(tmp_path))
    assert code == 0 and ok, lines
    assert "collected=4 passed=1 failed=0 errors=0 skipped=1 xfailed=1 xpassed=1" in lines[-3]


# ------------------------------------------------------------------ exception scope

@pytest.mark.parametrize("over, gate_ids, kwargs, reason", [
    ({}, ("9Z",), {}, "ended at the Phase 9Z gate record"),
    ({}, (), {"phase": "3"}, "not '3'"),
    ({"scope": None}, (), {}, "no machine-readable scope"),
    ({"scope": {"phases": ["remediation"]}}, (), {}, "no machine-readable scope"),
    ({}, (), {"today": date(2026, 11, 1)}, "expired"),
    ({}, (), {"platform": "plan9"}, "applies to"),
    ({"owner_approval": {"status": "proposed"}}, (), {}, "lacks owner approval"),
])
def test_an_exception_outside_its_scope_is_refused(tmp_path, over, gate_ids, kwargs, reason):
    code, report = run_suite(tmp_path, KNOWN_FAILURE)
    ok, lines = verdict(report, exception_file(tmp_path, flaky_nodeid(), **over), code, gates(tmp_path, *gate_ids),
                        **kwargs)
    assert not ok and reason in lines[0], lines


def test_a_failure_without_an_exception_is_refused(tmp_path):
    code, report = run_suite(tmp_path, KNOWN_FAILURE)
    ok, lines = verdict(report, exception_file(tmp_path, "test_sample.py::test_other"), code, gates(tmp_path))
    assert not ok and "no recorded exception" in lines[0]


def test_the_repository_exceptions_ended_at_the_phase_1a_gate_and_are_not_extended(tmp_path):
    """The recorded Windows exceptions applied to the Phase 1A merge recovery only."""
    real = json.loads((TOOLING / "windows_exceptions.json").read_text(encoding="utf-8"))
    yf = next(e for e in real["exceptions"] if e["id"] == "WIN-YF-CACHE-UNDER-HOME")
    assert yf["scope"] == {"phases": ["1A-merge-recovery"], "ends_at_gate": "1A"}
    assert yf["expires"] == "2026-10-31"
    with pytest.raises(checker.Reject, match="ended at the Phase 1A gate record"):
        checker.exception_active(yf, "win32", TODAY, "1A-merge-recovery",
                                 checker.recorded_gates(str(ROOT / "docs" / "PHASES.md")))
    for phase in ("2", "3", "remediation"):
        with pytest.raises(checker.Reject, match="applies to phase"):
            checker.exception_active(yf, "win32", TODAY, phase, set())
    checker.exception_active(yf, "win32", date(2026, 10, 4), "1A-merge-recovery", {"0"})   # its original scope


# ------------------------------------------------------------------ session integrity (real runs)

def test_an_interrupted_run_is_refused(tmp_path):
    code, report = run_suite(tmp_path, """
        def test_first():
            pass

        def test_interrupts():
            raise KeyboardInterrupt
    """)
    ok, lines = verdict(report, exception_file(tmp_path, "none"), code, gates(tmp_path))
    assert code == 2 and not ok and "exit status 2 (interrupted)" in lines[0]


def test_a_run_stopped_early_is_refused(tmp_path):
    code, report = run_suite(tmp_path, KNOWN_FAILURE + "\n\ndef test_after():\n    pass\n", "-x")
    ok, lines = verdict(report, exception_file(tmp_path, flaky_nodeid()), code, gates(tmp_path))
    assert code == 1 and not ok and "stopped early" in lines[0]


def test_a_collection_error_is_refused(tmp_path):
    code, report = run_suite(tmp_path, "def test_broken(:\n    pass\n")
    ok, lines = verdict(report, exception_file(tmp_path, "none"), code, gates(tmp_path))
    assert code == 2 and not ok


def test_a_run_with_no_tests_is_refused(tmp_path):
    code, report = run_suite(tmp_path, "X = 1\n")
    ok, lines = verdict(report, exception_file(tmp_path, "none"), code, gates(tmp_path))
    assert code == 5 and not ok


def test_a_setup_error_is_refused_even_with_an_exception_for_the_test(tmp_path):
    code, report = run_suite(tmp_path, """
        import pytest

        @pytest.fixture
        def broken():
            raise RuntimeError("fixture failed")

        def test_flaky_writer(broken):
            pass
    """)
    ok, lines = verdict(report, exception_file(tmp_path, flaky_nodeid()), code, gates(tmp_path))
    assert code == 1 and not ok and "(setup)" in lines[0] and "not in the test call" in lines[0]


def test_a_teardown_error_is_refused(tmp_path):
    code, report = run_suite(tmp_path, """
        import pytest

        @pytest.fixture
        def leaky():
            yield
            raise RuntimeError("teardown failed")

        def test_flaky_writer(leaky):
            pass
    """)
    ok, lines = verdict(report, exception_file(tmp_path, flaky_nodeid()), code, gates(tmp_path))
    assert code == 1 and not ok and "(teardown)" in lines[0]


def test_a_failing_subtest_is_refused(tmp_path):
    try:
        import _pytest.subtests  # noqa: F401  (pytest >= 9 ships the subtests fixture)
    except ImportError:
        pytest.importorskip("pytest_subtests")
    code, report = run_suite(tmp_path, """
        def test_flaky_writer(subtests):
            with subtests.test("inner"):
                errors = [PermissionError(13, "Access is denied")]
                assert errors == []
    """)
    ok, lines = verdict(report, exception_file(tmp_path, flaky_nodeid()), code, gates(tmp_path))
    assert code == 1 and not ok and "subtest" in "\n".join(lines)


def test_the_shell_exit_code_must_match_the_report(tmp_path):
    code, report = run_suite(tmp_path, KNOWN_FAILURE)
    ok, lines = verdict(report, exception_file(tmp_path, flaky_nodeid()), 0, gates(tmp_path))
    assert code == 1 and not ok and "pytest exited with 0 but the report records 1" in lines[0]


# ------------------------------------------------------------------ altered reports

def _altered(tmp_path, change):
    code, report = run_suite(tmp_path, KNOWN_FAILURE)
    records = read(report)
    change(records)
    return verdict(write(tmp_path / "altered.jsonl", records), exception_file(tmp_path, flaky_nodeid()), code,
                   gates(tmp_path))


def _drop(kind=None, when=None, nodeid_part=None):
    def change(records):
        for i, r in enumerate(records):
            if (kind is None or r["kind"] == kind) and (when is None or r.get("when") == when) \
                    and (nodeid_part is None or nodeid_part in r.get("nodeid", "")):
                del records[i]
                return
        raise AssertionError("nothing to drop")
    return change


def _finish(**fields):
    return lambda records: records[-1].update(fields)


@pytest.mark.parametrize("change, reason", [
    (_drop(kind="session_finish"), "exactly one session_finish"),
    (_drop(kind="session_start"), "exactly one session_start"),
    (_drop(kind="collection_finish"), "exactly one collection_finish"),
    (lambda rs: rs.insert(1, copy.deepcopy(rs[0])), "exactly one session_start"),
    (lambda rs: rs.append(copy.deepcopy(rs[0])), "exactly one session_start"),
    (lambda rs: rs.append({"kind": "test", "nodeid": "x"}), "the last record is not session_finish"),
    (_drop(kind="test", when="teardown", nodeid_part="test_ok"), "teardown record(s), expected 1"),
    (_drop(kind="test", when="call", nodeid_part="test_ok"), "call record(s), expected 1"),
    (lambda rs: rs.insert(-1, {"kind": "test", "nodeid": "test_sample.py::ghost", "when": "call",
                               "outcome": "passed"}), "was not collected"),
    (lambda rs: rs.insert(-1, {"kind": "collect_error", "nodeid": "x.py", "longrepr": "boom"}), "collection error"),
    (_finish(testsfailed=0), "failed report(s)"),
    (_finish(testscollected=5), "collected tests"),
    (_finish(shouldfail=True), "stopped early"),
    (lambda rs: rs[0].update(schema=1), "schema"),
    (lambda rs: next(r for r in rs if r["kind"] == "collection_finish").update(nodeids=[]), "no tests were collected"),
])
def test_an_altered_report_is_refused(tmp_path, change, reason):
    ok, lines = _altered(tmp_path, change)
    assert not ok and reason in lines[0], lines


def test_an_unparseable_line_is_refused(tmp_path):
    code, report = run_suite(tmp_path, GOOD)
    report.write_text(report.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
    ok, lines = verdict(report, exception_file(tmp_path, "none"), code, gates(tmp_path))
    assert not ok and "not valid JSON" in lines[0]


def test_a_missing_report_is_refused(tmp_path):
    ok, lines = verdict(tmp_path / "absent.jsonl", exception_file(tmp_path, "none"), 0, gates(tmp_path))
    assert not ok and lines[-1] == "RESULT: FAIL"


def test_exit_zero_with_a_recorded_failure_is_refused(tmp_path):
    code, report = run_suite(tmp_path, KNOWN_FAILURE)
    records = read(report)
    records[-1]["exitstatus"] = 0
    ok, lines = verdict(write(tmp_path / "altered.jsonl", records), exception_file(tmp_path, flaky_nodeid()), 0,
                        gates(tmp_path))
    assert not ok and "exit status 0 but failed reports are present" in lines[0]


@pytest.mark.parametrize("mutate, reason", [
    (lambda f: f["evidence"]["errors"].append({"type": "ValueError", "errno": None}), "mixed evidence"),
    (lambda f: f["evidence"].update(errors=[]), "evidence empty"),
    (lambda f: f.update(evidence=None), "evidence missing"),
    (lambda f: f["evidence"]["errors"][0].update(errno=32), "errno=32"),
    (lambda f: f.update(failing_statement="assert False"), "failing statement"),
    (lambda f: f.update(exc_type="ValueError"), "exception type"),
])
def test_signature_mismatches_are_refused(tmp_path, mutate, reason):
    def change(records):
        mutate(next(r for r in records if r["kind"] == "test" and r["outcome"] == "failed"))
    ok, lines = _altered(tmp_path, change)
    assert not ok and reason in lines[0], lines
