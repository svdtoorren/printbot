# Server-coordination prompt — CUPS queue visibility & remote remediation

Use the prompt below verbatim with the agent working on the companion server
repository (`~/Development/printgateway-server/`, branch `main`). It explains
the incident, the wire-contract this client repo (`printbot`, branch
`claude/investigate-printer-queue-issue-zaLlV`) is shipping, and asks the
server-side agent to deliver an aligned implementation plan **before** the
client PRs merge — so we can adjust field names / message shapes once instead
of doing a schema migration later.

---

> **Context.** Op een gateway-locatie gaf een printer een fysieke drum-fout. CUPS op de gateway zette daardoor de queue in state `stopped`. Nadat de drum vervangen was bleef de queue stopped — de iPad kon weer direct via IPP naar de printer, maar de gateway niet. De enige workaround was de printer remote verwijderen en opnieuw toevoegen (wat via `lpadmin -p … -E` de queue met `enabled + accepting` opnieuw aanmaakt). De heartbeat toonde wél "stopped", maar we konden niet zien **waarom** en niet **wat er in de queue stond**, en hadden geen remote recovery-actie minder ingrijpend dan "verwijder en voeg opnieuw toe".
>
> **Scope van de gezamenlijke fix (quick wins, ~1 dev-dag).** De client-repo `printbot` (branch `claude/investigate-printer-queue-issue-zaLlV`) levert drie PR's die samen de operator-loop sluiten. **Deze server-kant moet in lock-step meebewegen — wire-compatibility is essentieel**, anders loggen we nieuwe velden die nergens zichtbaar zijn of sturen we commando's die niet begrepen worden.
>
> **Wire-contract dat de client gaat opleveren.**
>
> *Heartbeat uitbreiding (backward compatible — bestaande `printer_status` string blijft).* Nieuwe top-level velden:
> ```
> printer_state_reasons: [str]        // bv ["cover-open","marker-supply-low-warning"]
> accepting_jobs: bool
> pending_jobs_count: int
> oldest_job_age_seconds: int | null
> printers: [{
>   name: str,
>   state: "idle"|"printing"|"stopped"|"unknown",
>   state_reasons: [str],
>   accepting_jobs: bool,
>   pending_jobs: int,
>   oldest_job_age_seconds: int | null,
>   is_default: bool
> }]
> ```
> De `printers` array is forward-compatible voor toekomstige multi-printer support; vandaag bevat hij één entry.
>
> *Nieuwe server→client WebSocket messages.* Allemaal met bestaande `cups_response` envelope + `request_id` correlatie:
>
> | Type | Payload | Effect op gateway |
> |---|---|---|
> | `cups_enable_printer` | `{printer_name}` | `cupsenable` |
> | `cups_disable_printer` | `{printer_name, reason?}` | `cupsdisable [-r reason]` |
> | `cups_accept_jobs` | `{printer_name}` | `cupsaccept` |
> | `cups_reject_jobs` | `{printer_name, reason?}` | `cupsreject [-r reason]` |
> | `cups_resume_printer` | `{printer_name}` | `cupsenable + cupsaccept` (one-click fix voor het incident) |
> | `cups_list_jobs` | `{printer_name}` | `lpstat -W not-completed -o -l` → array van jobs |
> | `cups_cancel_job` | `{job_id, purge?}` | `cancel [-x] <id>` |
> | `cups_clear_queue` | `{printer_name, purge?}` | `cancel -a [-x] <name>` |
>
> *Semantiek — let op voor UI-copy.* `resume` hervat alleen de queue; pending jobs blijven en worden direct verwerkt. `clear_queue` wist jobs zonder de queue te hervatten. Dit zijn twee losse operator-acties (combineerbaar, maar niet één).
>
> **Wat ik van jou nodig heb (onderzoek + plan, nog geen implementatie).** Lever een concreet implementatieplan met file-paths en regelnummers voor:
>
> 1. **Heartbeat-ingestie.** Lokaliseer de WS-handler + DB-model. Hoe voegen we de nieuwe velden toe — nullable kolommen op de bestaande tabel versus een aparte `heartbeat_printer_detail` tabel? Motiveer.
> 2. **Command surface.** Ontwerp REST-endpoints (voorstel: `POST /api/gateways/{id}/printers/{name}/resume`, `/enable`, `/disable`, `/accept`, `/reject`, `GET /jobs`, `POST /jobs/{job_id}/cancel`, `DELETE /jobs`). Geef request/response schemas, hoe de server de WS-dispatch naar de gateway doet met `request_id` correlatie, timeout/retry-policy, en welke rollen welke actie mogen (resume is goedaardig, `clear_queue` met purge is destructief).
> 3. **UI surface.** Lokaliseer de gateway-detail pagina. Schets: state-reasons chip-row, accepting/not-accepting badge, job-tabel met per-rij cancel, "Resume queue" en "Clear queue" knoppen (laatste met bevestiging), weergave van `oldest_job_age_seconds`.
> 4. **Audit log.** Bestaat er al een audit-mechanisme? Zo ja uitbreiden voor queue-control acties (actor, gateway_id, printer_name, action, reason, success, timestamp).
> 5. **Afstemmingspunten.** Flag expliciet waar het wire-contract hierboven voor jou onhandig is — beter één velden bij te sturen in de client-PR's voordat ze merged zijn dan later een schema-migratie. Check bijvoorbeeld: naamgeving (`pending_jobs_count` vs `queue_length`), enum-waarden voor `state`, hoe `state_reasons` gerenderd gaat worden (ruwe CUPS-strings of mapping naar mens-vriendelijke labels — en zo ja, server-side of client-side mapping?).
>
> **Buiten scope voor deze iteratie** (komt later, niet nu plannen): auto-recovery, periodieke reconciliation, pycups-migratie, lokaal diagnostics HTTP endpoint.
>
> **Retourneer:** file-path-referenced plan, DB-migraties, endpoint-specs met voorbeeld-payloads, UI-schetsen in tekst, en een lijst van vragen/afstemmingspunten richting de client-PR's. Noem expliciet welke van mijn veldnamen/enums je wilt wijzigen — die wijzigingen nemen we mee vóór PR1 merged.
