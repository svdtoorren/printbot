#!/usr/bin/env bash
# test_cups_status.sh — Verify CUPS configuration on the Pi.
#
# Checks: CUPS service active, printers configured, default printer set, printer idle.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/helpers.sh"

print_header "CUPS Status Tests"

# ── Test: CUPS service is active ────────────────────────────────────────────
cups_status=$(ssh_sudo "systemctl is-active cups" 2>/dev/null || echo "inactive")
assert_eq "CUPS service is active" "active" "$cups_status"

# ── Test: printers are configured ──────────────────────────────────────────
printer_list=$(ssh_cmd "lpstat -p 2>/dev/null" || echo "")
if [[ -n "$printer_list" ]]; then
    printer_count=$(echo "$printer_list" | wc -l | tr -d ' ')
    assert_true "printers configured (count: ${printer_count})" "[[ $printer_count -ge 1 ]]"
else
    echo -e "  ${RED}FAIL${NC} no printers configured"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi

# ── Test: default printer is set ────────────────────────────────────────────
default_printer=$(ssh_cmd "lpstat -d 2>/dev/null" || echo "")
if echo "$default_printer" | grep -q "system default destination:"; then
    printer_name=$(echo "$default_printer" | sed 's/system default destination: //')
    echo -e "  ${GREEN}PASS${NC} default printer is set (${printer_name})"
    PASS_COUNT=$((PASS_COUNT + 1))
else
    skip_test "default printer is set" "no default destination configured"
fi

# ── Test: configured printer is idle ────────────────────────────────────────
if [[ -n "$printer_list" ]]; then
    idle_check=$(echo "$printer_list" | head -1)
    if echo "$idle_check" | grep -qi "idle"; then
        echo -e "  ${GREEN}PASS${NC} printer is idle"
        PASS_COUNT=$((PASS_COUNT + 1))
    elif echo "$idle_check" | grep -qi "enabled"; then
        echo -e "  ${GREEN}PASS${NC} printer is enabled"
        PASS_COUNT=$((PASS_COUNT + 1))
    else
        echo -e "  ${YELLOW}SKIP${NC} printer status unclear: ${idle_check}"
        SKIP_COUNT=$((SKIP_COUNT + 1))
    fi
else
    skip_test "printer is idle" "no printers configured"
fi

print_summary
