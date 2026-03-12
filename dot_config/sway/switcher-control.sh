#!/bin/bash

# This script monitors how often the active window changes, and if it detects
# too many changes in a short period of time, it prompts the user the reason why
# they are switching in order to remind them to focus on one task.

# Duration of the short period of time
DURATION=5  # minutes
# Number of times the active window can change before the user is prompted
MAX_CHANGES=20
# List of timestamps of when the active window changed
LAST_WINDOW=""
WINDOW_LOG="/home/diego/.config/sway/switcher-control.log"
REASON_LOG="/home/diego/.config/sway/switcher-control-reasons.log"
LAST_PROMPT=0  # timestamp of the last time the user was prompted

# Main loop
while true; do
    # Get the current active window
    ACTIVE_WINDOW=$(swaymsg -t get_tree | jq -r '.. | (.nodes? // empty)[] | select(.focused==true).name')

    # If the active window changed, add the current timestamp to the list
    if [[ "$ACTIVE_WINDOW" != "$LAST_WINDOW" ]]; then
        LAST_WINDOW="$ACTIVE_WINDOW"
        echo "$(date +%s) $ACTIVE_WINDOW" >> "$WINDOW_LOG"
        echo "Switch: $(date +%s) $ACTIVE_WINDOW"
    fi

    # Compute the list of changes that happened in the last DURATION minutes
    # and count the number of changes
    changes=$(awk -v duration="$DURATION" -v now="$(date +%s)" '{if (now - $1 < duration*60) print $0}' "$WINDOW_LOG")
    n_changes=$(echo "$changes" | wc -l)

    # date
    # echo "Changes: $changes"

    # if too many changes and the last time the user was prompted was more than
    # 1 minute ago then prompt the user
    if [[ "$n_changes" -gt "$MAX_CHANGES" ]] && [[ "$(($(date +%s) - $LAST_PROMPT))" -gt 60 ]]; then
        # Build the prompt, using the window log
        PROMPT=$(
            echo "You have been switching windows too often. Please focus on one task at a time."
            echo
            echo "Recent changes:"
            # Convert the timestamps to human readable times and keep the window names
            tail -n "$MAX_CHANGES" "$WINDOW_LOG" | while read -r LINE; do
                # Convert the timestamp to a human readable time
                TIME=$(date -d "@$(echo "$LINE" | cut -d " " -f 1)" "+%H:%M:%S")
                # Print the time and the window name
                echo "$TIME $(echo "$LINE" | cut -d " " -f 2-)"
            done
        )

        # Prompt the user for a reason
        REASON=$(echo "$PROMPT" | wofi -d -p "Switcher Control" --show dmenu)

        # If the user didn't enter a reason, use "no reason"
        if [[ -z "$REASON" ]]; then
            REASON="no reason"
        fi

        # log the reason
        echo "$(date +%s) $REASON" >> "$REASON_LOG"

        LAST_PROMPT=$(date +%s)
    fi

    # If the log file is too big, rotate it by appending
    # a number to the name, avoiding overwriting existing files
    if [[ $(wc -l < "$WINDOW_LOG") -gt 10000 ]]; then
        i=0
        while [[ -f "$WINDOW_LOG.$i" ]]; do
            i=$((i+1))
        done
        mv "$WINDOW_LOG" "$WINDOW_LOG.$i"
    fi

    # Sleep for the duration
    sleep 5s
done