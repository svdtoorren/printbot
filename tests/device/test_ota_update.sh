#!/usr/bin/env bash
# test_ota_update.sh — Verify OTA update prerequisites on the Pi.
#
# Checks: current version, venv exists, writable install dir, pip available.
# Does NOT trigger an actual OTA update.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/helpers.sh"

print_header "OTA Update Prerequisites"

# ── Test: VERSION file exists and is readable ───────────────────────────────
version=$(ssh_cmd "cat /opt/printbot/VERSION 2>/dev/null" || echo "MISSING")
if [[ "$version" != "MISSING" && -n "$version" ]]; then
    echo -e "  ${GREEN}PASS${NC} VERSION file readable (${version})"
    PASS_COUNT=$((PASS_COUNT + 1))
else
    echo -e "  ${RED}FAIL${NC} VERSION file missing or unreadable"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi

# ── Test: Python venv exists ────────────────────────────────────────────────
venv_check=$(ssh_cmd "test -f /opt/printbot/.venv/bin/python && echo ok || echo missing" 2>/dev/null)
assert_eq "Python venv exists" "ok" "$venv_check"

# ── Test: pip is available in venv ──────────────────────────────────────────
pip_check=$(ssh_cmd "test -f /opt/printbot/.venv/bin/pip && echo ok || echo missing" 2>/dev/null)
assert_eq "pip available in venv" "ok" "$pip_check"

# ── Test: install directory is writable by printbot user ────────────────────
writable_check=$(ssh_sudo "su -s /bin/sh printbot -c 'test -w /opt/printbot && echo ok || echo no'" 2>/dev/null || echo "error")
if [[ "$writable_check" == "error" ]]; then
    # Fallback: check ownership
    owner=$(ssh_cmd "stat -c '%U' /opt/printbot 2>/dev/null" || echo "unknown")
    if [[ "$owner" == "printbot" ]]; then
        echo -e "  ${GREEN}PASS${NC} install dir owned by printbot user"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        skip_test "install dir writable" "could not verify (owner: ${owner})"
    fi
else
    assert_eq "install dir writable by printbot" "ok" "$writable_check"
fi

# ── Test: requirements.txt exists ───────────────────────────────────────────
req_check=$(ssh_cmd "test -f /opt/printbot/requirements.txt && echo ok || echo missing" 2>/dev/null)
assert_eq "requirements.txt exists" "ok" "$req_check"

# ── Test: version matches server-reported version ───────────────────────────
if [[ "$version" != "MISSING" ]]; then
    gw_json=$(api_get "/api/v1/gateways/${GATEWAY_ID}" 2>/dev/null || echo "{}")
    server_version=$(echo "$gw_json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('firmware_version', 'unknown'))
" 2>/dev/null || echo "unknown")

    if [[ "$server_version" != "unknown" ]]; then
        assert_eq "version matches server (file: ${version}, server: ${server_version})" "$version" "$server_version"
    else
        skip_test "version matches server" "server version not available"
    fi
else
    skip_test "version matches server" "local VERSION file missing"
fi

print_summary
