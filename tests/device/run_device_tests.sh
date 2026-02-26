#!/usr/bin/env bash
# run_device_tests.sh — Orchestrator for SSH-based device tests.
#
# Usage:
#   PI_HOST=printgw-01.local API_KEY=pgw_... GATEWAY_ID=<uuid> bash tests/device/run_device_tests.sh
#
# Optional env vars:
#   SERVER_URL  — server base URL (default: https://printgateway.toorren.nl)
#   SSH_USER    — SSH username (default: pi)
#   SSH_OPTS    — extra SSH options

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Load .env if present ────────────────────────────────────────────────────
if [[ -f "${SCRIPT_DIR}/../../.env" ]]; then
    echo "Loading .env file..."
    set -a
    source "${SCRIPT_DIR}/../../.env"
    set +a
fi

# ── Validate required variables ─────────────────────────────────────────────
: "${PI_HOST:?PI_HOST is required (e.g. printgw-01.local or 192.168.1.50)}"
: "${API_KEY:?API_KEY is required (pgw_... key for the gateway)}"
: "${GATEWAY_ID:?GATEWAY_ID is required (UUID of the gateway)}"

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║              PrintBot Device Test Suite                         ║"
echo "╠══════════════════════════════════════════════════════════════════╣"
echo "║  Host:     ${PI_HOST}"
echo "║  Gateway:  ${GATEWAY_ID:0:8}..."
echo "║  Server:   ${SERVER_URL:-https://printgateway.toorren.nl}"
echo "╚══════════════════════════════════════════════════════════════════╝"

TOTAL_PASS=0
TOTAL_FAIL=0
TOTAL_SKIP=0
FAILED_SUITES=()

run_test_suite() {
    local script="$1"
    local name
    name=$(basename "$script" .sh)

    echo ""
    if bash "$script"; then
        : # suite passed
    else
        FAILED_SUITES+=("$name")
    fi

    # Source helpers again to read counters (they are reset per script)
    # We parse the summary line from output instead
}

# ── Run all test suites ─────────────────────────────────────────────────────
SUITES=(
    "${SCRIPT_DIR}/test_service_health.sh"
    "${SCRIPT_DIR}/test_connectivity.sh"
    "${SCRIPT_DIR}/test_cups_status.sh"
    "${SCRIPT_DIR}/test_print_flow.sh"
    "${SCRIPT_DIR}/test_ota_update.sh"
)

for suite in "${SUITES[@]}"; do
    if [[ -f "$suite" ]]; then
        run_test_suite "$suite"
    else
        echo "WARNING: Test suite not found: $suite"
    fi
done

# ── Final summary ───────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║                    All Suites Complete                          ║"
echo "╠══════════════════════════════════════════════════════════════════╣"
if [[ ${#FAILED_SUITES[@]} -eq 0 ]]; then
    echo "║  All test suites passed!                                       ║"
else
    echo "║  Failed suites:                                                ║"
    for suite in "${FAILED_SUITES[@]}"; do
        printf "║    - %-56s ║\n" "$suite"
    done
fi
echo "╚══════════════════════════════════════════════════════════════════╝"

if [[ ${#FAILED_SUITES[@]} -gt 0 ]]; then
    exit 1
fi
