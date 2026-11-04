# Tec Tha Care Connect — Product Knowledge Base

Every Tec Tha team member and agent reads this before working. If a decision changes, update this file.

## 1. Company and product

- **Tec Tha** is an IT and AI automation company. The first product is **Tec Tha Care Connect**, automation for mid-size Indian hospitals.
- **First client (prospect):** a hospital group with **2 branches** that already uses a **CRM** and **separate billing software**. We don't yet know which CRM or billing product; the discovery questions are in section 9.
- **Position:** we don't replace the hospital's software. We **connect** the CRM, billing software and WhatsApp around the patient, and add automations and one owner view across branches.
- **Budget reality:** Tec Tha has no funds yet. Everything must run on free or near-free tools: a laptop or small VPS, SQLite, the WhatsApp Cloud API test number, and open-source tools.

## 2. Problems we solve (from the operations audit)

| # | Problem | Fix in product |
|---|---|---|
| 1 | Unbilled services and pending dues | Unbilled detection, dues reminders with payment link |
| 2 | Enquiries not followed up | One inbox for all sources, instant WhatsApp reply, missed-call tasks |
| 3 | Appointment no-shows | Reminders 24 h and 2 h before, confirm/reschedule/cancel by reply |
| 4 | Insurance/TPA delays | Claims board, alert past IRDAI limits (1 h cashless decision, 3 h discharge approval) |
| 5 | Patients lost after first visit | Follow-up reminders, feedback, care programmes |
| 6 | No combined view of 2 branches | Owner dashboard and 9 am WhatsApp report |
| 7 | Same patient registered twice | One patient ID (TT-xxxxxx) matched on mobile number |
| 8 | Manual re-entry | CSV import and REST API from billing; webhooks |
| 9 | Long OPD queues | Token numbers and queue messages (planned) |
| 10 | Stock-outs | Planned, phase 3 |
| 11 | Weak online reputation | Review link after high feedback scores; low scores go to the manager |
| 12 | Data privacy gaps | Consent before messages, role logins, audit log, India hosting |

## 3. Patient-side must-haves (from the patient-side audit)

WhatsApp booking and auto-reply · reminders and one-tap reschedule · one ID across branches · live token updates · reports and bills on WhatsApp · cost estimate and itemised bill · follow-up reminders · feedback and complaint tracking. Loyalty features to add later: family accounts, care programmes, health packages, the mother and child journey, referral rewards.

## 4. Market (from the market audit)

- Global EHRs (Epic, Oracle Health, MEDITECH) are too costly for this segment; use them only as a feature benchmark.
- Indian HMS products (Insta by Practo, KareXpert, eHospital, MediXcel and others) are strong on billing, pharmacy and lab, and weak on patient communication.
- CRMs (LeadSquared, Zoho, Salesforce Health Cloud) and WhatsApp platforms (Gupshup, Interakt, AiSensy, WATI) don't connect to billing without custom work.
- **Our gap:** the connecting layer, plus hospital-specific workflows, consent and audit, and one dashboard for every branch.

## 5. Users and roles

| Role | Uses | Needs |
|---|---|---|
| Owner / director | Dashboard, 9 am report | Revenue, collections, dues, problems that need attention |
| Front desk | Enquiries, appointments, messages, tasks | Fast replies, no re-typing |
| Billing / insurance desk | Billing, claims | Dues follow-up, claim status, unbilled alerts |
| Doctor | Appointments, patient profile | Today's list, follow-ups |
| Patient | WhatsApp, patient app (/my) | Easy booking, no surprises on bills, reports on the phone |
| Tec Tha admin | Settings, import, users, audit | Setup and support |

## 6. Current system (what exists in the repo)

- Stack: Python 3.11+, FastAPI, Jinja2 server-rendered pages, SQLite, no front-end framework. Runs on a laptop.
- Modules: `patients` (one ID, consent), `messaging` (WhatsApp in simulator or live mode, consent check, stores and audits every send), `automations` (reminders, dues, follow-ups, feedback, unbilled, stuck claims, owner report), `scheduler` (every 60 s), `billing` (bills, payments, orders, claims), `metrics` (dashboard numbers), `auth` (users, roles, CSRF), `integrations/csv_import`, `routes/api` (REST, X-API-Key), `routes/webhooks` (WhatsApp, simulator, missed call), `routes/ui` (staff screens), `routes/patient_app` (patient PWA at /my, in progress), `ai/` (AI receptionist and owner insights, in progress, off by default).
- Demo: `python -m app.seed` creates realistic data for 2 branches.
- Tests: `python -m pytest -q`.

## 7. Non-negotiable rules

1. **Consent:** no message to a patient without consent (DPDP Act 2023; Rules notified Nov 2025, most duties apply by May 2027). Replies to a message the patient sent first are allowed.
2. **No medical advice** from software or AI. Communication and admin only; clinical decisions stay with doctors.
3. **Accounts in the hospital's name:** the WhatsApp account, server and data. Tec Tha is an admin, never the owner, so the hospital is never locked in.
4. **No silent failures:** a failed send is stored as `failed` with the error, a blocked send as `blocked_no_consent`, and automation errors are written to the audit log.
5. **Every staff member has their own login**, sees only what their role and branch allow, and every change is audited.
6. **Indian context:** ₹ in Indian format, IST, mobile numbers stored as 91XXXXXXXXXX, UPI, TPA/PM-JAY, ABHA, NABH, plain English with local languages where possible.
7. **Never invent numbers or facts** in client-facing material. Label vendor claims as claims and sample data as sample.

## 8. Go-to-market plan

1. Discovery questions → hospital visit (operations audit and patient-side audit) → findings report in ₹.
2. Demo meeting (docs/DEMO_SCRIPT.md) → **paid pilot**: one branch, one problem, 30–45 days, success measure agreed up front.
3. Both branches → CRM ↔ billing sync → monthly retainer (setup fee per phase plus monthly fee; WhatsApp costs passed through at actual cost).

## 9. Open questions for the client

Which CRM? Which billing software, and does it have an API or export? Same or different billing at the two branches? The vendor's contact person? Manual work done daily? Biggest pain? WhatsApp type (personal, Business app or API)? Main patient sources?
