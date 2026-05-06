#!/usr/bin/env python3
"""Return the SHA of the latest commit on a branch that predates the
last Tuesday which was at least MIN_DAYS ago (default 14).

That anchor date shifts by exactly one week every Tuesday, so the resolved
SHA is stable for a full week and updates automatically without manual bumps.

Usage: gh-delayed-commit.py owner/repo [--days N] [--branch BRANCH]

Caches results under ~/.cache/chezmoi-scripts/ keyed by repo + cutoff date,
so repeated `chezmoi apply` runs within the same week make zero API calls.
Respects GITHUB_TOKEN if set.
"""

import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request


def cutoff_date(min_days: int) -> datetime.date:
    """Last Tuesday that is >= min_days ago."""
    base = datetime.date.today() - datetime.timedelta(days=min_days)
    # base.weekday(): 0=Mon, 1=Tue, ..., 6=Sun
    days_since_tuesday = (base.weekday() - 1) % 7
    return base - datetime.timedelta(days=days_since_tuesday)


def cached(cache_file: str) -> str | None:
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            return f.read().strip()
    return None


def write_cache(cache_file: str, value: str) -> None:
    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
    with open(cache_file, "w") as f:
        f.write(value)


def github_request(url: str) -> object:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "chezmoi-helper"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", help="owner/repo")
    parser.add_argument("--days", type=int, default=14, help="minimum age in days (default: 14)")
    parser.add_argument("--branch", default="master", help="branch to query (default: master)")
    args = parser.parse_args()

    repo = args.repo
    branch = args.branch
    cutoff = cutoff_date(args.days)

    cache_dir = os.path.expanduser("~/.cache/chezmoi-scripts")
    cache_file = os.path.join(
        cache_dir,
        f"delayed-commit-{repo.replace('/', '-')}-{branch}-{args.days}d-{cutoff.isoformat()}.txt",
    )

    sha = cached(cache_file)
    if sha:
        print(sha)
        return

    until = cutoff.isoformat() + "T23:59:59Z"
    url = f"https://api.github.com/repos/{repo}/commits?sha={branch}&until={until}&per_page=1"

    try:
        commits = github_request(url)
    except urllib.error.HTTPError as e:
        print(f"GitHub API error for {repo}: {e}", file=sys.stderr)
        sys.exit(1)

    if not commits:
        print(f"No commits found before {cutoff} in {repo}@{branch}", file=sys.stderr)
        sys.exit(1)

    sha = commits[0]["sha"]
    write_cache(cache_file, sha)
    print(sha)


if __name__ == "__main__":
    main()
