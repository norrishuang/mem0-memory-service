#!/bin/bash
# update-services.sh
# Sync systemd user service/timer files from repo to ~/.config/systemd/user/
# Run this after any git pull that changes files under systemd/
#
# Usage:
#   bash tools/update-services.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
SYSTEMD_SRC="$REPO_ROOT/systemd"
SYSTEMD_DST="$HOME/.config/systemd/user"

echo "=== mem0 service file sync ==="
echo "Source: $SYSTEMD_SRC"
echo "Dest:   $SYSTEMD_DST"
echo ""

mkdir -p "$SYSTEMD_DST"

# Files to sync (user-level services/timers only)
USER_UNITS=(
  "mem0-snapshot.service"
  "mem0-snapshot.timer"
  "mem0-auto-digest.service"
  "mem0-auto-digest.timer"
  "mem0-dream.service"
  "mem0-dream.timer"
)

updated=0
for unit in "${USER_UNITS[@]}"; do
  src="$SYSTEMD_SRC/$unit"
  dst="$SYSTEMD_DST/$unit"

  if [ ! -f "$src" ]; then
    echo "  SKIP  $unit (not found in repo)"
    continue
  fi

  if [ -f "$dst" ] && diff -q "$src" "$dst" > /dev/null 2>&1; then
    echo "  OK    $unit (up to date)"
  else
    cp "$src" "$dst"
    echo "  UPDATED $unit"
    updated=$((updated + 1))
  fi
done

if [ "$updated" -gt 0 ]; then
  echo ""
  echo "Reloading systemd user daemon..."
  systemctl --user daemon-reload
  echo "Done. $updated file(s) updated."
  echo ""
  echo "Active timers:"
  systemctl --user list-timers --no-pager 2>/dev/null | grep mem0 || true
else
  echo ""
  echo "All service files are up to date."
fi
