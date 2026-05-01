# v0.5 wire-contract — CUPS queue visibility & remote remediation

Single-page reference for the wire-contract between the printbot gateway
client and the printgateway server, finalised after coordination between
both Claude agents. Both sides ship this contract as of:

- printbot main → PR #3 (5 commits on `claude/investigate-printer-queue-issue-zaLlV`)
- printgateway-server main → `dfe8a92` (heartbeat enrichment + admin UI) and
  `8fbb89d` (queue-control endpoints + audit log + cups_job_id ingestion)

All additions are **backward-compatible** with v0.4.0 firmware in production —
old gateways keep working unchanged, the server falls back gracefully when
new fields are absent.

## Background

A printer hit a physical drum-error. CUPS on the gateway flipped the queue
to `stopped`. After the drum was replaced the iPad could print directly via
IPP again, but the gateway-routed queue stayed stopped. The only working
remediation was deleting and re-adding the printer, which forces
`enabled + accepting` via `lpadmin -p … -E`.

The heartbeat showed `stopped` but not **why**, not **what was stuck in the
queue**, and there was no remote action lighter than re-add. v0.5 closes
that loop.

## Heartbeat — additive enrichment

Top-level scalar `printer_status` (legacy v0.4.0 path) is preserved. The
server keeps ingesting it for old gateways. New gateways add a per-printer
`printers[]` array with diagnostics; the server derives any aggregates it
needs from this array — we do **not** send top-level aggregates.

```jsonc
{
  "type": "heartbeat",
  "gateway_id": "...",
  "version": "0.5.x",
  "printer_status": "idle",            // v0.4.0 BC scalar — unchanged
  "uptime": 12345,
  "local_ip": "192.168.x.x",
  "printers": [{                        // NEW — single entry today,
                                        // forward-compatible for multi-printer
    "name": "hp",
    "state": "idle" | "processing" | "stopped" | "unknown",
                                        // NB: "processing", not "printing"
                                        // (IPP-aligned enum)
    "state_reasons": ["cover-open"],   // raw CUPS strings, "none" filtered
                                        // out client-side. Severity suffixes
                                        // (-error/-warning/-report) stay attached;
                                        // server splits.
    "accepting_jobs": true,
    "cups_pending_jobs": 0,             // explicit cups_ prefix — NOT
                                        // pending_jobs/queue_length
    "oldest_job_age_seconds": null,    // null when queue is empty or no
                                        // parseable timestamp
    "is_default": true,
    "uri": "ipp://hp.local/",          // optional passthrough; omitted when blank
    "info": "HP Office"                 // optional passthrough; omitted when blank
  }],
  "config": { ... }
}
```

CLI sources on the gateway side (no pycups migration in this iteration):

| Field | Source |
|---|---|
| `state` | `lpstat -p <name>` (`is idle` / `now printing` / `disabled` / `stopped`) |
| `state_reasons` | `lpstat -l -p <name>` "Reasons:" line + keyword scan |
| `accepting_jobs` | `lpstat -a <name>` ("is accepting requests") |
| `cups_pending_jobs` | row count from `lpstat -W not-completed -o <name>` |
| `oldest_job_age_seconds` | `now - min(time-at-creation)` over pending jobs |
| `is_default` | `lpstat -d` ("system default destination is X") |

## JobStatusMessage — additive `cups_job_id`

Optional `cups_job_id: int` is included on `printing` and `completed`/`failed`
messages once the gateway has parsed it from `lp` stdout. v0.4.0 servers
ignore the unknown key.

```jsonc
{ "type": "job_status", "job_id": "...", "status": "received" }   // no id yet
{ "type": "job_status", "job_id": "...", "status": "printing",
  "cups_job_id": 142 }                                              // submit done
{ "type": "job_status", "job_id": "...", "status": "completed",
  "cups_job_id": 142 }
```

Rules:
- `printing` is **only** emitted when `handle_print_job` actually submitted
  to CUPS. Deduplicated jobs (already-printed) skip `printing` and emit
  only `completed` (no `cups_job_id` either, since no `lp` call happened).
- When parsing fails (locale glitch, weird CUPS version), `cups_job_id` is
  **omitted** from the message (never `null`).
- `lp` is invoked under `LC_ALL=C` so the parseable English line stays
  stable on Dutch/German/etc. hosts.

## Server → gateway commands (8 messages)

All use the existing `cups_response` envelope + `request_id` correlation.

| Type | Payload | Effect |
|---|---|---|
| `cups_resume_printer` | `{printer_name}` | `cupsenable + cupsaccept` (one-click incident fix) |
| `cups_enable_printer` | `{printer_name}` | `cupsenable` |
| `cups_disable_printer` | `{printer_name, reason?}` | `cupsdisable [-r reason]` |
| `cups_accept_jobs` | `{printer_name}` | `cupsaccept` |
| `cups_reject_jobs` | `{printer_name, reason?}` | `cupsreject [-r reason]` |
| `cups_list_jobs` | `{printer_name}` | data shape `{"jobs": [<IPP-attribute kebab-case>]}` |
| `cups_cancel_job` | `{job_id, purge?}` | `cancel [-x] <id>` |
| `cups_clear_queue` | `{printer_name, purge?}` | `cancel -a [-x] <name>` |

`cups_list_jobs` response shape:

```jsonc
{
  "type": "cups_response", "request_id": "<uuid>", "success": true,
  "data": {
    "jobs": [
      {
        "job-id": 142,                         // int, REQUIRED
        "job-originating-user-name": "pi",
        "job-k-octets": 24,                    // lpstat column 3 — kilobytes
        "time-at-creation": 1745683200,        // Unix int; OMITTED on parse fail
        "job-state": "pending"                 // string for now (CLI),
                                                // server reverse-maps to IPP int
                                                // pycups migration brings ints natively
        // Fields the CLI cannot supply (job-name title,
        // job-state-reasons, document-format, etc.) are OMITTED — never null.
      }
    ]
  }
}
```

## Validation rules

- `reason` (disable/reject): clipped to 255 chars, latin-1 only — non-latin-1
  codepoints become `?` so `cupsdisable -r 🔥` doesn't crash. CUPS limit, not
  ours.
- `purge` (cancel/clear): default `False`. `True` is explicitly destructive.
- `printer_name`: raw, not URL-encoded. Server URL-encodes when serving the
  REST endpoints.

## Idempotence

CUPS handles most idempotence natively:
- `cupsenable` on already-enabled queue → exit 0
- `cupsdisable` on already-disabled → exit 0 (latest reason wins)
- `cupsaccept` / `cupsreject` idem
- `cancel <id>` on already-canceled or completed job → exit non-zero with
  "job not found"; the WS-handler maps that to `success: false, error: "..."`

## State-reason rendering

Server-side mapping from raw CUPS state-reason strings to user-friendly
labels (NL today, multi-lingual later). The client does **zero**
interpretation:

- Filter `none` out client-side before sending
- Severity suffixes (`-error` / `-warning` / `-report`) stay on the string;
  server splits
- No client-invented reason strings — only what CUPS produces

## Out of scope for v0.5 (deferred to v0.6+)

- Auto-recovery (server-initiated resume on detected blocked queue)
- Periodic gateway-side reconciliation
- pycups migration (and the richer job-attributes that come with it)
- Local diagnostics HTTP endpoint on the gateway
- Print-verification fase 1 (state-machine that polls CUPS until terminal
  job-state) and fase 2 (server-side reconciliation poll). Fase 0 — the
  `cups_job_id` plumbing — landed in v0.5 so the later phases do not need a
  contract bump.
