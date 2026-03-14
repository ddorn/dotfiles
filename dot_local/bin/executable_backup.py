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

from functools import cached_property, cache
import os
import socket
import json
from pathlib import Path
import subprocess
import datetime
import sys
from typing import Self, Sequence
import shlex

import typer
from rich.spinner import Spinner
from rich.live import Live
from rich import print as rprint
from rich.table import Table
from rich.prompt import Confirm
from pydantic import BaseModel
import yaml


app = typer.Typer(no_args_is_help=True, add_completion=False)

CONFIG_DIR = Path("/home/diego/.config/restic")
CONFIG_FILE = CONFIG_DIR / "backupcfg.yaml"
SCRIPT_FILE = Path.home() / ".local" / "bin" / "backup"
EXCLUDE_FILE = CONFIG_DIR / "exclude"
SYSTEMD_SERVICE = CONFIG_DIR / "backup.service"
SYSTEMD_TIMER = CONFIG_DIR / "backup.timer"
EXPLICITLY_INSTALLED_PACKAGES_FILE = CONFIG_DIR / "explicitly_installed_packages.txt"

DATA_DIR = Path.home() / ".cache" / "backups"
LAST_DIRS_FOLDER = DATA_DIR / "last_big_dirs"
LAST_BIG_DIR_FORMAT = "%Y-%m-%d_%H_%M_%S.json"
DONT_ASK_FOR_BACKUP_FILE = DATA_DIR / "dont_ask_for_backup_until"


# Those are sent over to the remote machine when deploying
ALL_CODE_FILES = [
    CONFIG_FILE,
    SCRIPT_FILE,
    EXCLUDE_FILE,
    SYSTEMD_SERVICE,
    SYSTEMD_TIMER,
]


DRY_RUN = False
VERBOSE = False


class BackupConfig(BaseModel):

    class RemoteConfig(BaseModel):
        url: str
        """URL of the restic repository, passed to restic -r"""
        quota: str
        """Command that prints quota information for the remote."""

    remotes: dict[str, RemoteConfig]
    """All available remotes, with arbitrary names"""

    class MachineConfig(BaseModel):
        directories_to_backup: list[str]
        """Which folders on the machine to backup"""
        remotes: list[str]
        """Names of the remotes to backup the directories"""

    machines: dict[str, MachineConfig]
    """Configuration for each machine"""

    @cached_property
    def current_machine(self) -> MachineConfig:
        hostname = socket.gethostname()
        return self.machines[hostname]

    @classmethod
    @cache
    def read(cls) -> Self:
        return cls.model_validate(yaml.safe_load(CONFIG_FILE.read_text()))

    def get_remote(self, name: str) -> RemoteConfig:
        try:
            return self.remotes[name]
        except KeyError:
            valid_remotes = ", ".join(self.remotes.keys())
            msg = f"Remote {name} not found. Valid remotes are: {valid_remotes}"
            rprint(f"[red]Critical: {msg}")
            raise ValueError(msg)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    from_: str = typer.Option(None, "--from", help="Machine to backup from."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Don't modify any file."),
    verbose: bool = False,
):
    """Backup machines (local or distant) to multiple remotes."""
    global DRY_RUN, VERBOSE
    DRY_RUN = dry_run
    VERBOSE = verbose

    if from_ is not None:
        copy_script_to(from_)
        # Then we run it remotely, inside a tmux, without the --from flag

        args = remove_cli_arg(sys.argv, "--from")
        args[0] = str(SCRIPT_FILE)

        # Create a new tmux session called backup and send the keys to type the command there.
        # This is not rebust, but it's good enough for now
        keys = shlex.join(args)
        keys = keys.replace(" ", " SPACE ") + " ENTER"
        cmd = "tmux new-session -ds backup || true && tmux send-keys -t backup " + keys

        run(["ssh", from_, cmd])
        # Replace the current process with the open tmux with the command running
        os.execvp("ssh", ["ssh", "-t", from_, "tmux", "-u", "attach", "-t", "backup"])


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

    # Perform the backup for each remote, and collect errors
    config = BackupConfig.read()
    errors = []
    for remote in config.current_machine.remotes:
        try:
            backup_to(remote)
        except Exception as e:
            rprint(f"[red]Error backing up to {remote}: {e}")
            notify(f"Error backing up to {remote}: {e}")
            errors.append((remote, e))

    # Show disk usage for each remote
    for remote in config.current_machine.remotes:
        rprint(f"[yellow]Disk usage on {remote}")
        run(config.get_remote(remote).quota.split())

    if errors:
        for remote, error in errors:
            rprint(f"[red]🚨 Critical error for {remote}: {error}")
    else:
        save_big_dirs(big_dirs)
        notify("🎉 Backups completed")


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

def save_big_dirs(big_dirs: dict[str, int]) -> Path | None:
    """Write the big directories to a file."""
    if not DRY_RUN:
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


@app.command()
def install(remove: bool = False):
    """♾  Run the backup script with systemd every day."""

    # Copy the systemd files
    user_systemd_folder = Path("/home/diego/.config/systemd/user")
    target_service = user_systemd_folder / "backup.service"
    target_timer = user_systemd_folder / "backup.timer"

    if remove:
        try:
            run(["systemctl", "--user", "disable", "--now", "backup.timer"], dry_run=DRY_RUN)
        except subprocess.CalledProcessError:
            pass
        run(["rm", target_service], dry_run=DRY_RUN)
        run(["rm", target_timer], dry_run=DRY_RUN)
    else:
        run(["mkdir", "-p", user_systemd_folder], dry_run=DRY_RUN)
        run(["ln", "-s", SYSTEMD_SERVICE, target_service], dry_run=DRY_RUN)
        run(["ln", "-s", SYSTEMD_TIMER, target_timer], dry_run=DRY_RUN)

        # Enable the timer
        run(["systemctl", "--user", "enable", "--now", "backup.timer"], dry_run=DRY_RUN)
        run(["systemctl", "--user", "status", "backup.timer"], dry_run=DRY_RUN)
    rprint("✅ Installed systemd timer")


@app.command()
def backup_to(remote: str):
    """Backup to a given remote."""

    print(f"Backing up to {remote}")

    save_explicitly_installed_packages()

    config = BackupConfig.read()
    directories_to_backup = config.current_machine.directories_to_backup

    dry_run_arg = ["--dry-run"] if DRY_RUN else []
    call_restic(
        remote,
        "backup",
        "--exclude-file",
        EXCLUDE_FILE,
        # "--exclude-larger-than", "500M",
        "--verbose",
        *dry_run_arg,
        *directories_to_backup,
    )

    # If monday, check integrity
    if datetime.datetime.now().weekday() == 0 and not DRY_RUN:
        rprint("[yellow]Checking integrity")
        call_restic(remote, "check")
    else:
        rprint("[yellow]Skipping integrity check (not monday)")


@app.command()
def forget(remote: str):
    """Forget snapshots from a remote. --verbose and --dry-run can be passed *before* "forget"."""
    args = []
    if DRY_RUN:
        args.append("--dry-run")
    if VERBOSE:
        args.append("--verbose")
    call_restic(
        remote,
        "forget",
        "--keep-last", "3",
        "--keep-daily", "8",
        "--keep-weekly", "5",
        "--keep-monthly", "18",
        "--keep-yearly", "1000",
        *args,
    )


@app.command()
def env(remote: str):
    """Print the environment variables for a remote."""
    config = BackupConfig.read()
    remote_url = config.get_remote(remote).url
    print(f"export RESTIC_REPOSITORY={remote_url}")
    print(f"export RESTIC_PASSWORD={get_restic_password()}")


def get_list_of_big_directories(threshold: str = "50M") -> dict[str, int]:
    """Get a list directories larger than the threshold in the directories to backup."""

    dirs_to_backup = BackupConfig.read().current_machine.directories_to_backup

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
                *BackupConfig.read().current_machine.directories_to_backup,
            ]
        )

    big_directories = {}
    for line in out.splitlines():
        size, path = line.split("\t")
        big_directories[path] = int(size) * 1024

    return big_directories


def save_explicitly_installed_packages():
    """Save a list of explicitly installed packages to CONFIG_DIR."""
    try:
        out = check_output(["pacman", "-Qe"])
        if not DRY_RUN:
            EXPLICITLY_INSTALLED_PACKAGES_FILE.write_text(out)
        if VERBOSE:
            rprint(f"[green]Saved {len(out.splitlines())} explicitly installed packages to {EXPLICITLY_INSTALLED_PACKAGES_FILE}")
    except subprocess.CalledProcessError as e:
        rprint(f"[yellow]Warning: Could not get explicitly installed packages: {e}")


@cache
def get_restic_password() -> str:
    """Fetch the restic password from the environment or Bitwarden."""
    if password := os.environ.get("RESTIC_PASSWORD"):
        return password
    rprint("[yellow]Unlocking Bitwarden...")
    session = subprocess.check_output(["bw", "unlock", "--raw"], text=True).strip()
    return subprocess.check_output(
        ["bw", "get", "password", "restic backups", "--session", session],
        text=True,
    ).strip()


def call_restic(remote: str, *args: str | Path):
    config = BackupConfig.read()
    remote_url = config.get_remote(remote).url

    env = os.environ.copy()
    env["RESTIC_PASSWORD"] = get_restic_password()

    cmd: list[str | Path] = [
        "restic",
        "-r",
        remote_url,
        *args,
    ]
    return run(cmd, env=env)


def copy_script_to(machine: str):
    """Copy the backup script to a remote machine."""

    machines = BackupConfig.read().machines
    if machine not in machines:
        valid_machines = ", ".join(machines.keys())
        rprint(f"[red]Machine {machine} not found in config. Valid machines are: {valid_machines}")
        raise typer.Exit()

    if machine == socket.gethostname():
        return


    # Send the code to the remote machine
    run(["scp", *ALL_CODE_FILES, f"{machine}:{CONFIG_DIR}"], hide_output=not VERBOSE)

    rprint(f"✅ Code synced to [yellow]{machine}[/]!")


@app.command()
def deploy():
    """Deploy the backup script to all machines."""
    config = BackupConfig.read()
    for machine in config.machines:
        copy_script_to(machine)


def run(command: Sequence[str | Path], hide_output: bool = False, dry_run: bool = False, env: dict | None = None):

    command = [str(arg) for arg in command]

    if VERBOSE:
        dry = "Dry " if dry_run else ""
        rprint(f"[grey]{dry}Running: {command}", flush=True)

    if hide_output:
        stdout = subprocess.DEVNULL
    else:
        stdout = None

    if dry_run:
        return 0
    else:
        return subprocess.check_call(command, stdout=stdout, env=env)


def check_output(command: list[str | Path]):
    if VERBOSE:
        rprint(f"[grey]Running: {' '.join(map(str, command))}", flush=True)

    return subprocess.check_output(command, text=True)


# Utilities


def notify(message: str, critical: bool = False):
    """Send a desktop notification."""
    cmd = ["notify-send", "-t", "30000", "Restic Backup", message]
    if critical:
        cmd += ["-u", "critical"]
    try:
        run(cmd)
    except Exception as e:
        rprint(f"[red]Error sending notification: {e}")


def remove_cli_arg(args: list[str], arg_name: str):
    """Remove an argument from the command line. Supports both --name value and --name=value."""
    for i, arg in enumerate(args):
        if arg.startswith(f"{arg_name}="):
            del args[i]
            return args
        if arg == arg_name:
            del args[i]
            del args[i]
            return args
    return args


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
