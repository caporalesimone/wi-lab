#!/usr/bin/env python3
"""Delete old workflow runs that belong to pull requests.

For every pull-request branch, the KEEP most recent runs are always kept; any further run
older than MAX_AGE_HOURS is deleted. Only runs triggered by the ``pull_request`` event are
considered: runs on ``main``, on releases and every manual or scheduled run are never touched,
and runs still in progress are skipped.

Needs the GitHub CLI (``gh``) with a token allowed to delete runs (``actions: write``).

Usage: python scripts/cleanup_pr_runs.py [--repo OWNER/NAME] [--keep 3] [--max-age-hours 24]
                                         [--dry-run]
"""

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List


def gh(*args: str) -> str:
    return subprocess.run(
        ["gh", *args], check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def list_pr_runs(repo: str) -> List[dict]:
    out = gh("api", "--paginate", f"repos/{repo}/actions/runs?event=pull_request&per_page=100",
             "--jq", ".workflow_runs[] | {id, head_branch, created_at, status, name}")
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def select_for_deletion(runs: List[dict], keep: int, max_age: timedelta, now: datetime) -> List[dict]:
    by_branch: Dict[str, List[dict]] = defaultdict(list)
    for run in runs:
        by_branch[run["head_branch"]].append(run)
    doomed: List[dict] = []
    for branch_runs in by_branch.values():
        newest_first = sorted(branch_runs, key=lambda r: r["created_at"], reverse=True)
        for run in newest_first[keep:]:
            created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
            if run["status"] == "completed" and now - created > max_age:
                doomed.append(run)
    return doomed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo", help="OWNER/NAME (default: the current repository)")
    parser.add_argument("--keep", type=int, default=3, help="runs to keep per pull request branch")
    parser.add_argument("--max-age-hours", type=float, default=24)
    parser.add_argument("--dry-run", action="store_true", help="only report what would be deleted")
    args = parser.parse_args()

    repo = args.repo or gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner").strip()
    runs = list_pr_runs(repo)
    doomed = select_for_deletion(runs, args.keep, timedelta(hours=args.max_age_hours),
                                 datetime.now(timezone.utc))
    print(f"{repo}: {len(runs)} pull-request runs, {len(doomed)} to delete "
          f"(keeping the {args.keep} newest per branch, deleting those older than "
          f"{args.max_age_hours:g} h){' [dry run]' if args.dry_run else ''}")
    for run in doomed:
        print(f"  {'would delete' if args.dry_run else 'deleting'} run {run['id']} "
              f"({run['head_branch']}, {run['created_at']}, {run['name']})")
        if not args.dry_run:
            gh("api", "-X", "DELETE", f"repos/{repo}/actions/runs/{run['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
