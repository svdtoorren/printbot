#!/usr/bin/env bash
# helpers.sh — shared utilities for SSH-based device tests.
# Source this file from test scripts: source "$(dirname "$0")/helpers.sh"

set -euo pipefail

# ── Colors ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ── Counters ────────────────────────────────────────────────────────────────
PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

# ── Required env vars ──────────────────────────────────────────────────────
: "${PI_HOST:?PI_HOST is required (e.g. printgw-01.local or 192.168.1.50)}"
: "${API_KEY:?API_KEY is required (pgw_... key for the gateway)}"
: "${GATEWAY_ID:?GATEWAY_ID is required (UUID of the gateway)}"
SERVER_URL="${SERVER_URL:-https://printgateway.toorren.nl}"
SSH_USER="${SSH_USER:-pi}"
SSH_OPTS="${SSH_OPTS:--o ConnectTimeout=10 -o StrictHostKeyChecking=no}"

# ── SSH wrapper ─────────────────────────────────────────────────────────────
ssh_cmd() {
    # Run a command on the Pi via SSH.
    # Usage: ssh_cmd "systemctl status printbot"
    ssh $SSH_OPTS "${SSH_USER}@${PI_HOST}" "$@"
}

ssh_sudo() {
    # Run a command on the Pi via SSH with sudo.
    # Usage: ssh_sudo "systemctl status printbot"
    ssh $SSH_OPTS "${SSH_USER}@${PI_HOST}" "sudo $*"
}

# ── API helper ──────────────────────────────────────────────────────────────
api_get() {
    # GET request to the server API.
    # Usage: api_get "/api/v1/gateways/${GATEWAY_ID}"
    local path="$1"
    curl -sf -H "Authorization: Bearer ${API_KEY}" "${SERVER_URL}${path}"
}

api_post() {
    # POST request to the server API with JSON body.
    # Usage: api_post "/api/v1/jobs" '{"gateway_id": "...", ...}'
    local path="$1"
    local body="$2"
    curl -sf -X POST \
        -H "Authorization: Bearer ${API_KEY}" \
        -H "Content-Type: application/json" \
        -d "${body}" \
        "${SERVER_URL}${path}"
}

# ── Assertions ──────────────────────────────────────────────────────────────
assert_eq() {
    local description="$1"
    local expected="$2"
    local actual="$3"

    if [[ "$expected" == "$actual" ]]; then
        echo -e "  ${GREEN}PASS${NC} $description"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo -e "  ${RED}FAIL${NC} $description"
        echo -e "       expected: ${expected}"
        echo -e "       actual:   ${actual}"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

assert_contains() {
    local description="$1"
    local needle="$2"
    local haystack="$3"

    if echo "$haystack" | grep -q "$needle"; then
        echo -e "  ${GREEN}PASS${NC} $description"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo -e "  ${RED}FAIL${NC} $description"
        echo -e "       expected to contain: ${needle}"
        echo -e "       actual: ${haystack}"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

assert_true() {
    local description="$1"
    local condition="$2"

    if eval "$condition"; then
        echo -e "  ${GREEN}PASS${NC} $description"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo -e "  ${RED}FAIL${NC} $description"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
}

skip_test() {
    local description="$1"
    local reason="$2"
    echo -e "  ${YELLOW}SKIP${NC} $description — $reason"
    SKIP_COUNT=$((SKIP_COUNT + 1))
}

# ── Wait helpers ────────────────────────────────────────────────────────────
wait_for_job_status() {
    # Poll a job until it reaches the target status or times out.
    # Usage: wait_for_job_status <job_id> <target_status> [timeout_seconds]
    local job_id="$1"
    local target="$2"
    local timeout="${3:-60}"
    local elapsed=0

    while [[ $elapsed -lt $timeout ]]; do
        local status
        status=$(api_get "/api/v1/jobs/${job_id}" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null || echo "unknown")

        if [[ "$status" == "$target" ]]; then
            return 0
        fi
        if [[ "$status" == "failed" && "$target" != "failed" ]]; then
            echo "Job ${job_id} failed unexpectedly"
            return 1
        fi

        sleep 2
        elapsed=$((elapsed + 2))
    done

    echo "Timed out waiting for job ${job_id} to reach status '${target}' (last: ${status})"
    return 1
}

# ── Test section header ────────────────────────────────────────────────────
print_header() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  $1"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ── Summary ────────────────────────────────────────────────────────────────
print_summary() {
    local total=$((PASS_COUNT + FAIL_COUNT + SKIP_COUNT))
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "  Results: ${GREEN}${PASS_COUNT} passed${NC}, ${RED}${FAIL_COUNT} failed${NC}, ${YELLOW}${SKIP_COUNT} skipped${NC} (${total} total)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    if [[ $FAIL_COUNT -gt 0 ]]; then
        return 1
    fi
    return 0
}
