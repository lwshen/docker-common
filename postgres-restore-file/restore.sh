#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
HELPER="$SCRIPT_DIR/backup_tools.py"
if [ ! -f "$HELPER" ]; then
  HELPER="$SCRIPT_DIR/../postgres-common/backup_tools.py"
fi
exec python3 "$HELPER" restore-file
