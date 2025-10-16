# PrintBot - Automated Email-to-Print Service

**Automatisch emails printen vanaf Exchange Online via een Raspberry Pi**

PrintBot is een Python service die een Microsoft 365 mailbox monitort via Microsoft Graph API, emails filtert op afzender en map, en de inhoud automatisch print naar een CUPS printer. Perfect voor het automatiseren van bestelbon-printing vanuit een online systeem.

## 📋 Overzicht

- **Platform**: Raspberry Pi (Debian/Raspberry Pi OS) met CUPS
- **Email**: Microsoft 365 / Exchange Online via Graph API
- **Authenticatie**: Azure App Registration (Application permissions)
- **Deployment**: Ansible (geautomatiseerd) of manueel
- **Print**: Via CUPS (`lp` command)
- **Deduplicatie**: SQLite database met `internetMessageId`

## 🎯 Waarom Microsoft Graph (en niet IMAP)?

- Exchange Online heeft Basic Auth uitgeschakeld
- IMAP met OAuth2 (XOAUTH2) is complex en onderhoudsintensief
- Microsoft Graph is de officiële, toekomstvaste methode
- Ondersteunt filtering, polling en delta queries
- Geen inbound firewall regels nodig

## 📦 Prerequisites

### Vereisten op je computer (controller)

- **Ansible** >= 9.0
- **Python** >= 3.9
- **SSH toegang** tot je Raspberry Pi
- **Git** (om deze repository te clonen)

### Vereisten voor de Raspberry Pi

- **Raspberry Pi OS** (Bookworm of nieuwer) of Debian 12+
- **SSH server** enabled
- **Netwerk verbinding** (WiFi of ethernet)
- **USB printer** of netwerk printer (IPP/Bonjour)
- **Sudo rechten** voor de SSH user (standaard: `pi`)

### Vereisten in Microsoft Azure

- **Azure AD / Entra ID tenant** (Microsoft 365 account)
- **Rechten** om App Registrations aan te maken
- **Admin consent** rechten voor Graph API permissions
- Optioneel: **Application Access Policy** voor mailbox-beperking

---

## 🚀 Stap-voor-stap installatie

### Stap 1: Azure App Registration aanmaken

1. **Ga naar Azure Portal**: https://portal.azure.com
2. **Navigeer naar**: Azure Active Directory → App registrations → New registration
3. **Vul in**:
   - Name: `PrintBot`
   - Supported account types: `Accounts in this organizational directory only`
   - Redirect URI: (leeg laten)
4. **Klik**: Register

5. **Noteer de volgende waarden** (nodig voor `.env`):
   - **Application (client) ID**: te vinden op de Overview pagina
   - **Directory (tenant) ID**: te vinden op de Overview pagina

6. **Client Secret aanmaken**:
   - Ga naar: Certificates & secrets → New client secret
   - Description: `PrintBot Secret`
   - Expires: 24 months (of naar voorkeur)
   - Klik: Add
   - **⚠️ BELANGRIJK**: Kopieer de **Value** direct (wordt maar 1x getoond)

7. **API Permissions instellen**:
   - Ga naar: API permissions → Add a permission
   - Kies: Microsoft Graph → Application permissions
   - Zoek en selecteer: **Mail.ReadWrite**
   - Klik: Add permissions
   - **Klik**: Grant admin consent for [Your Organization]
   - Bevestig met: Yes

8. **Optioneel - Mailbox beperken** (aanbevolen voor beveiliging):
   ```powershell
   # In Exchange Online PowerShell
   New-ApplicationAccessPolicy -AppId <CLIENT_ID> -PolicyScopeGroupId <MAILBOX_EMAIL> -AccessRight RestrictAccess -Description "PrintBot access"
   ```

### Stap 2: Repository clonen en configureren

```bash
# Clone de repository
git clone https://github.com/yourusername/printbot.git
cd printbot

# Kopieer de .env template
cp .env.example .env
```

### Stap 3: .env bestand invullen

Open `.env` in een text editor en vul de waarden in:

```bash
nano .env
```

**Vul in met je Azure en email gegevens:**

```bash
# Microsoft Azure AD / Entra ID Application credentials
TENANT_ID=a7f0f509-xxxx-xxxx-xxxx-xxxxxxxxxxxx    # Van stap 1.5
CLIENT_ID=e102f781-xxxx-xxxx-xxxx-xxxxxxxxxxxx    # Van stap 1.5
CLIENT_SECRET=bkl8Q~xxxxxxxxxxxxxxxxxxxxx         # Van stap 1.6

# Exchange Online mailbox to monitor
MAILBOX_UPN=orders@yourdomain.tld                 # Het email adres om te monitoren

# Mail folder name to poll (case-sensitive)
MAIL_FOLDER=PrintOrders                           # Naam van de mail folder

# Filter: only process emails from this sender
FILTER_SENDER=orders@supplier.com                 # Alleen emails van deze afzender

# CUPS printer name (get via 'lpstat -p' on the Pi)
PRINTER_NAME=YourPrinterName                      # Naam van je printer in CUPS

# Polling interval in seconds
POLL_SECONDS=60                                   # Controleer elke 60 seconden

# Directory for state database (SQLite)
STATE_DIR=/var/lib/printbot                       # Locatie voor database
```

**⚠️ BELANGRIJK**:
- Het `.env` bestand bevat gevoelige credentials
- Dit bestand staat al in `.gitignore` en wordt **niet** gecommit naar Git
- Het wordt lokaal gelezen door Ansible en naar de Pi gekopieerd tijdens deployment

### Stap 4: Raspberry Pi voorbereiden

1. **Installeer Raspberry Pi OS** op je Pi (via Raspberry Pi Imager)
2. **Enable SSH** tijdens installatie of via `sudo raspi-config`
3. **Zet een vast IP adres** (optioneel maar aanbevolen)
4. **Test SSH verbinding**:
   ```bash
   ssh pi@<raspberry-pi-ip>
   ```

### Stap 5: Ansible inventory configureren

Open `ansible/inventory.ini`:

```bash
nano ansible/inventory.ini
```

**Pas het IP-adres aan** naar jouw Raspberry Pi:

```ini
[printpi]
printbot ansible_host=192.168.1.100 ansible_user=pi
```

**Vervang `192.168.1.100`** met het IP-adres van je Pi.

### Stap 6: Ansible installeren (als nog niet geïnstalleerd)

```bash
# macOS
brew install ansible

# Ubuntu/Debian
sudo apt update
sudo apt install -y ansible

# Python pip
pip install "ansible>=9,<11"
```

### Stap 7: Deployment uitvoeren

#### Optioneel: Preflight check (valideer paden)

```bash
ansible-playbook ansible/verify_paths.yml
```

Dit valideert dat alle benodigde bestanden aanwezig zijn voordat je deploy.

#### Volledige deployment naar de Pi

```bash
ansible-playbook -i ansible/inventory.ini ansible/site.yml
```

**Wat gebeurt er tijdens deployment?**

1. ✅ CUPS en dependencies worden geïnstalleerd
2. ✅ `printbot` system user wordt aangemaakt
3. ✅ Bronbestanden worden gevalideerd (preflight)
4. ✅ `/opt/printbot` wordt schoongemaakt en opnieuw aangemaakt
5. ✅ Python code en dependencies worden gekopieerd
6. ✅ Virtual environment wordt aangemaakt
7. ✅ Requirements worden geïnstalleerd
8. ✅ `.env` configuratie wordt gekopieerd
9. ✅ Systemd service wordt geïnstalleerd en gestart
10. ✅ Service wordt enabled voor autostart bij boot

**Output bij succes:**

```
PLAY RECAP *********************************************************************
printbot     : ok=24   changed=8    unreachable=0    failed=0    skipped=0
```

### Stap 8: Printer configureren in CUPS

1. **Open CUPS web interface**:
   ```
   http://<raspberry-pi-ip>:631
   ```

2. **Ga naar**: Administration → Add Printer
3. **Login** met Pi credentials
4. **Selecteer je printer** (USB of netwerk)
5. **Geef een naam** (deze naam gebruik je in `.env` als `PRINTER_NAME`)
6. **Test de printer**:
   ```bash
   ssh pi@<raspberry-pi-ip>
   lpstat -p
   echo "Test print" | lp -d <printer-name>
   ```

### Stap 9: Service verificatie

```bash
# Check service status
ansible printbot -i ansible/inventory.ini -m shell -a "systemctl status printbot" -b

# Check recent logs
ansible printbot -i ansible/inventory.ini -m shell -a "journalctl -u printbot -n 50" -b

# Of via SSH
ssh pi@<raspberry-pi-ip>
sudo systemctl status printbot
sudo journalctl -u printbot -f  # Live logs
```

**Verwachte output bij succesvolle start:**

```
● printbot.service - PrintBot - Auto print Exchange Online orders
   Loaded: loaded (/etc/systemd/system/printbot.service; enabled)
   Active: active (running) since ...
```

---

## 🔄 Updates deployen

Wanneer je code wijzigt in de repository:

```bash
# 1. Test lokaal of paden kloppen
ansible-playbook ansible/verify_paths.yml

# 2. Deploy naar Pi
ansible-playbook -i ansible/inventory.ini ansible/site.yml
```

De deployment:
- Behoudt je `.env` configuratie (persistent)
- Herstart automatisch de service na code-wijzigingen
- Reinstalleert Python dependencies indien nodig

---

## 🔍 Troubleshooting

### Service start niet

```bash
# Check logs
sudo journalctl -u printbot -n 100

# Check .env bestand
sudo cat /opt/printbot/.env

# Check Python errors
sudo -u printbot /opt/printbot/.venv/bin/python -m printbot.main
```

### "Unable to get authority configuration"

- **Oorzaak**: `TENANT_ID` is incorrect of placeholder waarde
- **Oplossing**: Controleer `.env` en redeploy

### "400 Bad Request" op Graph API

- **Oorzaak**: Mail folder ID of filter parameter is incorrect
- **Oplossing**: Verifieer dat `MAIL_FOLDER` exact overeenkomt (case-sensitive)

### "Could not find printer"

```bash
# List beschikbare printers
lpstat -p

# Test printer direct
echo "Test" | lp -d <printer-name>

# Update PRINTER_NAME in .env en redeploy
```

### Printer prints niet

- Check CUPS status: `systemctl status cups`
- Check printer status: `lpstat -t`
- Test via CUPS web interface: http://pi-ip:631
- Check printer drivers: `lpinfo -m | grep -i <your-printer-brand>`

### Ansible SSH connection failed

```bash
# Test SSH connectie
ssh pi@<raspberry-pi-ip>

# Test met Ansible
ansible printbot -i ansible/inventory.ini -m ping

# Gebruik password authentication (als SSH keys niet werken)
ansible-playbook -i ansible/inventory.ini ansible/site.yml --ask-pass
```

---

## 🛠️ Manuele installatie (zonder Ansible)

Als je liever manueel installeert:

```bash
# Op de Raspberry Pi:
sudo apt update
sudo apt install -y cups python3-venv python3-pip build-essential

# Maak printbot user
sudo useradd -r -s /usr/sbin/nologin printbot

# Maak directories
sudo mkdir -p /opt/printbot /var/lib/printbot
sudo chown printbot:printbot /opt/printbot /var/lib/printbot

# Kopieer code (via git of rsync)
git clone https://github.com/yourusername/printbot.git /tmp/printbot
sudo cp -r /tmp/printbot/src/printbot /opt/printbot/
sudo cp /tmp/printbot/requirements.txt /opt/printbot/

# Kopieer .env (zorg dat deze lokaal al ingevuld is)
sudo cp /tmp/printbot/.env /opt/printbot/.env
sudo chown printbot:printbot /opt/printbot/.env
sudo chmod 640 /opt/printbot/.env

# Python venv
cd /opt/printbot
sudo python3 -m venv .venv
sudo /opt/printbot/.venv/bin/pip install -r requirements.txt

# Systemd service
sudo cp /tmp/printbot/systemd/printbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now printbot
sudo systemctl status printbot
```

---

## 🔒 Security best practices

1. **Gebruik een dedicated mailbox** (niet je persoonlijke mailbox)
2. **Beperk app toegang** via Application Access Policy in Exchange Online
3. **Rotate secrets** regelmatig (elke 6-12 maanden)
4. **Houd de Pi LAN-only** (geen inbound ports van internet)
5. **Update regelmatig**: `sudo apt update && sudo apt upgrade`
6. **Monitor logs** op verdachte activiteit

---

## 📁 Repository structuur

```
printbot/
├── .env.example           # Template voor configuratie
├── .env                   # Jouw configuratie (git-ignored)
├── src/
│   └── printbot/          # Python package
│       ├── main.py        # Entry point
│       ├── graph_client.py
│       ├── processor.py
│       └── ...
├── requirements.txt       # Python dependencies
├── systemd/
│   └── printbot.service   # Systemd unit file
├── ansible/
│   ├── site.yml           # Main playbook
│   ├── inventory.ini      # Pi configuratie
│   ├── verify_paths.yml   # Preflight validatie
│   ├── ansible.cfg        # Ansible settings
│   └── roles/
│       ├── cups/          # CUPS installatie
│       └── printbot/      # PrintBot deployment
│           ├── tasks/
│           │   ├── main.yml      # Hoofd taken
│           │   └── preflight.yml # Path validatie
│           ├── handlers/
│           │   └── main.yml      # Service restarts
│           └── templates/
│               └── env.j2        # (DEPRECATED: use .env)
└── .github/
    └── workflows/
        └── ansible-verify-paths.yml  # CI: pad validatie
```

---

## 🧪 GitHub Actions CI

De repository bevat een GitHub Actions workflow die automatisch valideert dat alle benodigde paden aanwezig zijn:

- Runt bij elke push/PR
- Valideert `src/printbot/`, `requirements.txt`, `systemd/printbot.service`, `.env`
- Voorkomt deployment met ontbrekende bestanden

---

## 📄 Licentie

MIT License - zie LICENSE bestand voor details

---

## 🙋 Support & bijdragen

- **Issues**: https://github.com/yourusername/printbot/issues
- **Pull requests**: Altijd welkom!
- **Documentatie**: Suggesties welkom via issues

---

## 📚 Referenties

- [Microsoft Graph API Documentation](https://learn.microsoft.com/en-us/graph/api/overview)
- [Azure App Registration](https://learn.microsoft.com/en-us/azure/active-directory/develop/quickstart-register-app)
- [CUPS Documentation](https://www.cups.org/doc/admin.html)
- [Ansible Documentation](https://docs.ansible.com/)
