#!/usr/bin/env python3
# Fetches secrets from Bitwarden and caches them in .chezmoidata.toml.
# Runs automatically on `chezmoi apply` when this file changes.
# Run manually to refresh: python3 ~/.local/share/chezmoi/.chezmoiscripts/run_onchange_before_refresh-secrets.py

import json, os, stat, subprocess

DATA_FILE = os.path.join(os.environ["CHEZMOI_SOURCE_DIR"], ".chezmoidata.toml")


def bw(*args):
    return subprocess.check_output(["bw", *args, "--session", session], text=True).strip()


def bw_item(name):
    return json.loads(bw("get", "item", name))


print("Unlocking Bitwarden...")
session = subprocess.check_output(["bw", "unlock", "--raw"], text=True).strip()

print("Fetching secrets...")
tigris = bw_item("tigris-s3-camille")

secrets = {
    "wandb_api_key":                    next(f["value"] for f in bw_item("wandb")["fields"] if f["name"] == "api_key"),
    "overleaf_git_password":            bw("get", "password", "overleaf-git"),
    "wakatime_api_key":                 bw("get", "password", "wakatime-api-key"),
    "tigris_camille_access_key_id":     tigris["login"]["username"],
    "tigris_camille_secret_access_key": tigris["login"]["password"],
}


def toml_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


print(f"Writing {DATA_FILE}...")
with open(DATA_FILE, "w") as f:
    f.write("[secrets]\n")
    for key, value in secrets.items():
        f.write(f"  {key} = {toml_str(value)}\n")

os.chmod(DATA_FILE, stat.S_IRUSR | stat.S_IWUSR)
print("Done. Run 'chezmoi apply' again to apply with fresh secrets.")
