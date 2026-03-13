#!/bin/sh

# The script is called twice, the parent opens a new terminal with fzf
# The child selects the emoji and copies it to the clipboard
# The parent waits then wtype to type the emoji.
# This is needed as if wtype is called from the child, it will type in the
# terminal.

if [ "$1" = "child" ]; then
    jq -r '.emojis[] | .shortname +  " " + .emoji + " " + .name' ~/.config/sway/emoji.json |
        fzf |
        cut -d " " -f 2 |
        wl-copy -n
    exit 0
fi

# Open a new terminal with the script as a child
alacritty --class=emojipicker -e "$0" child

# sleep 0.1
# wl-paste -n | wtype -
