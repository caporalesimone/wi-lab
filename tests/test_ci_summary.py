"""Tests for scripts/ci_summary.py (Markdown job summary of test and coverage results)."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ci_summary.py"

JUNIT = """<?xml version="1.0"?>
<testsuites><testsuite name="pytest" tests="4" failures="1" errors="0" skipped="1" time="2.5">
<testcase classname="tests.test_a" name="test_ok"/>
<testcase classname="tests.test_a" name="test_ok_too"/>
<testcase classname="tests.test_b" name="test_broken"><failure message="boom"/></testcase>
<testcase classname="tests.test_b" name="test_skipped"><skipped/></testcase>
</testsuite></testsuites>
"""


@pytest.fixture(scope="module")
def ci_summary():
    spec = importlib.util.spec_from_file_location("ci_summary", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_junit_counts_and_names_the_failed_tests(ci_summary, tmp_path):
    path = tmp_path / "junit.xml"
    path.write_text(JUNIT, encoding="utf-8")
    out = ci_summary.junit_summary("Backend tests", path)
    assert "### Backend tests: failed" in out
    assert "| 2 | 1 | 1 | 2.5 s |" in out
    assert "`tests.test_b::test_broken`" in out


def test_karma_summary_reports_a_clean_run(ci_summary, tmp_path):
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(
        {"success": 14, "failed": 0, "skipped": 0, "durationMs": 3100, "failures": []}
    ), encoding="utf-8")
    out = ci_summary.karma_summary("Frontend tests", path)
    assert "### Frontend tests: passed" in out and "| 14 | 0 | 0 | 3.1 s |" in out
    assert "Failed tests" not in out


def test_coverage_lists_only_files_that_are_not_fully_covered(ci_summary, tmp_path):
    def metrics(pct):
        return {k: {"pct": pct} for k in ("statements", "branches", "functions", "lines")}

    path = tmp_path / "coverage-summary.json"
    path.write_text(json.dumps({
        "total": metrics(80),
        "D:\\repo\\frontend\\src\\app\\full.ts": metrics(100),
        "D:\\repo\\frontend\\src\\app\\partial.ts": metrics(50),
    }), encoding="utf-8")
    out = ci_summary.coverage_summary("Frontend coverage", path)
    assert "| 80% | 80% | 80% | 80% |" in out
    assert "| src/app/partial.ts | 50% |" in out
    assert "full.ts" not in out


def test_a_missing_file_prints_a_note_and_does_not_fail(ci_summary, tmp_path, capsys):
    assert ci_summary.main(["ci_summary.py", "junit", "Backend tests", str(tmp_path / "nope.xml")]) == 0
    assert "No results available" in capsys.readouterr().out


def test_a_wrong_command_line_is_an_error(ci_summary):
    assert ci_summary.main(["ci_summary.py", "unknown", "t", "p"]) == 2
