# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A [chezmoi](https://chezmoi.io)-managed dotfiles repository for Diego, targeting one machine: the personal Arch laptop (pando) — alacritty terminal, full pacman access, niri as the compositor with sway as a fallback.

Configs are written for that machine directly: there is no machine-role or per-host mechanism, and no `.chezmoi.toml.tmpl`.

## Chezmoi file naming conventions

- `dot_foo` → `~/.foo`
- `private_dot_foo` → `~/.foo` with mode 600
- `executable_foo` → `~/foo` with mode 755
- `foo.tmpl` → processed as a Go template before writing
- `run_onchange_*.sh/py` → re-executed whenever the file content changes
- `run_once_*.sh` → executed only once ever

## How software gets installed

Three mechanisms, not a traditional package manager list:

1. **`.chezmoiexternal.toml`** — downloads archives/files directly into userspace. Used for: oh-my-zsh + plugins, `bw` (Bitwarden CLI), and the Lilex font. GitHub sources go through `scripts/gh-delayed-commit.py` / `scripts/gh-delayed-release.py`, which pin to content at least 2 weeks old.

2. **`.chezmoiscripts/run_onchange_install-tools.sh`** — interactive script that prompts before installing: starship, direnv, fzf, Claude Code CLI. Runs when the script content changes.

3. System package manager (paru/pacman on Arch) — assumed to be used separately; this repo doesn't manage it.

## Secrets

Secrets flow: **Bitwarden vault → `.chezmoidata.toml` → templates**

- `.chezmoiscripts/run_onchange_before_refresh-secrets.py` unlocks Bitwarden via the `bw` CLI and writes `.chezmoidata.toml` (mode 600, git-ignored via `.gitignore`).
- This script runs automatically on `chezmoi apply` when its content changes, or can be triggered manually.
- Templates access secrets via `{{ .secrets.key_name }}` (e.g., `.secrets.wandb_api_key`, `.secrets.wakatime`).
- **Never commit `.chezmoidata.toml`** — it's the secrets cache.

Secrets stored in Bitwarden: wandb API key, overleaf-git password, wakatime API key, Tigris S3 credentials, restic backup password.

## Templates

Templating is used only for secret injection and a couple of computed values. The `.tmpl` files are rclone config, netrc, git-credentials and wakatime config (all `{{ .secrets.* }}`), `.chezmoiexternal.toml` (the delayed-pin helpers), and the systemd-reload script (unit hash). Everything else — `.zshrc`, `common.sh`, the sway and niri configs, SSH config — is a plain file.

## The backup system

`dot_local/bin/executable_backup.py` is a standalone script that:
- Reads **one config file per machine** — `dot_config/restic/backupcfg.yaml` is *this* machine's (pando). The abuelo and brimmon configs belong in `prog/infra/deploy` (pyinfra), not here — drafts of them sit untracked in `dot_config/restic/other-machines/`, which chezmoi ignores, until that move happens. The script has no notion of hostnames or of machines other than the one it runs on.
- Gets every secret from a single `secrets_command` in that config, which prints `KEY=value` lines (`RESTIC_PASSWORD`, `HEALTHCHECKS_PING_KEY`). One invocation per run, so one Bitwarden unlock — or, once this moves to sops, one YubiKey touch — covers both. Independent of chezmoi's secret cache.
- Keeps everything machine-specific in the config rather than in Python: directories, remotes, `notify_command` (absent on headless machines, where notifying is a no-op), `package_list_command` (pacman vs apt-mark).
- Different machines back up to different subsets of remotes because available storage sizes vary.
- `forget` and `prune` are separate commands, run manually; the automated `backup` never expires snapshots.

The backup excludes are in `dot_config/restic/exclude` (79-line list covering caches, build dirs, VCS internals, large media).

## Applying changes

```bash
chezmoi apply          # apply all changes, runs onchange scripts if needed
chezmoi apply -v       # verbose
chezmoi apply -n       # dry run
chezmoi diff           # preview what would change
chezmoi cd             # cd into source directory (this repo)
```

To force-refresh external archives (e.g., update oh-my-zsh):
```bash
chezmoi apply -R
```

To manually refresh secrets (e.g., after rotating a Bitwarden entry):
```bash
python .chezmoiscripts/run_onchange_before_refresh-secrets.py
```

## Non-obvious things

- **niri auto-launches** from `.zshrc` (via `dot_config/shell/common.sh`) when on tty1. There is no compositor chooser: sway is only reachable by running the `start-sway` shell function from a bare tty. Don't add terminal emulator startup logic elsewhere.
- **niri must be started via `niri-session`, never bare `niri`.** Only `niri-session` sets `XDG_CURRENT_DESKTOP=niri` and pushes it into the systemd/dbus activation environment. Bare `niri` inherits a stale value (sway doesn't clear its own on exit), which makes `xdg-desktop-portal` load the wrong backend config and silently breaks file dialogs.
- **Sway leaks env markers.** `SWAYSOCK`/`I3SOCK` survive a sway session, and tools gate on them (e.g. oh-my-zsh's `bgnotify` shells out to `swaymsg` every prompt). niri's config unsets them for everything it spawns; the tty1 chooser also clears them (and clears `NIRI_SOCKET` when choosing sway).
- **Electron apps need three different Wayland mechanisms.** System-electron apps (Obsidian) read `~/.config/electron-flags.conf`; Marvin honours the `ELECTRON_OZONE_PLATFORM_HINT` env var set in niri's `environment` block; Beeper's older bundled Electron ignores both and needs an explicit `--ozone-platform=wayland` flag (hence the local `.desktop` override). `--ozone-platform-hint=auto` does *not* reliably pick Wayland.
- **`.chezmoidata.toml` in root** looks like config but is a runtime-generated secrets cache. Do not add permanent config there.
