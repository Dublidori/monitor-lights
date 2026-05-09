#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-$HOME/.local}"
APP_DIR="$PREFIX/share/monitor-lights"
DESKTOP_FILE="$PREFIX/share/applications/monitor-lights.desktop"

rm -f "$DESKTOP_FILE"
rm -rf "$APP_DIR"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$PREFIX/share/applications" >/dev/null 2>&1 || true
fi

printf 'Removed Monitor Lights from %s\n' "$PREFIX"
