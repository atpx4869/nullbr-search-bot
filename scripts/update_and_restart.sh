#!/usr/bin/env bash
set -euo pipefail

# Nightly maintenance script for VPS / 1Panel cron.
#
# Usage:
#   bash scripts/update_and_restart.sh
#
# Optional environment variables:
#   APP_DIR            Project directory (default: parent of this script)
#   BRANCH             Git branch to update (default: main)
#   VENV_PATH          Virtualenv path (default: $APP_DIR/.venv)
#   BACKUP_BEFORE_PULL Backup .env/auth.db before pull (default: 1)
#   INSTALL_DEPS       Install requirements after pull (default: 1)

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
BRANCH="${BRANCH:-main}"
VENV_PATH="${VENV_PATH:-$APP_DIR/.venv}"
BACKUP_BEFORE_PULL="${BACKUP_BEFORE_PULL:-1}"
INSTALL_DEPS="${INSTALL_DEPS:-1}"

cd "$APP_DIR"

activate_venv() {
  if [[ -f "$VENV_PATH/bin/activate" ]]; then
    # shellcheck disable=SC1090
    source "$VENV_PATH/bin/activate"
  fi
}

echo "[1/7] Restart bot first"
bash scripts/bot_manager.sh restart

echo "[2/7] Check remote updates"
git fetch origin
LOCAL_SHA="$(git rev-parse "$BRANCH")"
REMOTE_SHA="$(git rev-parse "origin/$BRANCH")"

if [[ "$LOCAL_SHA" != "$REMOTE_SHA" ]]; then
  echo "Updates found: $LOCAL_SHA -> $REMOTE_SHA"

  if [[ "$BACKUP_BEFORE_PULL" == "1" ]]; then
    echo "[3/7] Backup local runtime files"
    ts="$(date +%F-%H%M%S)"
    [[ -f .env ]] && cp .env ".env.bak.$ts"
    [[ -f auth.db ]] && cp auth.db "auth.db.bak.$ts"
  else
    echo "[3/7] Skip backup"
  fi

  echo "[4/7] Pull latest code"
  git checkout "$BRANCH"
  git pull --ff-only origin "$BRANCH"

  if [[ "$INSTALL_DEPS" == "1" ]]; then
    echo "[5/7] Install dependencies"
    if [[ ! -d "$VENV_PATH" ]]; then
      python3 -m venv "$VENV_PATH"
    fi
    activate_venv
    python -m pip install -U pip
    python -m pip install -r requirements.txt
  else
    echo "[5/7] Skip dependency install"
  fi

  echo "[6/7] Syntax check"
  activate_venv
  python -m py_compile bot.py nullbr_api.py message_utils.py
else
  echo "No updates found on origin/$BRANCH."
  echo "[3/7] Skip backup"
  echo "[4/7] Skip pull"
  echo "[5/7] Skip dependency install"
  echo "[6/7] Skip syntax check"
fi

echo "[7/7] Ensure bot is running"
bash scripts/bot_manager.sh start

echo "Done."
