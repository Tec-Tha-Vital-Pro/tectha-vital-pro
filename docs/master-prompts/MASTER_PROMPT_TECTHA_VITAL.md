# Master prompt — Tec Tha Vital (Hospital OS, pilot edition)

Paste everything below the line into a new Claude Code session (or give it to any senior engineer) to rebuild the pilot from scratch. The finished, QA-approved version is on GitHub: `sanjay5777/tectha-vital`, branch `pilot-v1.0`.

---

You are the lead engineer for **Tec Tha Consultancy Services** ("Technology That Shapes the Future."). Build **Tec Tha Vital — Hospital OS**, a pilot product for a mid-size Indian hospital group with **2 branches** that already uses a CRM and a separate billing software. We do not replace their software: we connect CRM, billing and WhatsApp around the patient, automate follow-ups, and give the owner one view of both branches. Budget is near zero: everything must run free on a laptop or a small VPS.

## Non-negotiable rules
1. No message to a patient without consent (DPDP Act 2023). Replies to a patient who wrote first are allowed. STOP withdraws consent.
2. No medical advice from software or AI. AI is decision support; a person approves every clinical or financial action.
3. No silent failures: failed sends stored as `failed` with the reason, blocked sends as `blocked_no_consent`, automation errors in the audit log.
4. Every staff member has their own login, sees only their role and branch, and every change is audited.
5. Accounts and data in the hospital's name; India hosting.
6. Indian context: ₹ in lakh format, IST, mobiles stored as 91XXXXXXXXXX, UPI, TPA/PM-JAY, ABHA, IRDAI limits (1 h cashless decision, 3 h discharge approval).
7. Never invent numbers in client material; label sample data as sample.
8. Quiet hours: no automated patient messages 9 pm–8 am IST. No health details (tests, specialties, itemised bills) in WhatsApp text.

## Stack
Python 3.11+, FastAPI, Jinja2 server-rendered pages, SQLite (stdlib sqlite3), no front-end framework, one CSS file and one small JS file, installable PWA. Tests with pytest; end-to-end with Playwright (Node). Optional AI: Anthropic Claude via the official `anthropic` SDK (default model `claude-opus-5-5`, structured outputs, prompt caching), off unless `TT_AI=on` and an API key exist.

## Data model (SQLite)
branches, patients (one ID `TT-000123` across branches, phone unique, consent + consent_at, session_version), doctors, leads (source, branch, status New/Contacted/Booked/Converted/Lost, first_reply_seconds), appointments (status Booked/Confirmed/Cancelled/Visited/NoShow, token, reminder_24h/2h_sent_at, feedback_sent_at), bills, bill_items, payments, dues_reminders (stage), orders (services delivered; NULL bill_id = unbilled), claims (stages PreAuthRequested/PreAuthApproved/FinalSent/Settled/Denied, stage_changed_at), followups, feedback, messages (direction, template, status simulated/sent/failed/blocked_no_consent/received), tasks (kinds missed_call/complaint/claim_stuck/unbilled/followup_call; UNIQUE kind+related), audit_log, settings, users (roles owner/admin/frontdesk/billing/doctor, branch_id, pbkdf2 hash, session_version, active), processed_webhooks (dedupe Meta retries).

## Modules
- `patients.py` find_or_create by phone, consent set/withdraw (audited).
- `messaging.py` send(): consent check → simulator (store) or live WhatsApp Cloud API; inside 24 h window send text, else an approved template (`wa_templates.py`), else store failed with reason; login codes never stored readable in live mode.
- `automations.py` idempotent jobs: 24 h/2 h appointment reminders (reply 1 confirm / 2 reschedule task / 3 cancel), feedback requests, dues reminders at 3/10/21 days with ≥5 days gap and a payment link then a call task, follow-up reminders, unbilled detection (>2 h), stuck claims (IRDAI limits), 9 am owner report (+ optional AI insight with every number verified), per-automation on/off, quiet hours. `scheduler.py` runs them every 60 s and logs errors.
- `billing.py` bills, payments (no overpayment), add order to bill, claims stages, dues list.
- `routes/webhooks.py` Meta verify + signed POST only (dedupe by message id), emergency keyword rule first (English/Hindi/Hinglish → 108 reply + urgent task), STOP, feedback 1–5 (≤3 complaint task; review link offered to all), reminder replies, unknown number → lead + welcome; simulator endpoint for staff (login + CSRF) or API key; missed-call webhook (API key).
- `routes/api.py` REST with X-API-Key: leads, patients, bills, payments, orders, claims, dashboard, health (scheduler status).
- `integrations/csv_import.py` patients and bills CSV, bad rows reported, re-import idempotent, 5 MB limit.
- `auth.py` sessions (itsdangerous, 8 h, random per-install secret if none set), CSRF on every POST, login throttling (5 per 15 min), roles + branch isolation helper `_own()` (404 for other-branch records), owner role read-only billing, admin user management, CLI create-admin/reset-password/deactivate.
- `routes/ui.py` staff screens: dashboard (attention list, KPIs vs yesterday, 7-day collections chart, funnel, owner report preview), enquiries (filters, Book/Call/WhatsApp), appointments (tokens, Not confirmed/Confirmed/Seen, undo), patients + profile timeline, billing (search, dues, Send reminder, Record payment, unbilled Add to bill), claims kanban (time-in-stage limits), tasks, messages (WhatsApp-style, staff reply box, simulator panel), settings (names, automation switches, users), import, audit.
- `routes/patient_app.py` patient PWA at /my: OTP login (hashed, 5 min, 5 attempts, rate limits, same reply for unknown numbers), home ticket, booking with real free slots, bills/pay (demo only in simulator mode), reports, profile consent toggle, feedback, English/Hindi.
- `security.py` headers (CSP same-origin scripts, nosniff, frame DENY, referrer, permissions, HSTS on HTTPS, no-store HTML, noindex).
- `seed.py` realistic two-branch demo data relative to now.

## Design
Product name and tagline from one setting. Brand: Graphite Ink #121214, Chrome Silver #E7E9EC, Signal Violet #9B5DE5 (actions only), Slate Mute #9CA2AC, Off White #F5F5F7; status green/amber/red always with a word or symbol; Geist / Source Sans 3 / mono for numbers; graphite sidebar, white cards with hairlines; responsive 360–1920, 44 px touch targets, light/dark, WCAG AA, every patient page noindex.

## Deliverables and acceptance
- 160+ pytest tests green; Playwright demo flow (login → dashboard → run automations → simulate replies → billing reminder/payment/add to bill → claims → patient OTP/book/pay) passes 23/23.
- Docs: README, GO_LIVE, DEMO_SCRIPT, RUNBOOK, DEPLOY, PRD, ROADMAP, COMPLIANCE, SECURITY_REVIEW, TEST_PLAN, implementation and sales kits.
- One-command demo scripts for Mac/Linux and Windows; Dockerfile, Caddy, systemd, backups.

## Way of working
Act as a team of senior roles (product, domain/compliance, architect, backend, AI, design, front end, QA, security, DevOps, implementation, sales); give each role separate files; review every change; commit small, tested steps.
