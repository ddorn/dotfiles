# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A [chezmoi](https://chezmoi.io)-managed dotfiles repository for Diego, targeting 3 machine roles:
- **personal-laptop** — primary dev environment, alacritty terminal, full pacman access
- **work-laptop** — no admin rights, so GUI tools and CLI tools unavailable in system packages are installed in userspace via chezmoi; uses foot terminal (alacritty not installable)
- **server** — minimal, no GUI; role exists but is not yet deployed on actual servers (pando = laptop, abuelo = home server)

The role is selected once at `chezmoi init` time via `promptStringOnce` in `.chezmoi.toml.tmpl` and stored in chezmoi's local config (not in this repo). It drives all machine-specific templating.

## Chezmoi file naming conventions

- `dot_foo` → `~/.foo`
- `private_dot_foo` → `~/.foo` with mode 600
- `executable_foo` → `~/foo` with mode 755
- `foo.tmpl` → processed as a Go template before writing
- `run_onchange_*.sh/py` → re-executed whenever the file content changes
- `run_once_*.sh` → executed only once ever

## How software gets installed

Three mechanisms, not a traditional package manager list:

1. **`.chezmoiexternal.toml`** — downloads archives/files directly into userspace. Used for: oh-my-zsh + plugins (weekly), `bw` (Bitwarden CLI, always). On work-laptop, also manages ranger, bat, and sway-launcher-desktop — because those can't be installed via pacman (no admin rights). The `gitHubLatestRelease` helper is used for bat's dynamic URL.

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

Role-based conditionals throughout:
```
{{ if eq .role "personal-laptop" -}}
{{ else if eq .role "work-laptop" -}}
{{ else if hasSuffix "laptop" .role -}}  # matches both laptops
{{ end }}
```

Key templated files: `.zshrc`, sway config (terminal selection), SSH config (personal-laptop only), rclone config, netrc, git-credentials, wakatime config.

## The backup system

`dot_local/bin/executable_backup.py` is a substantial (~550 line) standalone script that:
- Reads `dot_config/restic/backupcfg.yaml` for multi-machine/multi-remote config
- Fetches the restic password from Bitwarden at runtime (independent of chezmoi's secret cache)
- Supports remotes: rsyncnet, hetzner-storage, abuelo; different machines back up to different subsets of remotes because available storage sizes vary
- Can deploy itself to remote machines via SCP
- Manages its own cron/systemd timer installation

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

- **Sway auto-launches** from `.zshrc` when on tty1 and role is laptop. Don't add terminal emulator startup logic elsewhere.
- **ranger and bat are on both machines**, but installed differently. On personal-laptop they come from pacman. On work-laptop (no admin rights), chezmoi downloads them into userspace via `.chezmoiexternal.toml`. The `.chezmoiignore.tmpl` excludes `~/.local/bin/ranger` on personal-laptop because that path is only needed for the tarball-based install.
- **The core work-laptop pattern**: if a tool can't be installed via pacman due to no admin rights, it goes into `.chezmoiexternal.toml` as a file/archive download to `~/.local/bin`.
- **`.chezmoidata.toml` in root** looks like config but is a runtime-generated secrets cache. Do not add permanent config there.
