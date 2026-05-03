#!/usr/bin/env bash
# backup_verify.sh — Verify that backup files exist and are not older than N days.
#
# Usage:
#   ./backup_verify.sh --dir /mnt/backups --max-age 1 --pattern "*.bak"
#   ./backup_verify.sh --dir /backups --max-age 7 --pattern "*.tar.gz" --log /var/log/backup_verify.log
#
# Parameters:
#   --dir       Directory to check for backup files (required)
#   --max-age   Maximum acceptable age in days (default: 1)
#   --pattern   Glob pattern for backup files (default: *)
#   --log       Optional log file to append results to
#   --quiet     Suppress console output (log file still written)
#
# Exit codes:
#   0 — All backups present and within age threshold
#   1 — One or more backups missing or stale
#   2 — Backup directory not found
#
# Example output:
#   [OK]   db-full-2024-05-03.tar.gz    last modified: 6 hours ago
#   [STALE] db-full-2024-04-25.tar.gz   last modified: 8 days ago (max: 1)
#   Result: 1 OK, 1 STALE, 0 MISSING

set -euo pipefail

BACKUP_DIR=""
MAX_AGE=1
PATTERN="*"
LOG_FILE=""
QUIET=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --dir)     BACKUP_DIR="$2"; shift 2 ;;
    --max-age) MAX_AGE="$2";    shift 2 ;;
    --pattern) PATTERN="$2";    shift 2 ;;
    --log)     LOG_FILE="$2";   shift 2 ;;
    --quiet)   QUIET=true;      shift   ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$BACKUP_DIR" ]] && { echo "ERROR: --dir is required" >&2; exit 1; }
[[ -d "$BACKUP_DIR" ]] || { echo "ERROR: Directory not found: $BACKUP_DIR" >&2; exit 2; }

log() {
  local msg="$1"
  [[ "$QUIET" == false ]] && echo "  $msg"
  [[ -n "$LOG_FILE" ]] && echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $msg" >> "$LOG_FILE"
}

count_ok=0
count_stale=0
count_missing=0
now=$(date +%s)

shopt -s nullglob
files=("$BACKUP_DIR"/$PATTERN)
shopt -u nullglob

if [[ ${#files[@]} -eq 0 ]]; then
  log "MISSING  No files matching '$PATTERN' found in $BACKUP_DIR"
  count_missing=1
else
  for fpath in "${files[@]}"; do
    fname=$(basename "$fpath")
    mtime=$(stat -c %Y "$fpath" 2>/dev/null || stat -f %m "$fpath" 2>/dev/null)
    age_seconds=$(( now - mtime ))
    age_days=$(( age_seconds / 86400 ))
    age_hours=$(( age_seconds / 3600 ))

    if (( age_days >= MAX_AGE )); then
      log "[STALE]  $fname   last modified: ${age_days} day(s) ago (max: ${MAX_AGE})"
      (( count_stale++ )) || true
    else
      log "[OK]     $fname   last modified: ${age_hours} hour(s) ago"
      (( count_ok++ )) || true
    fi
  done
fi

log ""
log "Result: ${count_ok} OK, ${count_stale} STALE, ${count_missing} MISSING in ${BACKUP_DIR}"

[[ $count_stale -eq 0 && $count_missing -eq 0 ]] && exit 0 || exit 1
