# Tec Tha Vital

Hospital automation by **Tec Tha**. It connects a hospital's existing CRM and billing software, talks to patients on WhatsApp, and gives the owner one view of every branch.

It does not replace the hospital's software. It reads from it (CSV export or API), adds the automations, and writes back only what it is asked to.

## What it does

| Area | Features |
|---|---|
| Patients | One patient ID across all branches (matched on mobile number), consent capture, full timeline |
| Front desk | One inbox for enquiries from WhatsApp, phone, website, ads and Practo; missed-call tasks with a 15-minute deadline |
| Appointments | Booking with token numbers, WhatsApp reminders 24 h and 2 h before, confirm / reschedule / cancel by reply |
| Billing | Pending dues with escalating WhatsApp reminders and payment links, unbilled-service detection, payments |
| Insurance | Claims board with alerts when pre-auth passes 1 hour or final approval passes 3 hours (IRDAI 2024 limits) |
| After-care | Follow-up reminders, feedback requests, complaint tasks for low scores, Google review link for high scores |
| Owner | Dashboard for both branches and a 9 am WhatsApp report |
| Safety | Staff logins with roles, CSRF protection, consent check before every message, audit log of every send and change |

## Run it on a laptop (free)

Needs Python 3.11 or newer.

```bash
pip install -r requirements.txt
```

```bash
python -m app.seed
```

```bash
TT_ADMIN_PASSWORD='choose-a-password' python -m app.auth create-admin admin "Tec Tha Admin"
```

```bash
TT_API_KEY='make-up-a-long-key' uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 and log in as `admin`.

`python -m app.seed` fills the system with realistic sample data for two branches. Run it again any time to reset the demo.

## Modes

WhatsApp runs in **simulator mode** by default: messages are stored and shown on the Messages screen, and nothing is sent. Use the "Simulate a patient message" box to reply as a patient (try `1` after a reminder, or `2` after a feedback request).

To send real WhatsApp messages, see [docs/GO_LIVE.md](docs/GO_LIVE.md).

## Settings (environment variables)

| Variable | Purpose | Default |
|---|---|---|
| `TT_DB_PATH` | SQLite database file | `data/tectha.db` |
| `TT_API_KEY` | Key for `/api` (billing software, website forms). The API is off until set | empty |
| `TT_SESSION_SECRET` | Signs staff login cookies. Required for live use | dev value |
| `TT_WHATSAPP_MODE` | `simulator` or `live` | `simulator` |
| `TT_WHATSAPP_TOKEN`, `TT_WHATSAPP_PHONE_ID`, `TT_WHATSAPP_APP_SECRET` | WhatsApp Cloud API credentials (live mode) | empty |
| `TT_WHATSAPP_VERIFY_TOKEN` | Webhook verification token you choose in Meta's dashboard | `tectha-verify` |
| `TT_OWNER_PHONE` | Receives the 9 am report | sample number |
| `TT_PAYMENT_LINK_BASE` | Base URL for payment links in dues reminders | example URL |
| `TT_REVIEW_LINK` | Google review link sent after good feedback | example URL |
| `TT_SCHEDULER` / `TT_SCHEDULER_INTERVAL` | Automations on/off and how often they run (seconds) | `on` / `60` |

The app refuses to start in live mode without the WhatsApp credentials, the webhook secret and a real session secret.

## Connecting the hospital's software

- **CSV import (works with any billing software):** Settings → Import. Sample files are in `docs/samples/`.
- **API:** send bills, payments, leads, orders and claims to `/api/...` with header `X-API-Key`. Website forms and ad leads can post to `/api/leads` through n8n or Zapier.
- **Missed calls:** point the telephony provider's (Exotel, Knowlarity) missed-call webhook to `/webhooks/missed-call`.

## Tests

```bash
python -m pytest -q
```

## Project layout

```
app/
  main.py            app entry point
  schema.sql, db.py  database
  patients.py        one patient ID across branches, consent
  messaging.py       WhatsApp sending (simulator or live), consent check
  automations.py     reminders, dues, follow-ups, feedback, claim and unbilled alerts, owner report
  scheduler.py       runs the automations every minute
  billing.py         bills, payments, orders, claims
  metrics.py         dashboard numbers
  auth.py            staff logins and roles
  integrations/      CSV import
  routes/            web screens (ui), REST API (api), WhatsApp and telephony webhooks
docs/                demo script, go-live guide, sample CSVs
tests/
```
