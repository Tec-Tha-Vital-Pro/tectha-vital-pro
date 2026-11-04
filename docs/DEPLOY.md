# Deploying Tec Tha Vital

Three ways to run it, cheapest first. Day-to-day operation (backups, updates, incidents) is in [RUNBOOK.md](RUNBOOK.md). The WhatsApp and hospital checklist is in [GO_LIVE.md](GO_LIVE.md).

| Option | Cost | Use it for | Real patient data? |
|---|---|---|---|
| A. Founder's laptop | Free | Demo meetings, sales | **No**, sample data only |
| B. Laptop plus a temporary tunnel | Free | Trying the Meta webhook with the WhatsApp **test number** | **No** |
| C. Small VPS in an Indian region, with Caddy HTTPS | Low monthly cost (check the provider's current price) | Pilot and live use | Yes, once the GO_LIVE checklist is done |

Whatever you choose, the server account, domain, WhatsApp account and data belong to **the hospital**. Tec Tha is added as an admin (PRODUCT_KNOWLEDGE.md, rule 3).

---

## A. Run the demo on the founder's laptop (free)

Needs Python 3.11 or newer ([python.org](https://www.python.org/downloads/); on Windows tick "Add python.exe to PATH").

**Mac / Linux**

```bash
./scripts/setup-and-run-demo.sh
```

**Windows:** double-click `scripts\setup-and-run-demo.bat`.

The script:

1. creates a virtual environment in `.venv` and installs the requirements (first run only, needs internet);
2. loads sample data for two branches into `data/demo.db` (a separate file, so a real database is never wiped);
3. creates an admin login called `demo`, with a password you type, or press Enter and it prints a random one **once**;
4. starts the server on http://127.0.0.1:8000 and opens the login page in your browser.

WhatsApp is forced into simulator mode: nothing is sent to real phones. Stop with Ctrl+C.

| Option (Mac/Linux / Windows) | Effect |
|---|---|
| `--port 8010` / `-Port 8010` | Use another port |
| `--keep-data` / `-KeepData` | Don't reload the sample data (it reloads by default, so dates are fresh for each demo) |
| `--fresh` / `-Fresh` | Delete the demo database first, including the `demo` login. Use this if you forgot the password |
| `--no-browser` / `-NoBrowser` | Don't open the browser |

Before a demo meeting: run the script once at home (downloads need internet), switch off sleep mode, and close other apps that use port 8000. The demo needs no internet after that.

**Docker on a laptop (optional):** `cp .env.example .env` and put a random value of 32+ characters in `TT_SESSION_SECRET`, then `docker compose up -d app`, then `docker compose exec app python -m app.seed` and `docker compose exec app python -m app.auth create-admin demo "Demo Admin"`. Open http://127.0.0.1:8000.

## B. Expose the laptop for Meta webhooks (temporary, test number only)

Meta only delivers webhooks to a public **HTTPS** URL. To let the WhatsApp **test number** reach the app on a laptop (for example to show real replies confirming appointments), use a tunnel. [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) (`cloudflared`) has a free "quick tunnel" that needs no account:

```bash
# 1. Start the app in live mode with the test number's credentials (in .env or exported)
TT_WHATSAPP_MODE=live TT_WHATSAPP_TOKEN=... TT_WHATSAPP_PHONE_ID=... TT_WHATSAPP_APP_SECRET=... \
TT_SESSION_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
TT_DB_PATH=data/demo.db .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2. In a second terminal
cloudflared tunnel --url http://127.0.0.1:8000
#    It prints a random https://<words>.trycloudflare.com address.

# 3. Meta → WhatsApp → Configuration → Webhook:
#    Callback URL  https://<words>.trycloudflare.com/webhooks/whatsapp
#    Verify token  your TT_WHATSAPP_VERIFY_TOKEN, then subscribe to "messages"
```

Close the tunnel (Ctrl+C) as soon as the test is done.

**Risks, and why this is never for real patients**

- **The whole app is on the public internet**, not just the webhook: the staff login page, `/api` and the patient app. Anyone who finds the URL can try passwords. Use a strong admin password, and keep the tunnel open only while you are testing.
- **The address changes every time** you restart `cloudflared`, so you must update the callback URL in Meta each time. Quick tunnels are meant for testing and come with no uptime guarantee.
- **Traffic passes through Cloudflare**, and the laptop holds the database. A laptop can be lost, stolen or reinstalled, and it has no backups or monitoring. Health data of real patients must not sit on it (DPDP Act; PRODUCT_KNOWLEDGE.md rule 12 "India hosting").
- **When the laptop sleeps, the webhook fails**, and Meta stops retrying after a while, so replies sent during that time are lost.
- Use only the free test number, with the few phone numbers you verify yourself, and sample data.

Other tunnels (ngrok, Tailscale Funnel) carry the same risks. For anything beyond a test, use option C.

## C. Small VPS in an Indian region with Caddy HTTPS

### Choosing the server

Any Linux VPS in an Indian region works. Examples of providers with Indian regions: DigitalOcean (Bengaluru), AWS (Mumbai, Hyderabad), Google Cloud (Mumbai, Delhi), Microsoft Azure (Pune and others), and Oracle Cloud (Mumbai, Hyderabad), which has an "Always Free" tier. Prices and free tiers change, so check the provider's own pricing page on the day and quote that to the hospital. Don't quote numbers from memory.

Size for one hospital with two branches: 1–2 GB RAM, 1 vCPU and 20 GB or more of disk is enough for this app (one Python process and SQLite). Choose **Ubuntu 24.04 LTS**. Open the firewall for ports 22, 80 and 443 only.

Open the account **in the hospital's name**, with the hospital's card, and add Tec Tha as a user.

You also need a domain or sub-domain, for example `care.yourhospital.in`, with a DNS **A record** pointing to the server's IP address.

### C1. Plain server with systemd (recommended: fewer moving parts)

```bash
# As root on the new server
apt update && apt install -y python3 python3-venv git curl caddy ufw
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw enable
timedatectl set-timezone Asia/Kolkata

# App user, code and folders
useradd --system --home /opt/tectha-care --shell /usr/sbin/nologin tectha
git clone <repository-url> /opt/tectha-care
chown -R tectha:tectha /opt/tectha-care
sudo -u tectha python3 -m venv /opt/tectha-care/.venv
sudo -u tectha /opt/tectha-care/.venv/bin/pip install -r /opt/tectha-care/requirements.txt
install -d -o tectha -g tectha -m 700 /var/lib/tectha-care /var/backups/tectha-care

# Settings (fill in real values; never commit this file)
install -d -m 750 -g tectha /etc/tectha-care
install -m 640 -g tectha /opt/tectha-care/.env.example /etc/tectha-care/env
nano /etc/tectha-care/env      # TT_SESSION_SECRET (32+ chars) is required here

# Service
cp /opt/tectha-care/deploy/tectha-care.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now tectha-care
curl -s http://127.0.0.1:8000/api/health          # {"ok":true}

# First admin (your own name; one login per person)
# (simulator mode here only so the command does not need the WhatsApp secrets; it just adds a login)
cd /opt/tectha-care && sudo -u tectha env TT_DB_PATH=/var/lib/tectha-care/tectha.db TT_WHATSAPP_MODE=simulator \
  .venv/bin/python -m app.auth create-admin <username> "<Full Name>"

# HTTPS
cp /opt/tectha-care/deploy/Caddyfile /etc/caddy/Caddyfile
echo 'TT_DOMAIN=care.yourhospital.in' >> /etc/default/caddy
systemctl restart caddy
```

Ubuntu's `caddy` package reads `/etc/default/caddy` through its systemd unit. If your Caddy install does not, add `Environment=TT_DOMAIN=...` with `systemctl edit caddy`. Caddy fetches a Let's Encrypt certificate on the first request and renews it itself.

Then:

```bash
cp /opt/tectha-care/deploy/backup.cron.example /etc/cron.d/tectha-care   # nightly backup + 5-minute health check
sudo -u tectha TT_DB_PATH=/var/lib/tectha-care/tectha.db TT_BACKUP_DIR=/var/backups/tectha-care \
  PYTHON=/opt/tectha-care/.venv/bin/python /opt/tectha-care/deploy/backup.sh   # first backup now
```

Then run the restore test from RUNBOOK section 3 once, before any real data goes in.

Don't run `python -m app.seed` on this server once real data is in: it deletes all patient, billing and message rows.

### C2. Docker (same server, if you prefer containers)

```bash
apt install -y docker.io docker-compose-v2 git
git clone <repository-url> /opt/tectha-care && cd /opt/tectha-care
cp .env.example .env && chmod 600 .env && nano .env      # real values, including TT_DOMAIN
docker compose --profile https up -d --build
docker compose exec app python -m app.auth create-admin <username> "<Full Name>"
docker compose ps                                         # app should become "healthy"
```

The database lives in the Docker volume `tectha-data`. Never run `docker compose down -v` or `docker volume prune`: both delete it. Backups: see the Docker lines in `deploy/backup.cron.example`.

### After either option

1. Open `https://care.yourhospital.in/login` and log in.
2. Point Meta's webhook to `https://care.yourhospital.in/webhooks/whatsapp` (GO_LIVE.md section 3).
3. Test by sending "hi" from a verified phone. It should appear as `received` on the Messages screen.
4. Set `TT_HEALTHCHECK_PING_URL` to a free uptime check (for example healthchecks.io) so someone gets an email if the server stops.
5. Write the server IP, domain, the location of the backup key, and who has access into the hospital's handover sheet.

## What is fixed by design

- **One app process per database.** Automations run inside the app; `--workers 1` is set in the Dockerfile and the systemd unit. Don't scale it by adding workers or a second container.
- **The app listens on 127.0.0.1 only.** Only Caddy is public. `--proxy-headers` lets the app know the visitor used HTTPS, so login cookies are marked secure.
- **SQLite on a local disk.** Never on a network drive or a synced folder.
- Caddy hides FastAPI's developer pages (`/docs`, `/redoc`, `/openapi.json`) in production.
