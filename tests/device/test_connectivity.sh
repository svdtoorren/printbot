#!/usr/bin/env bash
# test_connectivity.sh — Verify Pi connectivity and gateway status.
#
# Checks: SSH reachable, gateway online on server, recent heartbeat,
# WS connection in logs, Pi can reach server.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/helpers.sh"

print_header "Connectivity Tests"

# ── Test: SSH reachable ─────────────────────────────────────────────────────
ssh_output=$(ssh_cmd "echo ok" 2>/dev/null || echo "FAIL")
assert_eq "SSH connection to Pi" "ok" "$ssh_output"

# ── Test: gateway is online on server ───────────────────────────────────────
gw_json=$(api_get "/api/v1/gateways/${GATEWAY_ID}" 2>/dev/null || echo "{}")
gw_status=$(echo "$gw_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")
assert_eq "gateway status is online" "online" "$gw_status"

# ── Test: recent heartbeat (within last 2 minutes) ─────────────────────────
last_heartbeat=$(echo "$gw_json" | python3 -c "
import sys, json
from datetime import datetime, timezone, timedelta
data = json.load(sys.stdin)
hb = data.get('last_heartbeat', '')
if hb:
    # Parse ISO timestamp
    hb_time = datetime.fromisoformat(hb.replace('Z', '+00:00'))
    age = (datetime.now(timezone.utc) - hb_time).total_seconds()
    print(f'{int(age)}')
else:
    print('none')
" 2>/dev/null || echo "error")

if [[ "$last_heartbeat" == "none" || "$last_heartbeat" == "error" ]]; then
    echo -e "  ${RED}FAIL${NC} recent heartbeat — no heartbeat data"
    FAIL_COUNT=$((FAIL_COUNT + 1))
else
    assert_true "heartbeat age < 120s (actual: ${last_heartbeat}s)" "[[ $last_heartbeat -lt 120 ]]"
fi

# ── Test: WebSocket connection in recent logs ──────────────────────────────
# Check for connection or activity evidence today (heartbeats don't log at INFO)
ws_log=$(ssh_sudo "journalctl -u printbot --since today --no-pager -q 2>/dev/null | grep -c -i -E 'connect|job|print' || true" 2>/dev/null | tr -d '[:space:]')
ws_log="${ws_log:-0}"
assert_true "WS activity in today's logs (found: ${ws_log} lines)" "[[ $ws_log -ge 1 ]]"

# ── Test: Pi can reach server ───────────────────────────────────────────────
# Use curl to the health endpoint (ICMP ping may be blocked by firewall)
reach_ok=$(ssh_cmd "curl -sf -o /dev/null -w '%{http_code}' --max-time 10 ${SERVER_URL}/api/v1/health 2>/dev/null || echo 000" 2>/dev/null | tr -d '[:space:]')
assert_eq "Pi can reach server (HTTP health check)" "200" "$reach_ok"

print_summary
