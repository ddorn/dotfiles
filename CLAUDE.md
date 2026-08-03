# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A [chezmoi](https://chezmoi.io)-managed dotfiles repository for Diego, targeting one machine: the personal Arch laptop (pando) — alacritty terminal, full pacman access, niri as the compositor with sway as a fallback.

Configs are written for that machine directly: there is no machine-role or per-host mechanism, and no `.chezmoi.toml.tmpl`. Rationale for individual settings lives in comments next to them, not here.

## Commands

```bash
chezmoi diff           # preview what would change
chezmoi apply          # apply, running onchange scripts if needed (-v, -n)
chezmoi apply -R       # also re-download externals (e.g. update oh-my-zsh)
chezmoi cd             # cd into the source directory (this repo)

niri validate -c dot_config/niri/config.kdl    # after editing the niri config
qs -c noctalia-shell ipc show                  # list noctalia's IPC targets
python .chezmoiscripts/run_onchange_before_refresh-secrets.py   # re-pull secrets
```

## File naming

- `dot_foo` → `~/.foo`; `private_dot_foo` adds mode 600; `executable_foo` adds 755
- `create_foo` → `~/foo`, **written only if absent and never updated afterwards**
- `foo.tmpl` → Go template. Used only for secret injection and two computed values
- `run_onchange_*` re-runs when its own content changes; `run_once_*` runs once ever

## Architecture

**Three install mechanisms**, no package list. `.chezmoiexternal.toml` pulls archives into userspace (oh-my-zsh, `bw`, Lilex) via `scripts/gh-delayed-*.py`, which pin to content ≥2 weeks old. `.chezmoiscripts/run_onchange_install-tools.sh` prompts before installing sudo-free binaries. Everything else is pacman, managed outside this repo.

**Secrets** flow Bitwarden → `.chezmoidata.toml` → `{{ .secrets.* }}`. `.chezmoidata.toml` sits in the repo root looking like config, but is a git-ignored runtime cache — never commit it, never put permanent config there. The backup system deliberately bypasses this and reads sops directly (see `dot_config/restic/backupcfg.yaml`).

**The shell layer under niri is noctalia v4** — bar, launcher, clipboard, notifications, wallpaper, OSDs, night light, tray. It is a Quickshell config, not a program: `qs -c noctalia-shell`, driven by `ipc call <target> <function>`. Do not confuse it with the `noctalia` package, which is v5: a separate binary with a `noctalia msg` CLI and a TOML config. The two share a config directory name and nothing else; the v5 setup is on the `noctalia-v5` branch. `dot_config/{waybar,swaync,copyq}` serve the sway fallback, which has no noctalia.

noctalia rewrites `~/.config/noctalia/settings.json` whenever the GUI changes anything, so chezmoi cannot hold its content and tracks it as `create_`. The tracked file is a **seed for a fresh machine, not a live description of the settings** — configure in the GUI, and only fold a value back into the seed if a rebuild should start with it. It pins `settingsVersion` on purpose: without it noctalia reads version 0 and runs every schema migration over the seeded values. (JSON takes no comments, which is why this note is here and not in the file.)

**Where to look when something breaks:**

| Symptom | File |
|---|---|
| A noctalia keybind does nothing | `dot_config/niri/config.kdl` — a renamed IPC target fails silently |
| Colours don't follow the theme | `alacritty.toml` / `config.kdl` — a colour set there beats the palette |
| An Electron app won't start on Wayland | three different mechanisms: `dot_config/electron-flags.conf`, niri's `environment` block, `dot_local/share/applications/beeper.desktop` |
| Portals / file dialogs misbehave | `dot_config/shell/common.sh` — niri must start via `niri-session` |
| Something shells out to `swaymsg` under niri | stale `SWAYSOCK`/`I3SOCK`; cleared in `common.sh` and niri's `environment` block |
