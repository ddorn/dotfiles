#!/bin/bash
# Interactive setup script for binary tools (no sudo required).
# Runs automatically on `chezmoi apply` when this file changes.
# Oh-My-Zsh and ZSH plugins are managed via .chezmoiexternal.toml instead.
set -euo pipefail

_green='\033[0;32m' _yellow='\033[1;33m' _cyan='\033[0;36m' _bold='\033[1m' _reset='\033[0m'

info()    { echo -e "${_cyan}${*}${_reset}"; }
success() { echo -e "${_green}✓ ${*}${_reset}"; }
skip()    { echo -e "${_yellow}↷ ${*}${_reset}"; }

# Prompt the user to install a tool.
# Usage: prompt_install <name> <already_installed_check> <install_cmd_display> <install_cmd>
# already_installed_check: a bash expression that exits 0 if already installed
# install_cmd_display: human-readable version of the install command (may be multiline)
# install_cmd: command to actually run
prompt_install() {
    local name="$1"
    local check="$2"
    local display="$3"
    local cmd="$4"

    echo
    echo -e "${_bold}=== $name ===${_reset}"

    if eval "$check" &>/dev/null; then
        success "$name is already installed"
        return
    fi

    echo
    info "Install command:"
    echo "$display" | sed 's/^/    /'
    echo
    echo "  [s] Install via script"
    echo "  [m] Skip (install manually later)"
    echo
    printf "Choice [s/m]: "
    read -r choice

    case "${choice,,}" in
        s)
            info "Running install..."
            eval "$cmd"
            success "$name installed"
            ;;
        m|*)
            skip "Skipping $name — install manually when ready"
            ;;
    esac
}

echo
echo -e "${_bold}╔══════════════════════════════════════╗${_reset}"
echo -e "${_bold}║  Machine setup — interactive install  ║${_reset}"
echo -e "${_bold}╚══════════════════════════════════════╝${_reset}"
echo "All tools are installed to ~/.local/bin (no sudo required)."
echo "Oh-My-Zsh and ZSH plugins are managed by chezmoi externals (.chezmoiexternal.toml)."

# ── Starship ─────────────────────────────────────────────────────────────────
prompt_install "Starship prompt" \
    'command -v starship' \
    'curl -sS https://starship.rs/install.sh | sh -s -- --bin-dir ~/.local/bin --yes' \
    'curl -sS https://starship.rs/install.sh | sh -s -- --bin-dir ~/.local/bin --yes'

# ── direnv ───────────────────────────────────────────────────────────────────
_direnv_version="2.35.0"
prompt_install "direnv" \
    'command -v direnv' \
    "curl -sfL https://direnv.net/install.sh | bin_path=~/.local/bin bash
# or manually: download from https://github.com/direnv/direnv/releases (v${_direnv_version})" \
    'curl -sfL https://direnv.net/install.sh | bin_path=~/.local/bin bash'

# ── FZF ──────────────────────────────────────────────────────────────────────
prompt_install "fzf" \
    'command -v fzf' \
    'git clone --depth 1 https://github.com/junegunn/fzf.git ~/.fzf
~/.fzf/install --no-bash --no-fish --no-update-rc
ln -sf ~/.fzf/bin/fzf ~/.local/bin/fzf' \
    'git clone --depth 1 https://github.com/junegunn/fzf.git ~/.fzf && ~/.fzf/install --no-bash --no-fish --no-update-rc && ln -sf ~/.fzf/bin/fzf ~/.local/bin/fzf'

# ── Claude Code ───────────────────────────────────────────────────────────────
prompt_install "Claude Code" \
    'command -v claude' \
    'curl -fsSL https://claude.ai/install.sh | bash' \
    'curl -fsSL https://claude.ai/install.sh | bash'

echo
echo -e "${_bold}Done.${_reset}"
echo
