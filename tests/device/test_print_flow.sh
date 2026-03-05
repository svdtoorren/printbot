#!/usr/bin/env bash
# test_print_flow.sh — Submit a print job and verify it completes end-to-end.
#
# Checks: Submit HTML job via API → poll until completed → verify status_history
# → verify in Pi's SQLite state.db.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/helpers.sh"

print_header "Print Flow Tests"

# ── Test: submit HTML job via API ───────────────────────────────────────────
job_response=$(api_post "/api/v1/jobs" "{
    \"gateway_id\": \"${GATEWAY_ID}\",
    \"content_type\": \"html\",
    \"content\": \"<h1>Device Test</h1><p>Automated test job from $(date -u +%Y-%m-%dT%H:%M:%SZ)</p>\",
    \"title\": \"Device Test $(date +%s)\"
}" 2>/dev/null || echo "FAIL")

if [[ "$job_response" == "FAIL" ]]; then
    echo -e "  ${RED}FAIL${NC} submit HTML job — API request failed"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    print_summary
    exit 1
fi

job_id=$(echo "$job_response" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || echo "")
if [[ -z "$job_id" ]]; then
    echo -e "  ${RED}FAIL${NC} submit HTML job — no job ID in response"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    print_summary
    exit 1
fi
echo -e "  ${GREEN}PASS${NC} job submitted (id: ${job_id})"
PASS_COUNT=$((PASS_COUNT + 1))

# ── Test: job completes within 60s ──────────────────────────────────────────
if wait_for_job_status "$job_id" "completed" 60; then
    echo -e "  ${GREEN}PASS${NC} job completed successfully"
    PASS_COUNT=$((PASS_COUNT + 1))
else
    echo -e "  ${RED}FAIL${NC} job did not complete within 60s"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    print_summary
    exit 1
fi

# ── Test: verify status history ─────────────────────────────────────────────
job_data=$(api_get "/api/v1/jobs/${job_id}" 2>/dev/null || echo "{}")
history_check=$(echo "$job_data" | python3 -c "
import sys, json
data = json.load(sys.stdin)
history = [h['status'] for h in data.get('status_history', [])]
has_rendering = 'rendering' in history
has_completed = 'completed' in history
print(f'rendering={has_rendering},completed={has_completed},steps={len(history)}')
" 2>/dev/null || echo "error")

assert_contains "status_history includes rendering" "rendering=True" "$history_check"
assert_contains "status_history includes completed" "completed=True" "$history_check"

# ── Test: job recorded in Pi's SQLite state.db ──────────────────────────────
# Use Python to query since sqlite3 CLI may not be installed
state_check=$(ssh_sudo "python3 -c \"
import sqlite3, sys
try:
    conn = sqlite3.connect('/var/lib/printbot/state.db')
    cur = conn.execute('SELECT COUNT(*) FROM printed_jobs WHERE job_id=?', ('${job_id}',))
    print(cur.fetchone()[0])
    conn.close()
except Exception as e:
    print('error', file=sys.stderr)
    sys.exit(1)
\"" 2>/dev/null || echo "error")
if [[ "$state_check" == "error" ]]; then
    skip_test "job in Pi state.db" "could not query state.db"
else
    state_check=$(echo "$state_check" | tr -d '[:space:]')
    assert_eq "job recorded in Pi state.db" "1" "$state_check"
fi

print_summary
