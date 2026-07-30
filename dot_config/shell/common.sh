# Shared shell config — sourced by both ~/.zshrc and ~/.bashrc
# Nothing in here should use zsh- or bash-specific syntax.

# ── PATH ─────────────────────────────────────────────────────────────────────
add_to_path() {
    if [[ -d "$1" ]] && [[ ":$PATH:" != *":$1:"* ]]; then
        PATH="${PATH:+${PATH}:}$1"
    fi
}
add_to_path "$HOME/bin"
add_to_path "$HOME/.local/bin"
add_to_path "$HOME/prog/scripts/scripts"
add_to_path "$HOME/.cargo/bin"
add_to_path "$HOME/.npm-global/bin"
export PATH

export PNPM_HOME="$HOME/.local/share/pnpm"
case ":$PATH:" in
  *":$PNPM_HOME:"*) ;;
  *) export PATH="$PNPM_HOME:$PATH" ;;
esac

# ── ENVIRONMENT ──────────────────────────────────────────────────────────────
export HOST=$(cat /etc/hostname)
export RESTIC_REPOSITORY="sftp:zh2012@zh2012.rsync.net:backups"
export EPHEMERAL_DST="$HOME/.cache/ephemeral-cache"
export FZF_DEFAULT_OPTS='--layout=reverse --border'

# ── EDITOR ───────────────────────────────────────────────────────────────────
if command -v nvim &>/dev/null; then
    export EDITOR=nvim
    alias vi=nvim vim=nvim
else
    export EDITOR=vim
fi

# ── FUNCTIONS ────────────────────────────────────────────────────────────────
unalias md 2>/dev/null
md() { mkdir -p "$1" && cd "$1"; }

compress-mp4() { ffmpeg -i "$1" -vcodec libx265 -crf 28 "compressed-$1"; }

start-sway() {
    # tty1 auto-starts niri (see STARTUP below). This is the manual escape hatch
    # for sway: run it from a bare tty (not from inside a running compositor).
    # The niri marker must go, or tools that gate on $NIRI_SOCKET misbehave.
    unset NIRI_SOCKET
    systemctl --user unset-environment NIRI_SOCKET 2>/dev/null
    export XDG_CURRENT_DESKTOP=sway XDG_SESSION_DESKTOP=sway
    exec sway
}

mirror() {
    # Mirror the focused output onto the other one. Works under both niri and
    # sway, detected via their respective IPC socket env vars.
    local focused other
    if [[ -n "$NIRI_SOCKET" ]]; then
        focused=$(niri msg --json focused-output | jq -r '.name')
        other=$(niri msg --json outputs | jq -r --arg f "$focused" 'keys[] | select(. != $f)' | head -n 1)
        if [[ -z "$other" ]]; then echo "No other output found"; return 1; fi
        wl-mirror "$focused" & disown
        sleep 0.6
        local id
        id=$(niri msg --json windows | jq -r '.[] | select(.app_id=="wl_mirror") | .id' | head -n 1)
        if [[ -z "$id" ]]; then echo "wl-mirror window not found"; return 1; fi
        niri msg action move-window-to-monitor --id "$id" "$other"
        niri msg action fullscreen-window --id "$id"
    elif [[ -n "$SWAYSOCK" ]]; then
        focused=$(swaymsg -t get_outputs | jq -r '.[] | select(.focused) | .name')
        other=$(swaymsg -t get_outputs | jq -r --arg f "$focused" '.[] | select(.name != $f) | .name' | head -n 1)
        if [[ -z "$other" ]]; then echo "No other output found"; return 1; fi
        wl-mirror "$focused" & disown
        sleep 0.5
        swaymsg "[app_id=\"wl_mirror\"]" move output "$other"
        swaymsg "[app_id=\"wl_mirror\"]" fullscreen
    else
        echo "mirror: no niri (\$NIRI_SOCKET) or sway (\$SWAYSOCK) session detected"; return 1
    fi
}

# ── ALIASES ──────────────────────────────────────────────────────────────────
alias day='date +%Y-%m-%d'
alias rm='rm -I'
alias mv='mv -i'
alias r=ranger
[[ -n $ZSH_VERSION ]] && alias '$'='true &&'
alias py=ptpython
alias tree='tree --gitignore'
alias grep='grep --color=auto --exclude-dir={.bzr,CVS,.git,.hg,.svn,.idea,.tox,.venv}'
alias ephemeral='~/prog/all/ephemeral/ephemeral | grep -v "already a symlink"'
alias receipe="python -c \"import random as r; print('Receipe p.' + str(r.choice(list(range(15, 150)) + list(range(172, 204)))))\""
alias backuplist='du -X ~/.config/restic/exclude ~ -h -t 1M | sort -h'
alias scale='swaymsg output "*" scale'
alias qwerty="swaymsg input '*' xkb_layout fr"
alias azerty="swaymsg input '*' xkb_layout us"

# ── STARTUP ──────────────────────────────────────────────────────────────────
if [[ -z $DISPLAY && "$(tty)" == /dev/tty1 ]]; then
    # Shared Wayland environment (compositor-agnostic).
    export SDL_VIDEODRIVER=wayland
    export _JAVA_AWT_WM_NONREPARENTING=1
    export QT_QPA_PLATFORM=wayland
    export MOZ_ENABLE_WAYLAND=1
    export QT_SCREEN_SCALE_FACTORS="0.66666;1"
    export ELECTRON_OZONE_PLATFORM_HINT=wayland

    # niri MUST go through niri-session so it sets up the session environment
    # (XDG_CURRENT_DESKTOP, dbus/systemd activation env) — launching bare `niri`
    # leaves stale env and breaks portals (file pickers etc.).
    # sway is no longer offered here — run `start-sway` from a tty for that.
    if command -v niri-session >/dev/null; then
        # Drop any stale sway markers: sway doesn't clean these up on exit,
        # and a leftover SWAYSOCK makes e.g. oh-my-zsh's bgnotify plugin run
        # `swaymsg` on every prompt.
        unset SWAYSOCK I3SOCK
        systemctl --user unset-environment SWAYSOCK I3SOCK 2>/dev/null
        export XDG_CURRENT_DESKTOP=niri XDG_SESSION_DESKTOP=niri
        exec niri-session
    fi
fi

# Run backup if not snoozed and not inside a Cursor agent
_backup_snooze=~/.cache/backups/dont_ask_for_backup_until
if [[ -f $_backup_snooze ]] && (( $(date -d "$(cat $_backup_snooze)" +%s) > $(date +%s) )); then
    :
elif [[ "$CURSOR_AGENT" != "1" && -z "$SKIP_DD_BACKUP" ]]; then
    ~/.local/bin/backup.py backup --if-needed
fi

# Warn if /home is low on disk space
_free_space=$(df -m "$HOME" | awk 'NR==2 {print $4}')
if (( _free_space < 500 )) && command -v notify-send &>/dev/null; then
    notify-send "Low disk space" "Only ${_free_space}Mb left on $HOME"
fi
