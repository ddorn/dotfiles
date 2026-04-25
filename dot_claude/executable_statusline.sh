#!/usr/bin/env bash
# ~/.claude/statusline.sh — single-line Claude Code status

input=$(cat)

# ── Parse JSON fields ────────────────────────────────────────────────────────
session_id=$(echo "$input" | jq -r '.session_id // ""')
cwd=$(echo "$input" | jq -r '.workspace.current_dir // .cwd // ""')
model=$(echo "$input" | jq -r '.model.display_name // .model.id // "Claude"')
ctx_pct=$(echo "$input" | jq -r '.context_window.used_percentage // empty')
effort=$(echo "$input" | jq -r '.effort.level // empty')
rl_pct=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')
rl_resets=$(echo "$input" | jq -r '.rate_limits.five_hour.resets_at // empty')


# ── ANSI colors ───────────────────────────────────────────────────────────────
RESET='\033[0m'
CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
DIM='\033[2m'
WHITE='\033[37m'

# ── Model + effort ───────────────────────────────────────────────────────────
case "$effort" in
    low)    effort_icon="○" ;;
    medium) effort_icon="◐" ;;
    high)   effort_icon="●" ;;
    xhigh)  effort_icon="◉" ;;
    max)    effort_icon="◈" ;;
    "")     effort_icon=""  ;;
    *)      effort_icon="$effort" ;;
esac
[ -n "$effort_icon" ] \
    && model_part=$(printf "${CYAN}${model} ${effort_icon}${RESET}") \
    || model_part=$(printf "${CYAN}${model}${RESET}")

# ── Dir + git (cached 5s per session) ────────────────────────────────────────
dir_name=$(basename "$cwd")
git_info=""
if [ -n "$session_id" ]; then
    cache_file="/tmp/claude_git_${session_id}"
    now=$(date +%s)
    cache_time=$(stat -c %Y "$cache_file" 2>/dev/null || echo 0)
    age=$(( now - cache_time ))

    if [ "$age" -ge 5 ]; then
        branch=$(git -C "$cwd" --no-optional-locks rev-parse --abbrev-ref HEAD 2>/dev/null)
        if [ -n "$branch" ]; then
            staged=0; modified=0
            while IFS= read -r line; do
                x="${line:0:1}"; y="${line:1:1}"
                [[ "$x" != " " && "$x" != "?" ]] && (( staged++ ))
                [[ "$y" != " " && "$y" != "?" ]] && (( modified++ ))
            done < <(git -C "$cwd" --no-optional-locks status --porcelain 2>/dev/null)
            printf '%s|%d|%d' "$branch" "$staged" "$modified" > "$cache_file"
        else
            printf '' > "$cache_file"
        fi
        touch "$cache_file"
    fi

    cache_val=$(cat "$cache_file" 2>/dev/null)
    if [ -n "$cache_val" ]; then
        IFS='|' read -r branch staged modified <<< "$cache_val"
        git_counts=""
        [ "${staged:-0}" -gt 0 ]   && git_counts="${git_counts}\033[32m+${staged}${RESET}"
        [ "${modified:-0}" -gt 0 ] && git_counts="${git_counts}\033[33m~${modified}${RESET}"
        [ -n "$git_counts" ] \
            && git_info=" ${DIM}on${RESET} ${WHITE}${branch}${RESET} ${git_counts}" \
            || git_info=" ${DIM}on${RESET} ${WHITE}${branch}${RESET}"
    fi
fi
dir_part=$(printf "${WHITE}${dir_name}${RESET}${git_info}")

# ── 5-hour usage bar + time remaining ────────────────────────────────────────
if [ -n "$rl_pct" ]; then
    pct_int=$(printf '%.0f' "$rl_pct")
    filled=$(( pct_int * 8 / 100 )); [ "$filled" -gt 8 ] && filled=8
    empty=$(( 8 - filled ))
    if   [ "$pct_int" -lt 70 ]; then bar_color="$GREEN"
    elif [ "$pct_int" -lt 90 ]; then bar_color="$YELLOW"
    else                              bar_color="$RED"; fi
    bar=""; for (( i=0; i<filled; i++ )); do bar="${bar}█"; done
             for (( i=0; i<empty;  i++ )); do bar="${bar}░"; done
    # Time remaining in the window
    if [ -n "$rl_resets" ]; then
        remaining=$(( rl_resets - $(date +%s) ))
        [ "$remaining" -lt 0 ] && remaining=0
        r_hrs=$(( remaining / 3600 ))
        r_min=$(( (remaining % 3600) / 60 ))
        time_label="${r_hrs}h${r_min}m"
    else
        time_label="5h"
    fi
    usage_part=$(printf "${bar_color}${bar} ${pct_int}%%${RESET} ${DIM}${time_label}${RESET}")
else
    usage_part=$(printf "${DIM}5h: --${RESET}")
fi

# ── Context % (secondary) ────────────────────────────────────────────────────
if [ -n "$ctx_pct" ]; then
    ctx_int=$(printf '%.0f' "$ctx_pct")
    if   [ "$ctx_int" -lt 70 ]; then ctx_color="$GREEN"
    elif [ "$ctx_int" -lt 90 ]; then ctx_color="$YELLOW"
    else                              ctx_color="$RED"; fi
    ctx_part=$(printf "${ctx_color}ctx ${ctx_int}%%${RESET}")
else
    ctx_part=$(printf "${DIM}ctx --%${RESET}")
fi

# ── Single line output ────────────────────────────────────────────────────────
echo "${model_part}  ${dir_part}  ${usage_part}  ${ctx_part}"
