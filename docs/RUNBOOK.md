# Tec Tha Vital — Runbook

For whoever looks after the server: the Tec Tha admin, or the hospital's IT person.
Each section says how to **spot** the problem and how to **fix** it. Deployment itself is in [DEPLOY.md](DEPLOY.md).

Paths below assume the VPS layout from DEPLOY.md:

| What | Plain server (systemd) | Docker |
|---|---|---|
| App code | `/opt/tectha-care` | `/opt/tectha-care` (image built from it) |
| Settings and secrets | `/etc/tectha-care/env` | `/opt/tectha-care/.env` |
| Database | `/var/lib/tectha-care/tectha.db` | `/data/tectha.db` in the `tectha-data` volume |
| Backups | `/var/backups/tectha-care/` | `/data/backups/` in the volume, copied to `/var/backups/tectha-care/` |
| App log | `journalctl -u tectha-care` | `docker compose logs app` |
| HTTPS log | `journalctl -u caddy` | `docker compose logs caddy` |

The two screens you will use most (log in as an admin):

- **Messages** — every WhatsApp message in and out, with its status: `sent`, `failed` (with Meta's error text), `blocked_no_consent`, `received`, or `simulated` in simulator mode.
- **Audit** (`/audit`) — the last 200 actions: who did what and when. Automation problems appear here as `automation_error`.

The quick check that covers most of this page:

```bash
sudo -u tectha TT_DB_PATH=/var/lib/tectha-care/tectha.db /opt/tectha-care/deploy/healthcheck.sh
```

It checks that the app answers, the free disk space, failed WhatsApp sends and automation errors in the last 24 hours, and the time of the newest automation entry in the audit log. The cron example in `deploy/backup.cron.example` runs it every 5 minutes.

Logs and backups contain patient data (names, phone numbers, bills). Treat them like the database: don't email them, paste them into chat tools or copy them to personal laptops.

---

## 1. Start, stop, restart, status

| | systemd | Docker |
|---|---|---|
| Start | `sudo systemctl start tectha-care` | `docker compose --profile https up -d` |
| Stop | `sudo systemctl stop tectha-care` | `docker compose stop app` |
| Restart | `sudo systemctl restart tectha-care` | `docker compose restart app` |
| Status | `systemctl status tectha-care` | `docker compose ps` (look for `healthy`) |
| Follow log | `journalctl -u tectha-care -f` | `docker compose logs -f app` |

Laptop demo: `./scripts/setup-and-run-demo.sh` (Mac/Linux) or double-click `scripts\setup-and-run-demo.bat` (Windows). Stop with Ctrl+C.

**Always run exactly one copy of the app against a database.** The automations run inside the app process, so two copies (or `--workers 2`) send every reminder twice.

Restarting is safe at any time. Staff stay logged in (unless the session secret changed). Automations pick up where they left off on the next run, because each reminder is recorded when it is sent.

## 2. Update to a new version

1. Take a backup first (section 3) and note the current version: `git -C /opt/tectha-care rev-parse --short HEAD`.
2. Get the new code:
   ```bash
   cd /opt/tectha-care && sudo -u tectha git pull
   ```
3. Install and restart:
   - systemd: `sudo -u tectha .venv/bin/pip install -r requirements.txt && sudo systemctl restart tectha-care`
   - Docker: `docker compose build app && docker compose up -d app`
4. Check: `curl -s http://127.0.0.1:8000/api/health` returns `{"ok":true}`. Log in, open the Dashboard, Messages and Audit screens.
5. **Roll back** if something is wrong: `git checkout <previous version>`, then repeat step 3. If the new version changed the database and broke it, restore the backup from step 1 (section 3).

The database schema uses `CREATE TABLE IF NOT EXISTS`, so new tables are added on start. A release that changes an existing table must come with its own upgrade note. Ask the engineer before deploying it.

Do updates outside OPD hours. Reminders due during a short restart go out on the next run.

## 3. Backups and the restore test

**What runs:** `deploy/backup.sh` every night at 02:30 IST (cron). It takes a consistent copy while the app runs, checks the copy with SQLite's `integrity_check`, compresses it, and deletes copies older than 30 days (`TT_BACKUP_KEEP_DAYS`).

**A backup on the same server is not enough.** If the disk or the VPS account is lost, the backup goes with it. Copy each backup somewhere else:

- Set `TT_BACKUP_AGE_RECIPIENT` to encrypt backups with [age](https://github.com/FiloSottile/age) **before** they leave the server. Keep the private key offline, in the hospital's custody, with a printed copy in the hospital safe.
- Set `TT_BACKUP_RCLONE_REMOTE` to copy each backup to the hospital's own cloud storage with [rclone](https://rclone.org/) (for example Google Drive or an S3-compatible bucket in an Indian region).

**Check last night's backup worked:**

```bash
ls -lt /var/backups/tectha-care | head -3
tail -5 /var/backups/tectha-care/backup.log
```

**Take a backup now:**

```bash
# systemd
sudo -u tectha TT_DB_PATH=/var/lib/tectha-care/tectha.db TT_BACKUP_DIR=/var/backups/tectha-care \
  PYTHON=/opt/tectha-care/.venv/bin/python /opt/tectha-care/deploy/backup.sh
# Docker
docker compose exec app /app/deploy/backup.sh && docker compose cp app:/data/backups/. /var/backups/tectha-care/
```

**Monthly restore test (do it, and write the date down).** An untested backup may not restore.

```bash
/opt/tectha-care/deploy/restore.sh --test /var/backups/tectha-care/tectha-<date>.db.gz
```

It unpacks into a temporary file, runs `integrity_check` and prints the row counts and the time of the last audit entry. Compare them with the live system. The live database is not touched. Once a quarter, go further: restore onto a laptop and log in, using `TT_DB_PATH=/tmp/restored.db deploy/restore.sh --restore <file>`, then `TT_DB_PATH=/tmp/restored.db uvicorn app.main:app`. Delete the copy afterwards; it is real patient data.

**Real restore** (data lost or corrupted):

```bash
sudo systemctl stop tectha-care            # Docker: docker compose stop app
sudo -u tectha TT_DB_PATH=/var/lib/tectha-care/tectha.db \
  /opt/tectha-care/deploy/restore.sh --restore /var/backups/tectha-care/tectha-<date>.db.gz
sudo systemctl start tectha-care
```

The broken database is kept as `tectha.db.before-restore-<time>`; don't delete it until you are sure. Everything after the backup time is lost from Tec Tha (bills and payments can be re-imported from the billing software's CSV). Tell the owner which time window to re-check.

Docker restore: stop the app, then run the restore in a one-off container that mounts the volume, with the backup file copied into the volume first:

```bash
docker compose stop app
docker compose cp /var/backups/tectha-care/tectha-<date>.db.gz app:/data/backups/
docker compose run --rm --no-deps app /app/deploy/restore.sh --restore /data/backups/tectha-<date>.db.gz
docker compose start app
```

## 4. Rotate secrets

Rotate on a schedule (every 6 months), and **at once** if a secret may have leaked, a staff member with server access leaves, or a laptop holding `.env` is lost. Edit `/etc/tectha-care/env` (Docker: `.env`), then restart the app. Generate random values with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

| Secret | What else to change | Side effect |
|---|---|---|
| `TT_SESSION_SECRET` | nothing | Every staff member is logged out and logs in again |
| `TT_API_KEY` | Update the same key in the billing-software integration, n8n/Zapier website forms, and the telephony (Exotel/Knowlarity) missed-call webhook | Calls with the old key get `401` until they are updated. Do it in one sitting |
| `TT_WHATSAPP_TOKEN` | Create a new System User token in the hospital's Meta Business Settings; revoke the old one | none if done together |
| `TT_WHATSAPP_APP_SECRET` | Meta App → Settings → Basic → reset the App secret | Webhooks fail with `401` until the new value is in place |
| `TT_WHATSAPP_VERIFY_TOKEN` | Type the same value in Meta → WhatsApp → Configuration → Webhook, then click Verify | Only used when Meta verifies the webhook |
| `ANTHROPIC_API_KEY` (if AI is on) | Create a new key in the console, delete the old one | none |
| Staff passwords | Staff leaving: see the note below | |
| age backup key | Make a new key pair; old backups still need the old private key, so keep it until they expire | |

Note: in this version the app can add staff logins but has **no screen to reset a password or switch a login off**. Until that exists, ask the engineer to deactivate a departed staff member's login in the database on the same day, then rotate `TT_SESSION_SECRET` to end any open sessions.

After any rotation: log in, send one test message from the Messages screen in live mode, and check it shows `sent`.

## 5. Incidents

### 5.1 WhatsApp token expired or revoked

**Spot it**
- **Messages** screen: outgoing messages show status `failed`, and the error starts with `HTTP 401` and mentions `OAuthException`, often with `"code":190` (Meta's code for an expired or invalid access token).
- `healthcheck.sh` shows `WARN failed WhatsApp sends in last 24 h: <n>`.
- The owner says the 9 am report did not arrive.
- The **Audit** screen is not enough here: it records `message_sent` for every live attempt, failed or not. Use the Messages screen for the real status.

**Fix**
1. In the hospital's Meta Business Settings → Users → System users, create a token with the `whatsapp_business_messaging` and `whatsapp_business_management` permissions. Choose no expiry. The "temporary access token" on the app dashboard lasts only about 24 hours; never use it in production.
2. Put it in `TT_WHATSAPP_TOKEN` and restart the app.
3. Send a test message and check it shows `sent`.
4. Failed messages are **not** resent automatically. Filter the Messages screen for `failed` since the token expired and decide with the front desk which ones still matter (an appointment reminder for an appointment that has passed does not). Resend the ones that matter by hand.

Other `failed` errors: `HTTP 400` usually means a wrong number or a message outside WhatsApp's 24-hour customer-service window that needs an approved template. That is a message-content problem for the engineer, not a server problem.

### 5.2 Webhook failing (patient replies not arriving)

**Spot it**
- Patients reply "1" to confirm, but appointments stay `Booked`. No new `received` messages on the Messages screen.
- No `message_received` entries in **Audit**, while the front desk knows patients have replied.
- Meta → WhatsApp → Configuration shows webhook delivery errors, or Meta emails the app admin about failing webhooks.
- The HTTPS log shows `POST /webhooks/whatsapp` with status 401, 403, 404, 5xx, or no requests at all:
  ```bash
  journalctl -u caddy --since "1 hour ago" | grep webhooks/whatsapp     # Docker: docker compose logs caddy | grep webhooks
  ```

**Fix, by what you see**

| Symptom | Cause | Fix |
|---|---|---|
| `401` on POST | `TT_WHATSAPP_APP_SECRET` does not match the Meta app's App secret | Copy the App secret again (Meta App → Settings → Basic), restart |
| `403` when you click Verify in Meta | `TT_WHATSAPP_VERIFY_TOKEN` differs from what is typed in Meta | Make them the same, restart, click Verify |
| No requests reach Caddy | DNS changed, firewall closed 443, server down, or the tunnel URL changed (laptop setups) | `curl -I https://<domain>/login` from outside; check `ufw status`; for a tunnel, update the callback URL in Meta |
| TLS / certificate errors in Meta | Caddy could not renew the certificate (port 80 blocked, DNS wrong) | `journalctl -u caddy`; open port 80; fix DNS |
| `5xx` | App crashed or the database is full or locked | See 5.3 and 5.4; check `journalctl -u tectha-care` |
| Requests arrive with `200` but nothing happens | The phone number is subscribed to a different app or URL | In Meta, check the phone number's webhook subscription to `messages` |

Test the verify step from anywhere (use the real verify token):

```bash
curl "https://<domain>/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=<token>&hub.challenge=ok"   # prints: ok
```

Replies that arrived while the webhook was broken may never reach the app (Meta retries for a limited time only). Ask the front desk to check the WhatsApp Business inbox or Meta's message history for that window.

### 5.3 Disk full

**Spot it**
- `healthcheck.sh` shows `FAIL disk free only ... MB`.
- App log shows `sqlite3.OperationalError: database or disk is full`. Pages give errors, and nothing new appears in Audit.
- `df -h /var/lib/tectha-care` shows 100%, or close to it.

**Fix**
1. Find what is using the space: `sudo du -xh / --max-depth=2 2>/dev/null | sort -h | tail -15`.
2. Usual causes and safe clean-ups:
   - Old backups: check `/var/backups/tectha-care`. Lower `TT_BACKUP_KEEP_DAYS` **only after** confirming off-server copies exist.
   - System logs: `sudo journalctl --vacuum-size=200M`.
   - Docker: `docker system prune` (removes stopped containers and unused images; **never** add `--volumes`, which can delete the database volume).
   - Old `tectha.db.before-restore-*` files, once you are sure they are not needed.
3. Restart the app, then check Audit shows new entries.
4. Then run `deploy/restore.sh --test` on a fresh backup to confirm the database was not damaged.

Prevention: keep at least 1 GB free (the healthcheck's default limit); choose a VPS disk several times larger than database plus backups.

### 5.4 Database locked

**Spot it**
- App log shows `sqlite3.OperationalError: database is locked`. Some saves fail, or pages hang for about 10 seconds and then fail.
- Often coincides with someone running a manual query, a backup to a slow disk, or a second copy of the app.

**Fix**
1. See who has the file open: `sudo fuser -v /var/lib/tectha-care/tectha.db` (or `lsof`).
2. Exactly one app process should appear. Stop any extra copy: an old `uvicorn` from a terminal, a second container, or a unit started with more than one worker. Make sure the database is not also used by the laptop demo.
3. Close any DB browser or `sqlite3` shell holding it.
4. Restart the app: `sudo systemctl restart tectha-care`.
5. Never put the database on a network drive (NFS, SMB, Dropbox or OneDrive folders). SQLite locking is unreliable there, and the file can be corrupted.

If it keeps happening with only one app process, collect the log lines and ask the engineer. Write traffic may be outgrowing SQLite's single writer.

### 5.5 Scheduler (automations) stopped

The scheduler runs inside the app every `TT_SCHEDULER_INTERVAL` seconds (default 60). It sends reminders, dues messages, follow-ups and feedback requests, raises unbilled and claim alerts, and sends the 9 am report.

**Spot it**
- **Audit** shows `automation_error` entries (actor `automation`): the scheduler is running, but one automation keeps failing. The detail column has the error.
- No new entries from actor `automation`, and no new automated messages on the Messages screen (reminder templates such as `appt_reminder_24h`), for several hours of OPD time when appointments exist. `healthcheck.sh` prints the newest automation entry. A quiet night is normal; a quiet morning is not.
- The owner's 9 am report did not arrive (also check 5.1).
- Settings → **Run automations** suddenly sends a batch of reminders that should already have gone. That means the background loop was not running.

**Fix**
1. Check the setting: `TT_SCHEDULER` must be `on` (or unset) in the env file.
2. Restart the app. The scheduler starts with the app: `sudo systemctl restart tectha-care`.
3. If there are `automation_error` entries, read the detail text and the app log (`journalctl -u tectha-care | grep -A20 Traceback`). A database problem (5.3, 5.4) is the usual cause; anything else goes to the engineer with the error text.
4. After the fix, press **Run automations** once and check Messages for the expected reminders.

## 6. Escalation

1. Tec Tha admin on call (name and number to be filled in at go-live).
2. Engineer, for code errors (send the error text and time from the log, never the database).
3. For a suspected data leak or unauthorised access: stop, don't delete anything, tell the hospital's data protection contact the same day, and keep the logs.
