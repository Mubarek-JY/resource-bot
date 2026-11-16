#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

PYTHON="${PYTHON:-python}"
VENV_DIR=".venv"

if [[ ! -d "$VENV_DIR" ]]; then
    "$PYTHON" -m venv "$VENV_DIR"
fi

if ! "$VENV_DIR/bin/python" -m pip install --default-timeout 100 -r requirements.txt; then
    printf '%s\n' \
        'The regular virtualenv install failed; retrying with system packages visible.' \
        'On Arch/Omarchy, install the documented system packages first if needed.'
    "$PYTHON" -m venv --clear --system-site-packages "$VENV_DIR"
    "$VENV_DIR/bin/python" -m pip install --default-timeout 100 -r requirements.txt
fi

if [[ ! -e .env ]]; then
    cp .env.example .env
fi

printf '\nSetup complete. Edit .env, then run: source .venv/bin/activate && python bot.py\n'
