#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/share/monitor-lights"
DESKTOP_DIR="$PREFIX/share/applications"
DESKTOP_FILE="$DESKTOP_DIR/monitor-lights.desktop"
DESKTOP_TEMPLATE="$PROJECT_DIR/monitor-lights.desktop.in"

mkdir -p "$APP_DIR" "$DESKTOP_DIR"

install -m 755 "$PROJECT_DIR/monitor-lights" "$APP_DIR/monitor-lights"
install -m 644 "$PROJECT_DIR/monitor_lights.py" "$APP_DIR/monitor_lights.py"

python3 - "$DESKTOP_TEMPLATE" "$DESKTOP_FILE" "$APP_DIR/monitor-lights" <<'PY'
from pathlib import Path
import sys

template_path = Path(sys.argv[1])
desktop_path = Path(sys.argv[2])
exec_path = sys.argv[3]
desktop_path.write_text(template_path.read_text().replace("__EXEC__", exec_path))
PY
chmod 644 "$DESKTOP_FILE"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
fi

printf 'Installed Monitor Lights to %s\n' "$APP_DIR"
printf 'Launcher written to %s\n' "$DESKTOP_FILE"
