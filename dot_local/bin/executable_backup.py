#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "pydantic",
#     "pyyaml",
#     "rich",
#     "typer",
# ]
# ///

from functools import cache
import os
import shlex
import socket
import sys
import json
from pathlib import Path
import subprocess
import datetime
import urllib.request
from typing import Sequence

import typer
from rich.spinner import Spinner
from rich.live import Live
from rich import print as rprint
from rich.table import Table
from rich.prompt import Confirm
from pydantic import BaseModel
import yaml


app = typer.Typer(no_args_is_help=True, add_completion=False)

# Two locations, discovered rather than configured: /etc/restic for the system install
# (abuelo and brimmon, root system timers), ~/.config/restic for the per-user one (pando).
# First one with a config wins.
#
# This replaced a BACKUP_CONFIG_DIR env var set in the unit file, whose default was a
# hardcoded /home/diego/.config/restic — so a root service that lost the variable read
# diego's config instead of failing.
CONFIG_DIRS = (Path("/etc/restic"), Path.home() / ".config" / "restic")


def _find_config_dir() -> Path:
    for directory in CONFIG_DIRS:
        if (directory / "backupcfg.yaml").is_file():
            return directory
    raise SystemExit(
        "No backup config found in " + " or ".join(str(d) for d in CONFIG_DIRS)
        + ". (/etc/restic is mode 700 — if it exists, you need to be root to read it.)"
    )


CONFIG_DIR = _find_config_dir()
CONFIG_FILE = CONFIG_DIR / "backupcfg.yaml"
EXCLUDE_FILE = CONFIG_DIR / "exclude"
EXPLICITLY_INSTALLED_PACKAGES_FILE = CONFIG_DIR / "explicitly_installed_packages.txt"

DATA_DIR = Path.home() / ".cache" / "backups"
LAST_DIRS_FOLDER = DATA_DIR / "last_big_dirs"
LAST_BIG_DIR_FORMAT = "%Y-%m-%d_%H_%M_%S.json"
DONT_ASK_FOR_BACKUP_FILE = DATA_DIR / "dont_ask_for_backup_until"


VERBOSE = False


class Remote(BaseModel):
    name: str
    """Name used to select this remote on the command line"""
    url: str
    """URL of the restic repository, passed to restic -r"""
    quota: str
    """Command that prints quota information for the remote."""


class Config(BaseModel):
    """The config of the machine this script runs on. One file per machine."""

    directories: list[str]
    """Which folders on this machine to backup"""
    remotes: list[Remote]
    """Where to back them up, all of them, in order"""
    secrets_command: str
    """Shell command printing KEY=value lines: RESTIC_PASSWORD, HEALTHCHECKS_PING_KEY.

    Run once per invocation, so a single unlock covers every secret. Run with the parent's
    stdin/stderr so interactive unlock prompts still work.
    """
    notify_command: str = ""
    """Desktop notification command; the message is appended as one final argument.

    Empty on headless machines, where notifying is a no-op rather than a failure.
    """
    package_list_command: str = ""
    """Shell command listing explicitly installed packages, saved alongside the backup."""

    def remote(self, name: str) -> Remote:
        for remote in self.remotes:
            if remote.name == name:
                return remote
        valid = ", ".join(r.name for r in self.remotes)
        rprint(f"[red]Critical: remote {name} not found. Valid remotes are: {valid}")
        raise typer.Exit(1)


@cache
def config() -> Config:
    return Config.model_validate(yaml.safe_load(CONFIG_FILE.read_text()))


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, verbose: bool = False):
    """Backup this machine to multiple remotes."""
    global VERBOSE
    VERBOSE = verbose


@app.command()
def backup(yes: bool = typer.Option(False, help="Don't ask for confirmation"), if_needed: bool = False):
    """🌠 Backup to all remotes."""

    if if_needed:
        if should_skip_backup():
            if VERBOSE:
                rprint("[yellow]Skipping backup because of --if-needed")
            return
        elif not Confirm.ask("Do you want to backup now? Otherwise, it will be skipped for the next hour."):
            dont_ask_until(minutes=60)
            return
        else:
            dont_ask_until(minutes=60 * 18)

    changes, big_dirs = big_dirs_change()
    if not yes and changes and not Confirm.ask("Do you want to continue?"):
        raise typer.Abort()

    # Last question of the run, asked before anything slow begins. Leftover locks are found
    # per-remote but dealt with in one go: the whole point of a backup is being able to walk
    # away from it, so nothing may need a human again once it starts.
    if someone_is_watching():
        offer_to_unlock(*(remote.name for remote in config().remotes))

    # Only now is a backup actually happening: a snoozed or declined run pings nothing,
    # so healthchecks reports it as a missed backup rather than a successful one.
    ping_healthcheck("start")

    # Perform the backup for each remote, and collect errors
    errors = []
    for remote in config().remotes:
        try:
            backup_to(remote.name)
        except Exception as e:
            rprint(f"[red]Error backing up to {remote.name}: {e}")
            notify(f"Error backing up to {remote.name}: {e}")
            errors.append((remote.name, e))

    # Show disk usage for each remote
    for remote in config().remotes:
        rprint(f"[yellow]Disk usage on {remote.name}")
        run(shlex.split(remote.quota))

    if errors:
        for name, error in errors:
            rprint(f"[red]🚨 Critical error for {name}: {error}")
        ping_healthcheck("fail", "\n".join(f"{name}: {error}" for name, error in errors))
    else:
        save_big_dirs(big_dirs)
        notify("🎉 Backups completed")
        ping_healthcheck(body="Backed up to " + ", ".join(r.name for r in config().remotes))


def dont_ask_until(minutes: int):
    DONT_ASK_FOR_BACKUP_FILE.parent.mkdir(parents=True, exist_ok=True)
    DONT_ASK_FOR_BACKUP_FILE.write_text((datetime.datetime.now() + datetime.timedelta(minutes=minutes)).isoformat())

def should_skip_backup() -> bool:
    """Check if the backup should be skipped."""
    if DONT_ASK_FOR_BACKUP_FILE.exists():
        dont_ask_until = datetime.datetime.fromisoformat(DONT_ASK_FOR_BACKUP_FILE.read_text())
        if datetime.datetime.now() < dont_ask_until:
            return True
    return False


def get_all_last_big_dirs_files() -> dict[datetime.datetime, Path]:
    """Get all the last big directories files, with their timestamp."""
    all_files = {}
    for file in Path(LAST_DIRS_FOLDER).glob("*.json"):
        try:
            timestamp = datetime.datetime.strptime(file.name, LAST_BIG_DIR_FORMAT)
        except ValueError:
            if VERBOSE:
                rprint(f"[yellow]Skipping {file} because of invalid format")
            continue
        all_files[timestamp] = file

    return all_files

def save_big_dirs(big_dirs: dict[str, int]) -> Path:
    """Write the big directories to a file."""
    LAST_DIRS_FOLDER.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime(LAST_BIG_DIR_FORMAT)
    file = LAST_DIRS_FOLDER / timestamp
    file.write_text(json.dumps(big_dirs))
    return file

def get_last_big_dirs() -> dict[str, int]:
    """Get the last recorded big directories with their sizes."""
    all_files = get_all_last_big_dirs_files()
    if not all_files:
        return {}

    last_file = max(all_files)
    return json.loads(all_files[last_file].read_text())

@app.command()
def big_dirs_change(threshold: str = "20M"):
    """📈 See which directories are larger or smaller."""

    last_sizes = get_last_big_dirs()
    current_sizes = get_list_of_big_directories()

    # Make sure the folders are considered to have size 0 if not present
    for path in last_sizes.keys():
        current_sizes.setdefault(path, 0)

    changes = {}
    for path, current_size in current_sizes.items():
        last_size = last_sizes.get(path, 0)
        changes[path] = current_size - last_size

    # Filter the small ones
    threshold_bytes = bytes_from_pretty_size(threshold)
    changes = {path: size for path, size in changes.items() if abs(size) > threshold_bytes}

    if not changes:
        print("No significant changes")
        return {}, current_sizes

    # With rich table
    table = Table()
    table.add_column("Change", justify="right")
    table.add_column("Total")
    table.add_column("Path")
    for path, size in sorted(changes.items(), key=lambda x: x[1]):
        current_size_human = pretty_size(current_sizes[path])
        if size > 0:
            table.add_row(f"[green]+{pretty_size(size)}", current_size_human, path)
        else:
            table.add_row(f"[red]{pretty_size(size)}", current_size_human, path)
    rprint(table)

    return changes, current_sizes


@app.command()
def list_big_dirs(threshold: str = "50M", save: bool = False):
    """See biggest directories that are backed up."""
    big_directories = get_list_of_big_directories(threshold)
    for path, size in sorted(big_directories.items(), key=lambda x: x[1]):
        size_human = pretty_size(size)
        print(f"{size_human:<8} {path}")

    if save:
        file = save_big_dirs(big_directories)
        print(f"✅ Saved to {file}")


class Lock(BaseModel):
    """One entry of restic's lock list, as `restic cat lock <id>` prints it."""

    time: datetime.datetime
    hostname: str
    username: str = ""
    pid: int = 0
    exclusive: bool = False
    """Only `check`, `prune` and `forget` take an exclusive lock. `backup` shares."""


def list_locks(remote: str) -> dict[str, Lock]:
    """Every lock currently on a remote, keyed by ID."""
    ids = call_restic(remote, "list", "locks", capture=True).split()

    locks = {}
    for id in ids:
        try:
            locks[id] = Lock.model_validate_json(call_restic(remote, "cat", "lock", id, capture=True))
        except subprocess.CalledProcessError:
            # A lock that disappeared between listing and reading is one fewer problem.
            continue
    return locks


def someone_is_watching() -> bool:
    """Whether there is a person on the other end who can answer a prompt."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def offer_to_unlock(*remotes: str):
    """Show the locks across every remote at once, and offer to remove the stale ones.

    A lock outlives the process that took it whenever restic dies without cleaning up, and a
    laptop suspending mid-backup is enough to do that. Nothing notices for days: `backup`
    only ever takes a shared lock, so it steps around the debris quite happily. The weekly
    `check` is what wants an exclusive lock, so a single abandoned lock fails the check on
    every machine sharing the repo, on the same night, up to a week after the cause.

    Every remote is inspected before anything is asked, because this runs once at the start
    of a backup and then nobody is watching the terminal again. One listing, one question.

    Prompts, so callers must check `someone_is_watching()` first unless a person asked for
    this by name. A timer must never block on a prompt, and must never decide by itself
    that another machine's lock is safe to delete.
    """
    locked = {remote: locks for remote in remotes if (locks := list_locks(remote))}
    if not locked:
        rprint(f"[green]No locks on {', '.join(remotes)}")
        return

    now = datetime.datetime.now(datetime.timezone.utc)
    for remote, locks in locked.items():
        rprint(f"[yellow]{remote} has {len(locks)} lock(s):")
        for id, lock in locks.items():
            age = datetime.timedelta(seconds=int((now - lock.time).total_seconds()))
            kind = "exclusive" if lock.exclusive else "shared"
            rprint(f"  {id[:8]}  {kind:<9}  {lock.username}@{lock.hostname} (PID {lock.pid})  {age} old")

    if not Confirm.ask("Remove the stale ones?", default=True):
        return

    # Never `--remove-all`: plain `unlock` drops only what restic can argue is dead, and
    # deleting the lock of a live `prune` while it writes is how a repository gets corrupted.
    for remote in locked:
        call_restic(remote, "unlock")


@app.command()
def backup_to(remote: str):
    """Backup to a given remote."""

    print(f"Backing up to {remote}")

    save_explicitly_installed_packages()

    call_restic(
        remote,
        "backup",
        "--exclude-file",
        EXCLUDE_FILE,
        # "--exclude-larger-than", "500M",
        "--verbose",
        *config().directories,
    )

    # If monday, check integrity
    if datetime.datetime.now().weekday() == 0:
        rprint("[yellow]Checking integrity")
        call_restic(remote, "check")
    else:
        rprint("[yellow]Skipping integrity check (not monday)")


# forget and prune are deliberately separate commands, run by hand: the automated
# `backup` never expires a snapshot, so a bug here can't quietly eat history.
@app.command()
def forget(remote: str, dry_run: bool = typer.Option(False, "--dry-run", help="Don't remove anything.")):
    """Forget snapshots from a remote."""
    call_restic(
        remote,
        "forget",
        "--keep-last", "3",
        "--keep-daily", "8",
        "--keep-weekly", "5",
        "--keep-monthly", "18",
        "--keep-yearly", "1000",
        *(["--dry-run"] if dry_run else []),
        *(["--verbose"] if VERBOSE else []),
    )


@app.command()
def prune(remote: str, dry_run: bool = typer.Option(False, "--dry-run", help="Don't remove anything.")):
    """Reclaim space from forgotten snapshots on a remote."""
    call_restic(
        remote,
        "prune",
        *(["--dry-run"] if dry_run else []),
        *(["--verbose"] if VERBOSE else []),
    )


@app.command()
def unlock(remotes: list[str] = typer.Argument(None, help="Remotes to check. Default: all of them.")):
    """🔓 Show the locks on every remote and offer to remove the stale ones."""
    offer_to_unlock(*(remotes or [remote.name for remote in config().remotes]))


@app.command()
def env(remote: str):
    """Print the environment variables for a remote."""
    print(f"export RESTIC_REPOSITORY={config().remote(remote).url}")
    print(f"export RESTIC_PASSWORD={get_restic_password()}")


def get_list_of_big_directories(threshold: str = "50M") -> dict[str, int]:
    """Get a list directories larger than the threshold in the directories to backup."""

    dirs_to_backup = config().directories

    # Remove the /home/diego/ and other base dir prefix, which du doesn't want
    exclude_du_format = []
    for line in EXCLUDE_FILE.read_text().splitlines():
        for directory in dirs_to_backup:
            line = line.removeprefix(directory.rstrip("/") + "/")
        exclude_du_format.append(line)

    Path("/tmp/exclude_du_format").write_text("\n".join(exclude_du_format))

    with Live(
        Spinner("bouncingBar", text="Finding large directories..."),
        refresh_per_second=10,
    ):
        out = check_output(
            [
                "du",
                f"--threshold={threshold}",
                "--exclude-from=/tmp/exclude_du_format",
                *dirs_to_backup,
            ]
        )

    big_directories = {}
    for line in out.splitlines():
        size, path = line.split("\t")
        big_directories[path] = int(size) * 1024

    return big_directories


def save_explicitly_installed_packages():
    """Save the list of explicitly installed packages to CONFIG_DIR.

    Best-effort: this is a restore *convenience*, so it must never fail a backup.
    """
    command = config().package_list_command
    if not command:
        return

    try:
        out = subprocess.check_output(command, shell=True, text=True)
    except subprocess.CalledProcessError as e:
        rprint(f"[yellow]Warning: package_list_command failed (exit {e.returncode}), not saving the package list")
        return

    EXPLICITLY_INSTALLED_PACKAGES_FILE.write_text(out)
    if VERBOSE:
        rprint(f"[green]Saved {len(out.splitlines())} packages to {EXPLICITLY_INSTALLED_PACKAGES_FILE}")


@cache
def get_secrets() -> dict[str, str]:
    """Run secrets_command once and parse its KEY=value output.

    One invocation for every secret, so unlocking Bitwarden (or touching the YubiKey, once
    this is sops) happens a single time per run.
    """
    command = config().secrets_command
    try:
        out = subprocess.check_output(command, shell=True, text=True)
    except subprocess.CalledProcessError as e:
        rprint(f"[red]Critical: secrets_command failed (exit {e.returncode})")
        raise typer.Exit(1)

    secrets = {}
    for line in out.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            secrets[key.strip()] = value.strip()
    return secrets


def get_restic_password() -> str:
    password = get_secrets().get("RESTIC_PASSWORD")
    if not password:
        # Worth its own branch: an empty password is accepted by restic and would silently
        # create or open a *different*, unencrypted-in-practice repository.
        rprint("[red]Critical: secrets_command produced no RESTIC_PASSWORD")
        raise typer.Exit(1)
    return password


def ping_healthcheck(endpoint: str = "", body: str = ""):
    """Report backup status to healthchecks.io. Never raises: monitoring must not break backups."""
    try:
        key = get_secrets().get("HEALTHCHECKS_PING_KEY")
        if not key:
            rprint("[yellow]Warning: no HEALTHCHECKS_PING_KEY from secrets_command, not pinging healthchecks")
            return

        url = f"https://hc-ping.com/{key}/backup-{socket.gethostname()}"
        if endpoint:
            url += f"/{endpoint}"

        urllib.request.urlopen(url, data=body.encode()[:100_000], timeout=10)
    except Exception as e:
        rprint(f"[yellow]Warning: healthcheck ping failed: {e}")


def call_restic(remote: str, *args: str | Path, capture: bool = False):
    env = os.environ.copy()
    env["RESTIC_PASSWORD"] = get_restic_password()

    cmd: list[str | Path] = ["restic", "-r", config().remote(remote).url, *args]
    if capture:
        return check_output(cmd, env=env)
    return run(cmd, env=env)


def run(command: Sequence[str | Path], env: dict | None = None):
    command = [str(arg) for arg in command]

    if VERBOSE:
        rprint(f"[grey]Running: {command}", flush=True)

    return subprocess.check_call(command, env=env)


def check_output(command: list[str | Path], env: dict | None = None):
    command = [str(arg) for arg in command]

    if VERBOSE:
        rprint(f"[grey]Running: {' '.join(command)}", flush=True)

    return subprocess.check_output(command, text=True, env=env)


# Utilities


def notify(message: str):
    """Send a desktop notification, if this machine has one to send to."""
    command = config().notify_command
    if not command:
        return

    try:
        run([*shlex.split(command), message])
    except Exception as e:
        rprint(f"[red]Error sending notification: {e}")


UNITS_MAPPING = [
    (1 << 40, "T"),
    (1 << 30, "G"),
    (1 << 20, "M"),
    (1 << 10, "K"),
    (1, "B"),
]


def pretty_size(amount):
    """Get human-readable file sizes.
    simplified version of https://pypi.python.org/pypi/hurry.filesize/
    """
    if amount < 0:
        return "-" + pretty_size(-amount)
    for factor, suffix in UNITS_MAPPING:
        if amount >= factor:
            break
    amount = amount / factor

    return f"{amount:<.2f} {suffix}"


def bytes_from_pretty_size(size: str) -> int:
    size = size.upper()
    for factor, suffix in UNITS_MAPPING:
        if size.endswith(suffix):
            break
    else:
        raise ValueError("Invalid size")
    return int(float(size[: -len(suffix)]) * factor)


if __name__ == "__main__":
    app()
