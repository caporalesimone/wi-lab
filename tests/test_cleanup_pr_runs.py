"""Tests for scripts/cleanup_pr_runs.py (retention of pull request workflow runs)."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "cleanup_pr_runs.py"


@pytest.fixture(scope="module")
def cleanup():
    spec = importlib.util.spec_from_file_location("cleanup_pr_runs", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(run_id, branch, minutes_ago, status="completed"):
    created = f"2026-10-06T12:{59 - minutes_ago:02d}:00Z"
    return {"id": run_id, "head_branch": branch, "created_at": created, "status": status, "name": "CI"}


def ids(runs):
    return sorted(r["id"] for r in runs)


class TestSelection:
    def test_only_the_three_newest_runs_of_a_branch_are_kept_however_recent(self, cleanup):
        """Twenty runs pushed within the hour: only the last three survive."""
        runs = [run(i, "feat", minutes_ago=i) for i in range(1, 21)]
        assert ids(cleanup.select_for_deletion(runs, 3)) == list(range(4, 21))

    def test_three_or_fewer_runs_are_never_deleted(self, cleanup):
        runs = [run(i, "feat", minutes_ago=i) for i in range(1, 4)]
        assert cleanup.select_for_deletion(runs, 3) == []

    def test_each_branch_keeps_its_own_newest_three(self, cleanup):
        runs = [run(i, "a", i) for i in range(1, 6)] + [run(i, "b", i) for i in range(11, 16)]
        assert ids(cleanup.select_for_deletion(runs, 3)) == [4, 5, 14, 15]

    def test_runs_in_progress_are_never_deleted(self, cleanup):
        runs = [run(i, "feat", i) for i in range(1, 5)]
        runs[3] = run(4, "feat", 4, status="in_progress")
        assert cleanup.select_for_deletion(runs, 3) == []

    def test_ordering_in_the_input_does_not_matter(self, cleanup):
        runs = [run(i, "feat", i) for i in range(1, 7)]
        assert ids(cleanup.select_for_deletion(list(reversed(runs)), 3)) == [4, 5, 6]
