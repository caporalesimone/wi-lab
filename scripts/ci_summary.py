#!/usr/bin/env python3
"""Turn test and coverage results into Markdown for the GitHub job summary.

Usage:
  python scripts/ci_summary.py junit "Backend tests" junit.xml
  python scripts/ci_summary.py karma "Frontend tests" frontend/test-results/summary.json
  python scripts/ci_summary.py coverage "Frontend coverage" frontend/coverage/coverage-summary.json

A missing or unreadable file prints a one-line note instead of failing: a summary must never
hide the real result of the step that produced it.
"""

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List

MAX_FAILURES = 20


def _failures_block(failures: List[str]) -> List[str]:
    if not failures:
        return []
    lines = ["", "**Failed tests**", ""]
    lines += [f"- `{name}`" for name in failures[:MAX_FAILURES]]
    if len(failures) > MAX_FAILURES:
        lines.append(f"- ... and {len(failures) - MAX_FAILURES} more")
    return lines


def _results_table(title: str, passed: int, failed: int, skipped: int, seconds: float,
                   failures: List[str]) -> str:
    status = "failed" if failed else "passed"
    lines = [
        f"### {title}: {status}",
        "",
        "| Passed | Failed | Skipped | Time |",
        "|-------:|-------:|--------:|-----:|",
        f"| {passed} | {failed} | {skipped} | {seconds:.1f} s |",
    ]
    return "\n".join(lines + _failures_block(failures)) + "\n"


def junit_summary(title: str, path: Path) -> str:
    """Summary of a JUnit XML file (pytest --junitxml)."""
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = failed = skipped = 0
    seconds = 0.0
    failures: List[str] = []
    for suite in suites:
        total += int(suite.get("tests", 0))
        failed += int(suite.get("failures", 0)) + int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))
        seconds += float(suite.get("time", 0))
        for case in suite.iter("testcase"):
            if case.find("failure") is not None or case.find("error") is not None:
                failures.append(f"{case.get('classname', '')}::{case.get('name', '')}")
    return _results_table(title, total - failed - skipped, failed, skipped, seconds, failures)


def karma_summary(title: str, path: Path) -> str:
    """Summary of the JSON written by the reporter in frontend/karma.conf.js."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return _results_table(
        title, data["success"], data["failed"], data["skipped"], data["durationMs"] / 1000,
        data.get("failures", []),
    )


def coverage_summary(title: str, path: Path) -> str:
    """Summary of an istanbul/karma-coverage ``json-summary`` file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    total = data["total"]
    lines = [
        f"### {title}",
        "",
        "| Statements | Branches | Functions | Lines |",
        "|-----------:|---------:|----------:|------:|",
        "| " + " | ".join(f"{total[k]['pct']}%" for k in ("statements", "branches", "functions", "lines")) + " |",
    ]
    rows = []
    for name, metrics in data.items():
        if name == "total" or metrics["lines"]["pct"] == 100:
            continue
        short = name.replace("\\", "/")
        short = short[short.index("src/"):] if "src/" in short else short
        rows.append(f"| {short} | {metrics['statements']['pct']}% | {metrics['branches']['pct']}% "
                    f"| {metrics['functions']['pct']}% | {metrics['lines']['pct']}% |")
    if rows:
        lines += ["", "Files not fully covered:", "",
                  "| File | Statements | Branches | Functions | Lines |",
                  "|------|-----------:|---------:|----------:|------:|", *rows]
    return "\n".join(lines) + "\n"


KINDS = {"junit": junit_summary, "karma": karma_summary, "coverage": coverage_summary}


def main(argv: List[str]) -> int:
    if len(argv) != 4 or argv[1] not in KINDS:
        print(__doc__, file=sys.stderr)
        return 2
    kind, title, path = argv[1], argv[2], Path(argv[3])
    try:
        print(KINDS[kind](title, path))
    except (OSError, ValueError, KeyError, ET.ParseError) as exc:
        print(f"### {title}\n\nNo results available ({type(exc).__name__}: {exc}).\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
