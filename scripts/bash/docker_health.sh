#!/usr/bin/env bash
# docker_health.sh — Check all running containers are healthy; restart unhealthy ones.
#
# Usage:
#   ./docker_health.sh
#   ./docker_health.sh --restart --log /var/log/docker_health.log
#   ./docker_health.sh --notify-url https://hooks.slack.com/services/...
#
# Parameters:
#   --restart       Automatically restart containers with "unhealthy" status
#   --log           Append results to this log file
#   --notify-url    POST a plain-text summary to this webhook URL on failure
#   --quiet         Suppress console output
#
# Exit codes:
#   0 — All containers healthy or no health checks configured
#   1 — One or more containers unhealthy or exited unexpectedly
#
# Example output:
#   [OK]        prometheus         running   healthy
#   [OK]        grafana            running   healthy
#   [UNHEALTHY] node-exporter      running   unhealthy  → restarted
#   [EXITED]    alertmanager       exited    ---

set -euo pipefail

RESTART=false
LOG_FILE=""
NOTIFY_URL=""
QUIET=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --restart)    RESTART=true;         shift   ;;
    --log)        LOG_FILE="$2";        shift 2 ;;
    --notify-url) NOTIFY_URL="$2";      shift 2 ;;
    --quiet)      QUIET=true;           shift   ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

log() {
  local msg="$1"
  [[ "$QUIET" == false ]] && echo "  $msg"
  [[ -n "$LOG_FILE" ]] && echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') $msg" >> "$LOG_FILE"
}

if ! command -v docker &>/dev/null; then
  log "ERROR: docker command not found"
  exit 1
fi

count_ok=0
count_unhealthy=0
count_exited=0
count_restarted=0
problem_containers=()

while IFS='|' read -r id name status health; do
  name="${name// /}"
  status="${status// /}"
  health="${health// /}"

  if [[ "$status" == "exited" || "$status" == "dead" ]]; then
    log "[EXITED]    $name   status=$status"
    (( count_exited++ )) || true
    problem_containers+=("$name (exited)")

  elif [[ "$health" == "unhealthy" ]]; then
    if [[ "$RESTART" == true ]]; then
      docker restart "$id" >/dev/null 2>&1 && restarted="→ restarted" || restarted="→ restart failed"
      (( count_restarted++ )) || true
    else
      restarted=""
    fi
    log "[UNHEALTHY] $name   status=$status health=$health $restarted"
    (( count_unhealthy++ )) || true
    problem_containers+=("$name (unhealthy)")

  elif [[ "$health" == "starting" ]]; then
    log "[STARTING]  $name   status=$status health=starting"

  else
    log "[OK]        $name   status=$status health=${health:-no-healthcheck}"
    (( count_ok++ )) || true
  fi

done < <(docker ps -a --format '{{.ID}}|{{.Names}}|{{.Status}}|{{.Health}}' 2>/dev/null | \
  awk -F'|' '{
    split($3, s, " ");
    print $1 "|" $2 "|" s[1] "|" $4
  }')

total_problems=$(( count_unhealthy + count_exited ))
log ""
log "Result: ${count_ok} OK, ${count_unhealthy} unhealthy, ${count_exited} exited, ${count_restarted} restarted"

if [[ $total_problems -gt 0 && -n "$NOTIFY_URL" ]]; then
  msg="Docker health check: ${count_unhealthy} unhealthy, ${count_exited} exited on $(hostname). Affected: ${problem_containers[*]}"
  curl -s -X POST -H "Content-Type: application/json" \
    -d "{\"text\": \"$msg\"}" \
    "$NOTIFY_URL" >/dev/null || true
fi

[[ $total_problems -eq 0 ]] && exit 0 || exit 1
