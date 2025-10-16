# PrintBot (Exchange Online → Auto-Print via Raspberry Pi/CUPS)

Small, robust Python service that polls a Microsoft 365 mailbox via Microsoft Graph, filters by sender and folder, and prints plain-text content to a local CUPS printer (using `lp`).

## Why Graph (instead of IMAP)?
- Exchange Online disabled Basic Auth; IMAP only works with OAuth (XOAUTH2) and is more complex to set up and maintain.
- Microsoft Graph with application or delegated auth is the simplest, future‑proof method.
- Supports polling, delta queries, and robust filtering; no need to expose your LAN.

## High-level
- Runs on a Raspberry Pi (Debian/Raspberry Pi OS) with CUPS.
- Polls a specific folder (e.g., `PrintOrders`) for messages from a configured sender.
- Prints body (text/plain preferred; HTML is stripped to text if needed), then marks mail as read.
- Dedup via `internetMessageId` stored in a local SQLite DB.

## Auth Options (Microsoft Graph)
1. **Application permissions (recommended)** for a *shared mailbox or dedicated user*:
   - Create Azure App Registration.
   - Grant **Mail.ReadWrite** (Application).
   - Approve admin consent.
   - Restrict scope to a specific mailbox via an **Application Access Policy** (Exchange Online).
   - Configure `TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET`, and `MAILBOX_UPN` as environment variables.

2. **Delegated permissions** with **Device Code flow** (simple for single user):
   - Grant **Mail.ReadWrite** (Delegated).
   - First run prompts a device code in logs; finish sign‑in once.
   - Stores token cache on disk.

> This repo uses **Application permissions** by default via MSAL (confidential client).

## Quick start (manual)
```bash
# On the Pi:
sudo apt update
sudo apt install -y cups python3-venv avahi-daemon ipp-usb
sudo usermod -a -G lpadmin $USER
# Add your IPP/Bonjour printer via http://<pi>:631

# App
cd /opt
sudo mkdir -p /opt/printbot && sudo chown $USER:$USER /opt/printbot
cp -r /path/to/this/repo/* /opt/printbot/
cd /opt/printbot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure env
cp .env.sample .env
# edit .env with your tenant/client/secret, mailbox, folder, sender and printer

# Test run
python -m printbot.main
```

## systemd
```bash
sudo cp systemd/printbot.service /etc/systemd/system/printbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now printbot
sudo systemctl status printbot
```

## Ansible
Use `ansible/site.yml` to fully provision the Pi (CUPS + app + service). See `group_vars` to inject secrets or set as extra vars.

## Configuration (.env)
```
TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
CLIENT_SECRET=YOUR_CLIENT_SECRET
MAILBOX_UPN=orders@yourdomain.tld
MAIL_FOLDER=PrintOrders
FILTER_SENDER=orders@bestelsite.tld
PRINTER_NAME=YourCUPSPrinterName
POLL_SECONDS=60
STATE_DIR=/var/lib/printbot
```

## Security notes
- Prefer a **shared mailbox** and restrict app access via **Application Access Policy**.
- Keep the Pi LAN‑only; no inbound ports from the internet.
- Use least‑privilege Graph permissions and rotate client secrets regularly.

## License
MIT
