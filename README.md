# PrintBot — WebSocket Print Gateway Client

**Thin Raspberry Pi client die print jobs ontvangt via WebSocket, ze afdrukt via CUPS, en remote management van de queue mogelijk maakt.**

PrintBot draait op een Pi en houdt een persistent WebSocket open met de [Print Gateway Server](https://github.com/svdtoorren/printgateway-server). De server doet PDF-rendering, autorisatie en de admin-UI; de Pi voert puur lokaal CUPS-werk uit. De wire-tussenlaag is bidirectioneel — de gateway is geen passieve consumer maar een control-plane die remote diagnose en remediation toelaat.

## Architectuur

```
┌──────────────────────┐                 ┌────────────────────────────┐
│  printgateway-server │                 │  printbot (Raspberry Pi)   │
│                      │                 │                            │
│  ├─ REST + admin UI  │ ─── print ────► │  ├─ WS client + reconnect  │
│  ├─ PDF rendering    │ ─── ping ─────► │  ├─ Job queue (sequential) │
│  ├─ Job queue        │ ─── ota_update► │  ├─ Job dedup (SQLite)     │──► CUPS ──► Printer
│  ├─ CUPS admin API   │ ─── cups_*  ──► │  ├─ CUPS wrappers          │
│  ├─ Audit log        │                 │  ├─ Heartbeat + diagnostics│
│  └─ Heartbeat ingest │ ◄─ heartbeat ── │  ├─ OTA self-updater       │
│                      │ ◄─ job_status ─ │  └─ mDNS device discovery  │
│                      │ ◄─ cups_resp. ─ │                            │
└──────────────────────┘                 └────────────────────────────┘
                       persistent WebSocket (WSS)
```

De Pi is bewust dun: geen WeasyPrint of zware rendering, geen lokale REST-server, alleen een WS-loop + asyncio worker-threads voor CUPS-aanroepen. Alle rendering en autorisatie zit in de server.

## Features

- **Print job processing** — base64 PDF of raw payload via WebSocket, CUPS-submit met `lp`, dedup tegen herhaalde job-ids via lokale SQLite
- **Print verification fase 0** — gateway parseert de CUPS job-id uit `lp` stdout en stuurt 'm mee in `job_status: printing/completed/failed` zodat de server de job kan reconciliëren
- **Heartbeat met queue-diagnostics** — elke 30s, met per-printer `state` (`idle|processing|stopped|unknown`), `state_reasons`, `accepting_jobs`, `cups_pending_jobs`, `oldest_job_age_seconds`
- **Remote queue control** — de server kan `cupsenable`/`cupsdisable`/`cupsaccept`/`cupsreject`, jobs cancelen of de queue clearen, en de "stopped" queue weer hervatten met één commando (`cups_resume_printer`)
- **Remote CUPS admin** — printers toevoegen/verwijderen/default zetten, opties uitlezen/zetten via WebSocket
- **mDNS device discovery** — `avahi-browse` voor IPP-printers in het lokale netwerk, gerapporteerd terug aan de server
- **Server-driven config update** — server kan `.env`-velden remote bijwerken zonder Pi-toegang
- **OTA self-update** — server pusht `ota_update` met tarball-URL + sha256, gateway downloadt, verifieert, vervangt zichzelf en herstart via systemd
- **Auto-reconnect** — exponential backoff met jitter (5s → 300s), reactie op WSS-drops zonder dataverlies
- **Idempotente queue control** — `cupsenable` op already-enabled, `cancel` op completed job etc. zijn allemaal veilig herhalen

## Wire-contract (v0.5)

Volledige spec in [`docs/server-coordination-prompt.md`](docs/server-coordination-prompt.md). Kort overzicht:

### Server → Gateway message types

| Type | Doel |
|---|---|
| `print` | Print job met base64 PDF/raw payload |
| `ping` | Liveness check (gateway antwoordt met `pong`) |
| `config_update` | Remote update van `.env`-velden |
| `discover_devices` | Trigger mDNS scan, response in `discover_devices_response` |
| `ota_update` | Tarball-URL + sha256 + version, gateway updatet zichzelf |
| `cups_add_printer` / `cups_remove_printer` / `cups_list_printers` / `cups_set_default` / `cups_get_printer_options` / `cups_set_printer_options` | CUPS admin |
| `cups_resume_printer` / `cups_enable_printer` / `cups_disable_printer` / `cups_accept_jobs` / `cups_reject_jobs` / `cups_list_jobs` / `cups_cancel_job` / `cups_clear_queue` | Queue control (8 messages, allemaal met `request_id` correlatie) |

### Gateway → Server message types

| Type | Wanneer |
|---|---|
| `heartbeat` | Elke 30s — bevat `printer_status` (legacy v0.4.0 BC scalar) + `printers[]` array met per-printer diagnostics |
| `job_status` | `received` → `printing` → `completed` of `failed`; bevat `cups_job_id` zodra `lp` 'm heeft toegekend |
| `pong` | Reactie op `ping` |
| `discover_devices_response` | Lijst gevonden IPP-services |
| `cups_response` | Antwoord op elke `cups_*` admin/queue-control request, met `request_id` voor correlatie |
| `ota_status` | `downloading` → `verifying` → `installing` → `completed`/`failed` |

Alle additieve velden (`printers[]`, `cups_job_id`, etc.) zijn backward-compatible met v0.4.0 servers — onbekende velden worden genegeerd.

## Vereisten

### Raspberry Pi

- **Raspberry Pi OS** (Bookworm of nieuwer) of Debian 12+
- **Python** ≥ 3.11
- **CUPS** geïnstalleerd en draaiend
- **Avahi** (`avahi-daemon` + `avahi-utils`) voor mDNS discovery
- **USB printer** of netwerk printer (IPP/Bonjour)
- **Netwerk** met outbound HTTPS/WSS toegang

### Print Gateway Server

- Een draaiende [printgateway-server](https://github.com/svdtoorren/printgateway-server) instantie (v0.5+ voor de queue-control en heartbeat-enrichment features)
- Een geregistreerde gateway met API key

## Installatie

### Stap 1 — Gateway registreren op de server

```bash
curl -X POST https://printgateway.toorren.nl/api/v1/gateways \
  -H "Authorization: Bearer <admin-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Kantoor Pi", "organization": "my-org"}'
```

Noteer de `id` (gateway ID) en `api_key` uit de response. De API key wordt maar 1× getoond.

### Stap 2 — Repository clonen en configureren

```bash
git clone https://github.com/svdtoorren/printbot.git
cd printbot
cp .env.example .env
```

Vul `.env` in:

```bash
# Print Gateway verbinding
GATEWAY_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx    # Van stap 1
API_KEY=pgw_xxxxxxxxxxxxxxxxxxxxxxxxxxxx            # Van stap 1
WS_URL=wss://printgateway.toorren.nl/ws/gateway

# CUPS printer (krijg naam via 'lpstat -p' op de Pi)
PRINTER_NAME=YourPrinterName

# Optioneel
STATE_DIR=/var/lib/printbot        # SQLite deduplicatie database
HEARTBEAT_INTERVAL=30              # Seconden tussen heartbeats
RECONNECT_DELAY=5                  # Initiele reconnect wachttijd (sec)
MAX_RECONNECT_DELAY=300            # Maximale reconnect wachttijd (sec)
DRY_RUN=false                      # true = simuleer printen
LOG_LEVEL=INFO                     # DEBUG, INFO, WARNING, ERROR
```

### Stap 3 — Printer configureren in CUPS

#### USB printer

USB printers worden meestal automatisch herkend. Controleer met `lpstat -p`.

#### Netwerkprinter (IPP/AirPrint)

```bash
# Ontdek printers op het netwerk via Avahi/mDNS
avahi-browse -rt _ipp._tcp

# Voeg de printer toe via CUPS (voorbeeld: HP LaserJet via IPP)
sudo lpadmin -p MijnPrinter \
  -E \
  -v ipp://192.168.1.50/ipp/print \
  -m everywhere

# Stel A4 en enkelzijdig in als default
sudo lpoptions -p MijnPrinter -o media=A4 -o sides=one-sided

# Test
echo "Test print" | lp -d MijnPrinter
```

Als alternatief: CUPS web-interface op `http://<pi-ip>:631`. Of remote vanuit de server-UI via de `cups_add_printer` admin-actie.

### Stap 4 — Deployen naar de Pi

#### Optie A: Ansible (aanbevolen)

1. Pas `ansible/inventory.ini` aan met je Pi's IP:

```ini
[printpi]
printbot ansible_host=192.168.1.100 ansible_user=pi
```

2. Pas `ansible/site.yml` (of `ansible/host_vars/<host>.yml`) aan met je credentials:

```yaml
vars:
  GATEWAY_ID: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
  API_KEY: "pgw_your-api-key"
  WS_URL: "wss://printgateway.toorren.nl/ws/gateway"
  PRINTER_NAME: "YourPrinterName"
```

3. Deploy:

```bash
cd ansible && ansible-playbook -i inventory.ini site.yml
```

Dit installeert CUPS + Avahi, maakt een `printbot` system user, kopieert de code, maakt een venv, installeert dependencies, en start de systemd service.

#### Optie B: Handmatig

```bash
# Op de Raspberry Pi:
sudo apt update && sudo apt install -y cups avahi-daemon avahi-utils python3-venv python3-pip

sudo useradd -r -s /usr/sbin/nologin printbot
sudo mkdir -p /opt/printbot /var/lib/printbot
sudo chown printbot:printbot /opt/printbot /var/lib/printbot

git clone https://github.com/svdtoorren/printbot.git /tmp/printbot
sudo cp -r /tmp/printbot/src/printbot /opt/printbot/
sudo cp /tmp/printbot/requirements.txt /opt/printbot/
sudo cp /tmp/printbot/.env /opt/printbot/.env
sudo chown printbot:printbot /opt/printbot/.env
sudo chmod 640 /opt/printbot/.env

sudo python3 -m venv /opt/printbot/.venv
sudo /opt/printbot/.venv/bin/pip install -r /opt/printbot/requirements.txt

sudo cp /tmp/printbot/systemd/printbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now printbot
```

### Stap 5 — Verificatie

```bash
sudo systemctl status printbot
sudo journalctl -u printbot -f
```

Verwachte log-output bij succesvolle verbinding:

```
PrintBot Gateway starting
Gateway ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
Server: wss://printgateway.toorren.nl/ws/gateway
Printer: YourPrinterName
Connecting to wss://printgateway.toorren.nl/ws/gateway
Connected to server
Heartbeat sent (printer=idle, uptime=5s, printers=1)
```

Verifieer op de server dat de gateway online is:

```bash
curl -H "Authorization: Bearer <api-key>" \
  https://printgateway.toorren.nl/api/v1/gateways
# status: "online"
```

## Configuratie

| Variabele | Verplicht | Default | Beschrijving |
|-----------|-----------|---------|--------------|
| `GATEWAY_ID` | Ja | — | UUID van de geregistreerde gateway |
| `API_KEY` | Ja | — | API key (begint met `pgw_`) |
| `WS_URL` | Ja | `wss://printgateway.toorren.nl/ws/gateway` | WebSocket URL van de server |
| `PRINTER_NAME` | Ja | — | CUPS printer naam |
| `STATE_DIR` | Nee | `/var/lib/printbot` | Directory voor SQLite database |
| `HEARTBEAT_INTERVAL` | Nee | `30` | Seconden tussen heartbeats |
| `RECONNECT_DELAY` | Nee | `5` | Initiele reconnect delay (sec) |
| `MAX_RECONNECT_DELAY` | Nee | `300` | Max reconnect delay (sec) |
| `DRY_RUN` | Nee | `false` | Simuleer printen (geen CUPS aanroep) |
| `LOG_LEVEL` | Nee | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR` |

`config_update` van de server kan elk van deze velden remote bijwerken; `Settings.save_to_env()` schrijft de wijziging persistent terug naar `/opt/printbot/.env` en de service herstart op de volgende reconnect.

## Updates deployen

```bash
cd ansible && ansible-playbook -i inventory.ini site.yml
```

De playbook behoudt `.env`, herstart de service en herinstalleert dependencies indien nodig. Als alternatief kan de server zelf een `ota_update` pushen — gateway downloadt het tarball, verifieert sha256, vervangt `/opt/printbot/src/printbot/`, en herstart via systemd.

## Extra gateway toevoegen

1. Registreer een nieuwe gateway op de server (zelfde `curl` als stap 1).
2. Maak een host vars bestand: `cp ansible/host_vars/printgw-01.yml ansible/host_vars/printgw-02.yml` en vul `GATEWAY_ID`, `API_KEY`, `PRINTER_NAME` in.
3. Voeg de Pi toe aan `ansible/inventory.ini`.
4. Deploy alleen die host: `ansible-playbook -i ansible/inventory.ini site.yml --limit printgw-02`.

## Troubleshooting

### Service start niet

```bash
sudo journalctl -u printbot -n 100
# Of test handmatig:
sudo -u printbot /opt/printbot/.venv/bin/python -m printbot.main
```

### "Missing required settings: gateway_id, api_key"

Controleer of `/opt/printbot/.env` correct ingevuld is en alle verplichte velden bevat.

### Kan niet verbinden met server

```bash
curl https://printgateway.toorren.nl/api/v1/health   # → {"status":"ok"}
python3 -c "import websockets, asyncio; asyncio.run(websockets.connect('wss://printgateway.toorren.nl/ws/gateway'))"
```

Bij verbindingsproblemen retry de gateway automatisch met exponential backoff (5s → 10s → 20s → … → max 300s).

### Printer wordt niet gevonden

```bash
lpstat -p                          # List printers
lpstat -t                          # Volledige CUPS status
echo "Test" | lp -d <printer>      # Test print
systemctl status cups              # CUPS service
```

### Queue zit "stopped"

Vanaf v0.5 stuurt de heartbeat per-printer state inclusief reden. Vraag de operator de "Resume queue"-knop in de admin-UI te gebruiken — dat stuurt `cups_resume_printer` (= `cupsenable + cupsaccept`). Lokaal:

```bash
sudo cupsenable <printer>
sudo cupsaccept <printer>
```

### Job wordt niet geprint (deduplicatie)

```bash
sudo rm /var/lib/printbot/state.db
sudo systemctl restart printbot
```

## Lokaal testen

```bash
# Terminal 1: Mock server
python -m tests.mock_server         # ws://localhost:8765/ws/gateway

# Terminal 2: Gateway tegen mock server
WS_URL=ws://localhost:8765/ws/gateway \
GATEWAY_ID=test-gateway \
API_KEY=test-key \
PRINTER_NAME=test-printer \
DRY_RUN=true \
python -m printbot.main
```

De mock server stuurt na 2 seconden een test print job. Voor unit tests:

```bash
pip install -r requirements-test.txt
pytest                              # 125 tests, ~2s
```

## Repository structuur

```
printbot/
├── src/printbot/
│   ├── __init__.py
│   ├── main.py                # Async entry point + signal handlers
│   ├── config.py              # Settings dataclass + .env load/save
│   ├── websocket_client.py    # WS-loop, dispatch, heartbeat, _build_printer_entry,
│   │                          # 17 server→gateway message handlers
│   ├── job_handler.py         # PDF/raw decode, print, dedup (SQLite)
│   ├── printing.py            # CUPS CLI wrappers (~30 fns):
│   │                          #   • print_pdf / print_raw (returns cups_job_id)
│   │                          #   • add/remove/list/set_default printer
│   │                          #   • get/set printer options
│   │                          #   • enable/disable/accept/reject queue
│   │                          #   • cancel_job / clear_queue
│   │                          #   • get_printer_detail (state + reasons)
│   │                          #   • list_jobs (IPP kebab-case schema)
│   │                          #   • discover_devices (avahi + dnssd backend)
│   └── ota_updater.py         # Tarball download + sha256 verify + restart
├── tests/
│   ├── conftest.py
│   ├── mock_server.py         # Standalone mock WS server (port 8765)
│   ├── inspect_state.py       # Debug helper for SQLite dedup state
│   ├── test_config.py
│   ├── test_job_handler.py
│   ├── test_message_routing.py # cups_* + ota + discover handlers
│   ├── test_ota_updater.py
│   ├── test_printing.py        # 49 tests (parsers, wrappers, lp parsing)
│   ├── test_websocket_client.py # heartbeat shape, job_status flow
│   └── device/                # Real-device integration helpers
├── ansible/
│   ├── ansible.cfg
│   ├── site.yml               # Main playbook
│   ├── inventory.ini
│   ├── verify_paths.yml       # Pre-deploy sanity check
│   ├── group_vars/
│   ├── host_vars/             # Per-Pi credentials
│   └── roles/
│       ├── cups/              # CUPS + Avahi installatie
│       └── printbot/          # PrintBot deployment (venv, systemd, .env)
├── docs/
│   └── server-coordination-prompt.md  # v0.5 wire-contract reference
├── systemd/
│   └── printbot.service       # Systemd unit
├── pyproject.toml             # pytest config (asyncio_mode=auto, pythonpath=src)
├── requirements.txt           # websockets, python-dotenv, requests, tenacity
├── requirements-test.txt      # + pytest, pytest-asyncio, pytest-cov
├── .env.example
└── README.md
```

## Gerelateerd

- [printgateway-server](https://github.com/svdtoorren/printgateway-server) — Server (FastAPI + PostgreSQL + WebSocket + admin UI)
- [`docs/server-coordination-prompt.md`](docs/server-coordination-prompt.md) — Volledige v0.5 wire-contract, single source of truth voor de protocol-shapes
