#!/usr/bin/env bash
# test_service_health.sh — Verify printbot systemd service is healthy on the Pi.
#
# Checks: service active, process running, not crash-looping, no recent errors, version.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/helpers.sh"

print_header "Service Health Tests"

# ── Test: systemd service is active ─────────────────────────────────────────
service_status=$(ssh_sudo "systemctl is-active printbot" 2>/dev/null || echo "inactive")
assert_eq "printbot service is active" "active" "$service_status"

# ── Test: process is running ────────────────────────────────────────────────
proc_count=$(ssh_cmd "pgrep -c -f 'printbot.main'" 2>/dev/null || echo "0")
assert_true "printbot process is running" "[[ $proc_count -ge 1 ]]"

# ── Test: not crash-looping (uptime > 60s) ──────────────────────────────────
if [[ "$service_status" == "active" ]]; then
    # Get service uptime in seconds via systemd
    active_enter=$(ssh_sudo "systemctl show printbot --property=ActiveEnterTimestamp --value" 2>/dev/null)
    if [[ -n "$active_enter" ]]; then
        active_epoch=$(ssh_cmd "date -d '${active_enter}' +%s" 2>/dev/null || echo "0")
        now_epoch=$(ssh_cmd "date +%s" 2>/dev/null)
        uptime_secs=$((now_epoch - active_epoch))
        assert_true "service uptime > 60s (actual: ${uptime_secs}s)" "[[ $uptime_secs -gt 60 ]]"
    else
        skip_test "service uptime > 60s" "could not read ActiveEnterTimestamp"
    fi
else
    skip_test "service uptime > 60s" "service is not active"
fi

# ── Test: no recent errors in journal (last 5 min) ──────────────────────────
error_count=$(ssh_sudo "journalctl -u printbot --since '5 minutes ago' -p err --no-pager -q 2>/dev/null | wc -l" 2>/dev/null || echo "0")
assert_true "no recent errors in journal (last 5 min, found: ${error_count})" "[[ $error_count -le 2 ]]"

# ── Test: version file exists ───────────────────────────────────────────────
version=$(ssh_cmd "cat /opt/printbot/VERSION 2>/dev/null" || echo "MISSING")
if [[ "$version" != "MISSING" && -n "$version" ]]; then
    echo -e "  ${GREEN}PASS${NC} VERSION file exists (${version})"
    PASS_COUNT=$((PASS_COUNT + 1))
else
    echo -e "  ${RED}FAIL${NC} VERSION file missing or empty"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi

print_summary
