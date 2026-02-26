#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   bash scripts/bot_manager.sh start
#   bash scripts/bot_manager.sh stop
#   bash scripts/bot_manager.sh restart
#   bash scripts/bot_manager.sh status
#
# Optional environment variables:
#   APP_DIR       Project directory (default: parent of this script)
#   VENV_PATH     Virtualenv path (default: $APP_DIR/.venv)
#   BOT_CMD       Start command (default: python3 bot.py)
#   LOG_FILE      Runtime log file (default: $APP_DIR/bot_runtime.log)
#   PID_FILE      PID file path (default: $APP_DIR/bot.pid)

ACTION="${1:-restart}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
VENV_PATH="${VENV_PATH:-$APP_DIR/.venv}"
BOT_CMD="${BOT_CMD:-python3 bot.py}"
LOG_FILE="${LOG_FILE:-$APP_DIR/bot_runtime.log}"
PID_FILE="${PID_FILE:-$APP_DIR/bot.pid}"

cd "$APP_DIR"

activate_venv() {
  if [[ -f "$VENV_PATH/bin/activate" ]]; then
    # shellcheck disable=SC1090
    source "$VENV_PATH/bin/activate"
  fi
}

is_running() {
  if [[ ! -f "$PID_FILE" ]]; then
    return 1
  fi
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

start_bot() {
  if is_running; then
    echo "Bot already running (PID $(cat "$PID_FILE"))."
    return 0
  fi

  activate_venv
  nohup bash -lc "$BOT_CMD" >> "$LOG_FILE" 2>&1 &
  local pid=$!
  echo "$pid" > "$PID_FILE"
  sleep 1

  if kill -0 "$pid" 2>/dev/null; then
    echo "Bot started (PID $pid)."
  else
    echo "Failed to start bot. Check log: $LOG_FILE"
    exit 1
  fi
}

stop_bot() {
  if ! is_running; then
    echo "Bot is not running."
    rm -f "$PID_FILE"
    return 0
  fi

  local pid
  pid="$(cat "$PID_FILE")"
  kill "$pid" 2>/dev/null || true

  for _ in {1..20}; do
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
    sleep 0.5
  done

  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null || true
  fi

  rm -f "$PID_FILE"
  echo "Bot stopped."
}

status_bot() {
  if is_running; then
    echo "Bot is running (PID $(cat "$PID_FILE"))."
  else
    echo "Bot is not running."
    return 1
  fi
}

case "$ACTION" in
  start)
    start_bot
    ;;
  stop)
    stop_bot
    ;;
  restart)
    stop_bot
    start_bot
    ;;
  status)
    status_bot
    ;;
  *)
    echo "Unknown action: $ACTION"
    echo "Usage: $0 {start|stop|restart|status}"
    exit 2
    ;;
esac
