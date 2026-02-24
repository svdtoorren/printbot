# PrintBot - WebSocket Print Gateway Client

**Thin client die print jobs ontvangt via WebSocket en afdrukt op een CUPS printer.**

PrintBot draait op een Raspberry Pi en verbindt via WebSocket met de [Print Gateway Server](https://github.com/svdtoorren/printgateway-server). De server rendert HTML/text naar PDF en stuurt kant-en-klare PDF's naar de Pi, die ze doorgeeft aan CUPS.

## Architectuur

```
┌──────────────────────┐         ┌──────────────────┐
│  printgateway-server │◄──WSS──►│  printbot (Pi)    │
│  (cloud/homelab)     │         │                   │
│  ├─ REST API         │         │  ├─ WS client     │──► CUPS ──► Printer
│  ├─ PDF rendering    │         │  ├─ Job handler    │
│  └─ Job queue        │         │  └─ Heartbeat      │
└──────────────────────┘         └──────────────────┘
```

- **Pi ontvangt** kant-en-klare PDF's via WebSocket
- **Pi stuurt** heartbeats (printer status, uptime, versie)
- **Auto-reconnect** met exponential backoff + jitter
- **Job deduplicatie** via lokale SQLite database
- **Geen WeasyPrint** of zware rendering dependencies op de Pi

## Vereisten

### Raspberry Pi
- **Raspberry Pi OS** (Bookworm of nieuwer) of Debian 12+
- **Python** >= 3.11
- **CUPS** geinstalleerd en geconfigureerd
- **USB printer** of netwerk printer (IPP/Bonjour)
- **Netwerk** met outbound HTTPS/WSS access

### Print Gateway Server
- Een draaiende [printgateway-server](https://github.com/svdtoorren/printgateway-server) instantie
- Een geregistreerde gateway met API key

## Installatie

### Stap 1: Gateway registreren op de server

Registreer een gateway via de server API en sla de API key op:

```bash
curl -X POST https://printgateway.toorren.nl/api/v1/gateways \
  -H "Authorization: Bearer <admin-api-key>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Kantoor Pi", "organization": "my-org"}'
```

Noteer de `id` (gateway ID) en `api_key` uit de response. De API key wordt maar 1x getoond.

### Stap 2: Repository clonen en configureren

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
WS_URL=wss://printgateway.toorren.nl/ws/gateway    # Server WebSocket URL

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

### Stap 3: Printer configureren in CUPS

```bash
# List beschikbare printers
lpstat -p

# Test printer
echo "Test print" | lp -d <printer-name>
```

Of configureer via de CUPS web interface: `http://<pi-ip>:631`

### Stap 4: Deployen naar de Pi

#### Optie A: Ansible (aanbevolen)

1. Pas `ansible/inventory.ini` aan met je Pi's IP:

```ini
[printpi]
printbot ansible_host=192.168.1.100 ansible_user=pi
```

2. Pas `ansible/site.yml` aan met je credentials:

```yaml
vars:
  GATEWAY_ID: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
  API_KEY: "pgw_your-api-key"
  WS_URL: "wss://printgateway.toorren.nl/ws/gateway"
  PRINTER_NAME: "YourPrinterName"
```

3. Deploy:

```bash
ansible-playbook -i ansible/inventory.ini ansible/site.yml
```

Dit installeert CUPS, maakt een `printbot` system user, kopieert de code, maakt een venv, installeert dependencies, en start de systemd service.

#### Optie B: Handmatig

```bash
# Op de Raspberry Pi:
sudo apt update && sudo apt install -y cups python3-venv python3-pip

sudo useradd -r -s /usr/sbin/nologin printbot
sudo mkdir -p /opt/printbot /var/lib/printbot
sudo chown printbot:printbot /opt/printbot /var/lib/printbot

# Kopieer bestanden (via git of rsync)
git clone https://github.com/svdtoorren/printbot.git /tmp/printbot
sudo cp -r /tmp/printbot/src/printbot /opt/printbot/
sudo cp /tmp/printbot/requirements.txt /opt/printbot/
sudo cp /tmp/printbot/.env /opt/printbot/.env
sudo chown printbot:printbot /opt/printbot/.env
sudo chmod 640 /opt/printbot/.env

# Python venv + dependencies
sudo python3 -m venv /opt/printbot/.venv
sudo /opt/printbot/.venv/bin/pip install -r /opt/printbot/requirements.txt

# Systemd service
sudo cp /tmp/printbot/systemd/printbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now printbot
```

### Stap 5: Verificatie

```bash
# Service status
sudo systemctl status printbot

# Live logs
sudo journalctl -u printbot -f
```

Verwachte output bij succesvolle verbinding:

```
PrintBot Gateway starting
Gateway ID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
Server: wss://printgateway.toorren.nl/ws/gateway
Printer: YourPrinterName
Connecting to wss://printgateway.toorren.nl/ws/gateway
Connected to server
Heartbeat sent (printer=idle, uptime=5s)
```

Verifieer op de server dat de gateway online is:

```bash
curl -H "Authorization: Bearer <api-key>" \
  https://printgateway.toorren.nl/api/v1/gateways
# status: "online"
```

## Configuratie

| Variabele | Verplicht | Default | Beschrijving |
|-----------|-----------|---------|-------------|
| `GATEWAY_ID` | Ja | - | UUID van de geregistreerde gateway |
| `API_KEY` | Ja | - | API key van de gateway (begint met `pgw_`) |
| `WS_URL` | Ja | `wss://printgateway.toorren.nl/ws/gateway` | WebSocket URL van de server |
| `PRINTER_NAME` | Ja | - | CUPS printer naam |
| `STATE_DIR` | Nee | `/var/lib/printbot` | Directory voor SQLite database |
| `HEARTBEAT_INTERVAL` | Nee | `30` | Seconden tussen heartbeats |
| `RECONNECT_DELAY` | Nee | `5` | Initiele reconnect delay (sec) |
| `MAX_RECONNECT_DELAY` | Nee | `300` | Max reconnect delay (sec) |
| `DRY_RUN` | Nee | `false` | Simuleer printen (geen CUPS) |
| `LOG_LEVEL` | Nee | `INFO` | Log level |

## Updates deployen

```bash
ansible-playbook -i ansible/inventory.ini ansible/site.yml
```

De deployment behoudt je `.env` configuratie, herstart de service, en herinstalleert dependencies indien nodig.

## Troubleshooting

### Service start niet

```bash
sudo journalctl -u printbot -n 100
# Of test handmatig:
sudo -u printbot /opt/printbot/.venv/bin/python -m printbot.main
```

### "Missing required settings: gateway_id, api_key"

Controleer of `/opt/printbot/.env` correct is ingevuld en alle verplichte velden bevat.

### Kan niet verbinden met server

```bash
# Test of de server bereikbaar is
curl https://printgateway.toorren.nl/api/v1/health
# Verwacht: {"status":"ok"}

# Check of WSS poort open is
python3 -c "import websockets, asyncio; asyncio.run(websockets.connect('wss://printgateway.toorren.nl/ws/gateway'))"
```

Bij verbindingsproblemen controleert de gateway automatisch opnieuw met exponential backoff (5s → 10s → 20s → ... → max 300s).

### Printer wordt niet gevonden

```bash
lpstat -p                          # List printers
lpstat -t                          # Volledige CUPS status
echo "Test" | lp -d <printer>     # Test print
systemctl status cups              # CUPS service status
```

### Job wordt niet geprint (deduplicatie)

Als een job al eerder verwerkt is, wordt deze overgeslagen. Reset de deduplicatie database:

```bash
sudo rm /var/lib/printbot/state.db
sudo systemctl restart printbot
```

## Lokaal testen

Test de gateway lokaal met de mock WebSocket server:

```bash
# Terminal 1: Start mock server
python -m tests.mock_server

# Terminal 2: Start gateway (verbind met lokale mock server)
WS_URL=ws://localhost:8765/ws/gateway \
GATEWAY_ID=test-gateway \
API_KEY=test-key \
PRINTER_NAME=test-printer \
DRY_RUN=true \
python -m printbot.main
```

De mock server stuurt na 2 seconden een test print job.

## Repository structuur

```
printbot/
├── src/printbot/
│   ├── main.py                # Async entry point, signal handlers
│   ├── config.py              # Gateway configuratie
│   ├── websocket_client.py    # WS client, reconnect, heartbeat
│   ├── job_handler.py         # PDF decode, print, deduplicatie
│   ├── printing.py            # CUPS print_pdf + get_printer_status
│   └── ota_updater.py         # OTA update handler
├── tests/
│   ├── mock_server.py         # Mock WebSocket server
│   ├── test_job_handler.py    # Job handler unit tests
│   ├── test_printing.py       # Printing unit tests
│   └── inspect_state.py       # SQLite state database inspector
├── ansible/
│   ├── site.yml               # Main playbook
│   ├── inventory.ini          # Pi configuratie
│   └── roles/
│       ├── cups/              # CUPS installatie
│       └── printbot/          # PrintBot deployment
├── systemd/
│   └── printbot.service       # Systemd unit file
├── requirements.txt           # websockets, python-dotenv, requests, tenacity
└── .env.example               # Template voor configuratie
```

## Gerelateerd

- [printgateway-server](https://github.com/svdtoorren/printgateway-server) — Server component (FastAPI + PostgreSQL + WebSocket)
