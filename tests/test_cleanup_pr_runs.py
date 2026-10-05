"""Tests for scripts/cleanup_pr_runs.py (retention of pull request workflow runs)."""

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "cleanup_pr_runs.py"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
DAY = timedelta(hours=24)


@pytest.fixture(scope="module")
def cleanup():
    spec = importlib.util.spec_from_file_location("cleanup_pr_runs", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(run_id, branch, hours_ago, status="completed"):
    created = (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": run_id, "head_branch": branch, "created_at": created, "status": status, "name": "CI"}


def ids(runs):
    return sorted(r["id"] for r in runs)


class TestSelection:
    def test_the_three_newest_runs_of_a_branch_are_always_kept_even_when_old(self, cleanup):
        runs = [run(i, "feat", hours_ago=100 + i) for i in range(1, 4)]
        assert cleanup.select_for_deletion(runs, 3, DAY, NOW) == []

    def test_older_runs_beyond_the_newest_three_are_deleted(self, cleanup):
        runs = [run(i, "feat", hours_ago=30 + i) for i in range(1, 7)]   # 6 runs, all > 24 h
        assert ids(cleanup.select_for_deletion(runs, 3, DAY, NOW)) == [4, 5, 6]

    def test_runs_younger_than_a_day_survive_even_beyond_the_newest_three(self, cleanup):
        runs = [run(1, "feat", 1), run(2, "feat", 2), run(3, "feat", 3), run(4, "feat", 5)]
        assert cleanup.select_for_deletion(runs, 3, DAY, NOW) == []

    def test_each_branch_keeps_its_own_newest_three(self, cleanup):
        runs = [run(i, "a", 40 + i) for i in range(1, 6)] + [run(i, "b", 40 + i) for i in range(11, 16)]
        assert ids(cleanup.select_for_deletion(runs, 3, DAY, NOW)) == [4, 5, 14, 15]

    def test_runs_in_progress_are_never_deleted(self, cleanup):
        runs = [run(i, "feat", 30 + i) for i in range(1, 5)]
        runs[3] = run(4, "feat", 34, status="in_progress")
        assert cleanup.select_for_deletion(runs, 3, DAY, NOW) == []

    def test_ordering_in_the_input_does_not_matter(self, cleanup):
        runs = [run(i, "feat", 30 + i) for i in range(1, 7)]
        assert ids(cleanup.select_for_deletion(list(reversed(runs)), 3, DAY, NOW)) == [4, 5, 6]
