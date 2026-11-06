# ==============================================================================
# SE Toolbox - Master Terminal Aliases & Utilities
# Location: ~/se/toolbox/terminal_aliases/toolbox_aliases.sh
# ==============================================================================

TOOLBOX_DIR="$HOME/se/toolbox"
ALIASES_DIR="$TOOLBOX_DIR/terminal_aliases"

# Add bundled binaries and wrappers to PATH
if [ -d "$ALIASES_DIR/bin" ]; then
    export PATH="$ALIASES_DIR/bin:$PATH"
fi

# Add library path for aria2c if needed
if [ -d "$ALIASES_DIR/lib" ]; then
    export LD_LIBRARY_PATH="$ALIASES_DIR/lib:${LD_LIBRARY_PATH}"
fi

# ------------------------------------------------------------------------------
# Navigation & Workspace Shortcuts
# ------------------------------------------------------------------------------
se() {
    cd "$HOME/se" && act toolbox
}
alias sec='code "$HOME/se/se.code-workspace"'

# ------------------------------------------------------------------------------
# Virtual Environment Switcher (act / activate / deact)
# ------------------------------------------------------------------------------
act() {
    local target_venv=""
    local req="$1"

    if [ -n "$req" ]; then
        case "$req" in
            tool*|Tool*) target_venv="$HOME/se/toolbox/.venv/bin/activate" ;;
            pers*|Pers*|dev*|Dev*) target_venv="$HOME/se/personal/.venv/bin/activate" ;;
            note*|Note*) target_venv="$HOME/se/notes/.venv/bin/activate" ;;
            proj*|Proj*) target_venv="$HOME/se/projects/.venv/bin/activate" ;;
            *)
                if [ -f "$req/.venv/bin/activate" ]; then
                    target_venv="$req/.venv/bin/activate"
                elif [ -f "$req/venv/bin/activate" ]; then
                    target_venv="$req/venv/bin/activate"
                fi
                ;;
        esac
    fi

    if [ -z "$target_venv" ]; then
        local curr_dir="$(pwd)"
        while [ "$curr_dir" != "/" ] && [ "$curr_dir" != "." ]; do
            if [ -f "$curr_dir/.venv/bin/activate" ]; then
                target_venv="$curr_dir/.venv/bin/activate"
                break
            elif [ -f "$curr_dir/venv/bin/activate" ]; then
                target_venv="$curr_dir/venv/bin/activate"
                break
            fi
            curr_dir="$(dirname "$curr_dir")"
        done
    fi

    if [ -z "$target_venv" ] || [ ! -f "$target_venv" ]; then
        target_venv="$HOME/se/toolbox/.venv/bin/activate"
    fi

    if [ -n "$target_venv" ] && [ -f "$target_venv" ]; then
        deactivate 2>/dev/null || true
        source "$target_venv"
        local py_ver
        py_ver=$(python3 -V 2>&1 | cut -d' ' -f2)
        echo -e "\033[1;32m✔ Active Environment:\033[0m $(python3 -c 'import sys; print(sys.prefix)') \033[1;30m(Python $py_ver)\033[0m"
    else
        echo -e "\033[1;31m✖ No virtualenv found\033[0m"
        return 1
    fi
}
alias activate='act'
alias deact='deactivate'

# ------------------------------------------------------------------------------
# YouTube & Media Downloaders (00_yt)
# ------------------------------------------------------------------------------
alias yt="$ALIASES_DIR/00_yt/yt"
alias yt4="$ALIASES_DIR/00_yt/yt4"
alias ytg="$ALIASES_DIR/00_yt/yt-gui"
alias yt-gui="$ALIASES_DIR/00_yt/yt-gui"
alias mp3="$ALIASES_DIR/00_yt/mp3"

# ------------------------------------------------------------------------------
# Aria2 Turbo Multi-Connection Downloaders (02_aria)
# ------------------------------------------------------------------------------
alias aria="$ALIASES_DIR/02_aria/aria"
alias aria_torr="$ALIASES_DIR/02_aria/aria_torr"

# ------------------------------------------------------------------------------
# Notebook Converters (03_notebooks)
# ------------------------------------------------------------------------------
alias ipynbtomd="$ALIASES_DIR/03_notebooks/ipynbtomd"
alias pdfs="$ALIASES_DIR/03_notebooks/convert_notebooks.sh"
pdf() {
    "$TOOLBOX_DIR/.venv/bin/jupyter" nbconvert --to pdf "$@"
}
html() {
    "$TOOLBOX_DIR/.venv/bin/jupyter" nbconvert --to html "$@"
}

# ------------------------------------------------------------------------------
# Workspace Tools & Shortcuts (05_workspace_tools)
# ------------------------------------------------------------------------------
alias math="$ALIASES_DIR/05_workspace_tools/math"
alias rewind-lecture="$ALIASES_DIR/05_workspace_tools/rewind-lecture"
alias toggle-lecture="$ALIASES_DIR/05_workspace_tools/toggle-lecture"

# ------------------------------------------------------------------------------
# System & Antigravity Helpers
# ------------------------------------------------------------------------------
alias update='sudo apt update && sudo apt upgrade -y'
artifacts() {
    if [ "$1" = "cd" ]; then
        cd "$HOME/artifacts" 2>/dev/null || cd "$HOME"
    else
        "$HOME/.local/bin/agy-artifacts" "$@" 2>/dev/null || true
    fi
}
alias agy-artifacts='artifacts'
alias view-artifacts='artifacts'
