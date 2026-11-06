#!/usr/bin/env bash
# ==========================================================
# 🛡️ Virtualenv Manager & Aliases
# Location: ~/SE/toolbox/terminal_aliases/01_venv/act.sh
# ==========================================================

act() {
    local target_venv="$HOME/SE/toolbox/.venv/bin/activate"

    if [ -f "$target_venv" ]; then
        deactivate 2>/dev/null || true
        source "$target_venv"
        local py_ver
        py_ver=$(python3 -V 2>&1 | cut -d' ' -f2)
        echo -e "\033[1;32m✔ Active Environment:\033[0m $(python3 -c 'import sys; print(sys.prefix)') \033[1;30m(Python $py_ver)\033[0m"
    else
        echo -e "\033[1;31m✖ Toolbox virtualenv not found at:\033[0m $target_venv"
        return 1
    fi
}

alias activate='act'
alias deact='deactivate'
