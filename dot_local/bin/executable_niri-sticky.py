#!/usr/bin/env python3
"""Keep a few chosen floating windows on whatever workspace is in view.

niri has no sticky windows, so this follows `niri msg event-stream` and, every
time a workspace becomes active, moves the sticky windows there. It only reacts
to workspaces on the output a window is already on: with several screens each
window stays on its screen and follows that screen's workspace switches.

Only floating windows follow: tiling one of them is how you pin it to a single
workspace.

Only one copy runs at a time (flock), so launching it from a hotkey as well as
at startup is safe.
"""

import fcntl
import json
import os
import subprocess
import sys
import tempfile

# The windows to keep in view, by the app id `niri msg windows` reports.
STICKY_APP_IDS = {"pucoti", "pucoti2"}


def niri(*args: str) -> list[dict]:
    out = subprocess.run(["niri", "msg", "--json", *args], capture_output=True, text=True)
    return json.loads(out.stdout)


def follow(workspace_id: int) -> None:
    workspaces = {w["id"]: w for w in niri("workspaces")}
    target = workspaces.get(workspace_id)
    if target is None:
        return

    for window in niri("windows"):
        if window["app_id"] not in STICKY_APP_IDS:
            continue
        if not window["is_floating"]:
            continue  # Tiled: it is a column of the workspace, let it stay there.
        current = workspaces.get(window["workspace_id"])
        if current is None or current["id"] == target["id"]:
            continue
        if current["output"] != target["output"]:
            continue  # Another screen switched workspace; leave this one alone.
        # A workspace reference is a name or an index. Names are unambiguous but
        # only exist for named workspaces, so fall back to the index — which
        # niri resolves on the output the window is on, the output we just
        # checked the target is on too.
        reference = target["name"] or str(target["idx"])
        subprocess.run(
            ["niri", "msg", "action", "move-window-to-workspace",
             "--window-id", str(window["id"]), "--focus", "false", reference],
            check=False,
        )


def main() -> None:
    lock_dir = os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir())
    lock = open(os.path.join(lock_dir, "niri-sticky.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(0)  # Another copy is already running.

    stream = subprocess.Popen(
        ["niri", "msg", "--json", "event-stream"], stdout=subprocess.PIPE, text=True
    )
    for line in stream.stdout:
        event = json.loads(line)
        if activated := event.get("WorkspaceActivated"):
            follow(activated["id"])
    sys.exit(stream.wait())


if __name__ == "__main__":
    main()
