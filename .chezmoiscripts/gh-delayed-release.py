#!/usr/bin/env python3
"""Return the tag name of the latest non-draft, non-prerelease GitHub release
that is at least MIN_AGE_DAYS old (default 14).

Usage: gh-delayed-release.py owner/repo [--days N]

Caches results under ~/.cache/chezmoi-scripts/ with a 1-day TTL, so repeated
`chezmoi apply` runs on the same day make zero API calls.
Respects GITHUB_TOKEN if set.
"""

import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request


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
    args = parser.parse_args()

    repo = args.repo
    min_age_days = args.days
    today = datetime.date.today().isoformat()

    cache_dir = os.path.expanduser("~/.cache/chezmoi-scripts")
    cache_file = os.path.join(
        cache_dir,
        f"delayed-release-{repo.replace('/', '-')}-{min_age_days}d-{today}.txt",
    )

    tag = cached(cache_file)
    if tag:
        print(tag)
        return

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=min_age_days)
    url = f"https://api.github.com/repos/{repo}/releases?per_page=20"

    try:
        releases = github_request(url)
    except urllib.error.HTTPError as e:
        print(f"GitHub API error for {repo}: {e}", file=sys.stderr)
        sys.exit(1)

    for release in releases:
        if release["draft"] or release["prerelease"]:
            continue
        published = datetime.datetime.fromisoformat(release["published_at"].replace("Z", "+00:00"))
        if published <= cutoff:
            tag = release["tag_name"]
            write_cache(cache_file, tag)
            print(tag)
            return

    print(f"No release older than {min_age_days} days found for {repo}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
