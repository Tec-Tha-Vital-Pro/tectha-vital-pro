# Tec Tha Vital — Product Requirements (PRD)

Owner: Head of Product · Last reviewed: 4 Nov 2026 against the code in `app/` (commit `7861cf0` plus uncommitted work in the tree).
Read with [PRODUCT_KNOWLEDGE.md](PRODUCT_KNOWLEDGE.md) (rules in section 7 apply to every item here) and [ROADMAP.md](ROADMAP.md).

**Status key.** **Built** = in the code, covered by tests, works in simulator mode. **In progress** = code exists but is uncommitted, untested, not wired in, or not safe for real patients yet. **Planned** = no code. Sales may show Built items only, and must call everything else "planned".

---

## 1. Vision

A mid-size Indian hospital keeps its CRM and billing software and gets one connecting layer on top: every patient has one ID across branches, every enquiry gets a reply, every due and every unbilled service is chased, and the owner sees both branches on one screen and on WhatsApp at 9 am. We recover money, keep patients and save staff time without replacing anything.

## 2. Target customer

- **Segment:** private hospitals in India with 2–5 branches, roughly 50–300 beds, already using an HMS/billing product and some CRM, with communication done by hand on personal WhatsApp and phone.
- **First client (prospect):** a 2-branch hospital group with a CRM and separate billing software (products not yet known; see PRODUCT_KNOWLEDGE section 9).
- **Buyer:** owner / director. **Users:** front desk, billing and insurance desk, doctors, patients. **Setup:** Tec Tha admin.

## 3. Personas

| Persona | A day today | What they need from us |
|---|---|---|
| **Owner / director** | Hears yesterday's numbers by phone or Excel, if at all; finds out about stuck claims too late | One dashboard for both branches; 9 am WhatsApp report; a short "needs attention" list |
| **Front desk executive** | Juggles calls, walk-ins and WhatsApp on a personal phone; missed calls are forgotten | One inbox, instant auto-reply, a 15-minute missed-call task, booking with token numbers |
| **Billing / insurance desk** | Chases dues by calling; TPA approvals tracked on paper | Dues list with one-click reminder, unbilled alerts, claims board with time-limit alerts |
| **Doctor** | Gets the OPD list on paper | Today's list and the patient's history |
| **Patient** | Waits on hold, forgets appointments, gets bill surprises | Reminders with reply-to-confirm, clear itemised bill, one ID at both branches |
| **Tec Tha admin** | Sets up and supports the hospital | Import, users, settings, audit log |

## 4. Problems, ranked by value to the hospital

1. **Money leaks:** pending dues, services done but not billed, insurance claims stuck past IRDAI limits.
2. **Lost patients:** enquiries not answered, no-shows, no follow-up after the first visit.
3. **Staff time:** re-typing between systems, manual reminder calls, compiling reports.
4. **No combined view** of two branches; the same patient registered twice.
5. **Trust and compliance:** consent (DPDP Act 2023), role-based access, audit trail.

---

## 5. v1 — what is built (demo-ready, simulator mode)

Each feature: user story, acceptance criteria (AC) that QA can test, status, and the success metric to track in the pilot. Pilot metrics use the hospital's own baseline, measured before go-live (GO_LIVE.md section 5); targets are agreed with the client at kickoff, not set here.

### F1. One patient ID across branches — Built
*As front desk, I want a patient found by mobile number at either branch, so that nobody is registered twice.*
- AC1: Creating a patient with a phone that already exists returns the existing record; no second row (`patients.phone` is unique).
- AC2: Phones are stored as `91XXXXXXXXXX` whatever format is typed; an invalid number is rejected with a message.
- AC3: Each patient gets a `TT-xxxxxx` ID shown on the Patients screen and the patient page.
- AC4: The patient page shows appointments, bills, messages and feedback from both branches.
- **Metric:** duplicate registrations per month (target: zero new duplicates created through Care Connect).

### F2. Consent and opt-out — Built
*As the hospital, I want no message sent without consent, so that we follow DPDP.*
- AC1: An automated message to a patient without consent is stored as `blocked_no_consent` and not sent.
- AC2: A patient replying `STOP` has consent withdrawn and the change is audited.
- AC3: Staff can give or withdraw consent on the patient page; CSV import and `/api/patients` accept a consent field.
- AC4: Replies to a conversation the patient started are allowed without consent (rule 7.1).
- **Metric:** % of active patients with recorded consent; number of messages sent without consent (must be zero).

### F3. Enquiry inbox — Built
*As front desk, I want enquiries from every source in one list, so that none is missed.*
- AC1: A WhatsApp message from an unknown number creates a lead (source WhatsApp) and sends a welcome reply listing the branches.
- AC2: Leads can be added by hand or by `POST /api/leads` (X-API-Key) with one of nine sources.
- AC3: Leads can be filtered by source, status and branch; status moves New → Contacted → Booked → Converted / Lost.
- AC4: Booking an appointment for that phone moves an open lead to Booked.
- AC5: Dashboard shows enquiries per day and % replied within 5 minutes.
- **Metric:** median first-reply time; enquiry → booked → visited → paid funnel (dashboard).

### F4. Missed-call tasks — Built
*As front desk, I want every missed call to become a task with a deadline, so that we call back.*
- AC1: `POST /webhooks/missed-call` with a valid X-API-Key creates a lead and a `missed_call` task due in 15 minutes.
- AC2: Wrong or missing key returns 401; unknown branch returns 400.
- **Metric:** % of missed calls returned within 15 minutes; open missed-call tasks at end of day.

### F5. Appointments, tokens and reminders — Built
*As front desk, I want reminders sent automatically and replies handled, so that no-shows fall.*
- AC1: Booking assigns the next token number for that branch and day.
- AC2: A reminder goes 24 h before and another 2 h before, once each, only for Booked/Confirmed appointments.
- AC3: Reply `1` sets Confirmed; `2` creates a reschedule call task due in 30 min; `3` sets Cancelled. Each sends a confirmation reply.
- AC4: Staff can mark Visited / NoShow; a branch-bound user cannot book at another branch.
- **Metric:** no-show rate (30-day, on dashboard); % of reminders answered.

### F6. Pending dues reminders — Built
*As the billing desk, I want dues chased automatically, so that we collect without phone calls.*
- AC1: Bills with a balance get a WhatsApp reminder at 3, 10 and 21 days old; never the same stage twice.
- AC2: The message lists bill items, total, paid, balance and a payment link.
- AC3: At stage 3 a call task is created for the billing desk.
- AC4: "Send reminder now" sends the next stage at once; a no-consent patient shows a clear error.
- AC5: Staff can record a payment (UPI, Card, Cash, Insurance); overpayment is rejected.
- **Metric:** ₹ of dues older than 30 days; ₹ collected within 7 days of a reminder; days-sales-outstanding.
- Note: the payment link is `TT_PAYMENT_LINK_BASE/<bill_no>`. There is no payment gateway and no automatic "paid" update yet (see F17).

### F7. Unbilled-service detection — Built
*As the billing desk, I want services done but not billed flagged, so that revenue is not lost.*
- AC1: An order (lab, pharmacy, ward) with no bill after 2 hours creates one `unbilled` task.
- AC2: "Add to bill" puts it on the patient's open bill at that branch (or a new bill) and closes the task.
- AC3: Dashboard and owner report show the total ₹ unbilled.
- **Metric:** ₹ found unbilled per month and ₹ later billed (money recovered).

### F8. Insurance claims board — Built
*As the insurance desk, I want claims past the IRDAI time limits flagged, so that we chase the TPA in time.*
- AC1: Claims move through PreAuthRequested → PreAuthApproved → FinalSent → Settled / Denied, each change audited.
- AC2: A claim in PreAuthRequested for more than 60 min, or FinalSent for more than 180 min, creates one `claim_stuck` task (IRDAI 2024 master circular: 1 h cashless decision, 3 h discharge).
- AC3: Changing the stage closes the task.
- **Metric:** % of claims decided within the limits; average discharge-approval time.

### F9. After-care: follow-ups, feedback, reviews — Built
*As the hospital, I want patients reminded of follow-ups and asked for feedback, so that they come back and unhappy ones are heard.*
- AC1: Follow-ups due in the next 3 days get one reminder; status becomes Reminded.
- AC2: Visited appointments get one feedback request 2–48 h later.
- AC3: Score 1–3 creates a complaint task (24 h) and an apology reply; 4–5 sends the Google review link.
- **Metric:** follow-up return rate; complaints closed within 24 h; new Google reviews per month.

### F10. Owner dashboard and 9 am report — Built
*As the owner, I want both branches' numbers and problems in one place every morning, so that I act before noon.*
- AC1: Dashboard shows OPD, billed, collected, dues, no-show %, 7-day collections by branch, enquiry funnel and "needs attention", for all branches or one.
- AC2: After 9 am, once per day, the owner gets a WhatsApp report for yesterday per branch plus needs-attention counts.
- AC3: Numbers match a direct database count for the same day (test with seed data).
- **Metric:** owner opens the report or dashboard on ≥ 5 days a week (ask the owner; we do not track reads yet).

### F11. Staff logins, roles and audit — Built
*As the hospital, I want each staff member to have their own login and see only their screens, so that data is protected.*
- AC1: Roles admin, frontdesk, billing, doctor; each screen refuses other roles with a 403 page.
- AC2: A branch-bound user sees only their branch on Dashboard, Enquiries, Appointments, Billing, Claims and Tasks.
- AC3: Every POST checks a CSRF token; passwords are PBKDF2-hashed; sessions expire after 8 h.
- AC4: Logins (success and failure), sends, blocks, consent changes, payments, stage changes and automation errors are in the audit log.
- **Metric:** shared logins (must be zero); audit entries per user per week.
- Gap: Patients, patient page, Messages and actions by record ID (send reminder, record payment, change claim stage) are not branch-restricted yet (see F18).

### F12. Data in: CSV import and REST API — Built
*As Tec Tha admin, I want to load patients and bills from the billing software, so that nobody re-types.*
- AC1: Patient and bill CSVs import with a per-row error list; bad rows are reported, never dropped silently.
- AC2: Bills already imported (same bill_no) are skipped, so re-importing the same file is safe.
- AC3: `/api/leads, /patients, /bills, /payments, /orders, /claims` and `PATCH /api/claims/{id}` work with X-API-Key; the API is off until `TT_API_KEY` is set.
- **Metric:** hours of manual entry per week at the pilot branch (before vs after).

### F13. WhatsApp simulator and live mode — Built (simulator), In progress (live)
*As Tec Tha, I want to demo without sending real messages and switch to real WhatsApp for the pilot.*
- AC1: Simulator mode stores every send as `simulated`; the Messages screen lets staff reply as a patient.
- AC2: Live mode refuses to start without token, phone ID, app secret and a real session secret.
- AC3: Incoming webhooks are rejected without a valid `X-Hub-Signature-256`.
- AC4: A failed live send is stored as `failed` with Meta's error.
- Gap: live sends are free text only. Reminders, dues and reports outside the 24-hour window will fail until Meta templates are supported (F14).

---

## 6. v1.1 — pilot hardening (next 4 weeks)

Goal: one branch, one problem, real patients, no surprises. Ranked by what blocks the pilot.

### F14. WhatsApp message templates — Planned (P0)
*As the hospital, I want reminders and dues messages to reach patients outside the 24-hour window.*
- AC1: Each automated message type maps to a named, Meta-approved template with variables; live mode sends a `template` message, not free text.
- AC2: If a template is not approved, the send is stored as `failed` with a clear reason and appears on a "failed sends" list.
- AC3: Simulator shows the same filled-in template text.
- **Metric:** live delivery success rate per template.

### F15. Safe live webhook — Planned (P0)
*As the hospital, I want each patient message handled exactly once.*
- AC1: Meta message IDs are stored; a retried webhook does not create a second lead, task or reply.
- AC2: Delivery and read status callbacks update the message row (sent → delivered → read / failed).
- **Metric:** duplicate leads per week (must be zero).

### F16. Pilot operations: backups, monitoring, failed-send alerts — Planned (P0)
- AC1: Nightly SQLite backup to a second location; a restore is tested and documented.
- AC2: If the scheduler has not run for 10 minutes, or any automation error is logged, the Tec Tha admin is alerted.
- AC3: A "failed and blocked sends today" count appears on the dashboard.
- **Metric:** automation uptime %; backups verified per month.

### F17. Payment link with real status — Planned (P1)
*As the billing desk, I want a dues link that takes a real UPI payment and marks the bill paid.*
- AC1: The link opens a payment page from a gateway in the hospital's name (e.g. Razorpay; to be chosen with the client).
- AC2: The gateway webhook records the payment against the bill, once, and stops further reminders.
- **Metric:** % of dues paid through the link.

### F18. Branch restriction everywhere — In progress gap, Planned fix (P1)
- AC1: A branch-bound user gets 403 (or "not found") on any patient, message, bill, order or claim from another branch, for both pages and actions.
- AC2: Tests cover every screen and action for a branch-bound user.

### F19. Pilot results report — Planned (P1)
*As the owner, I want a monthly before/after report on the agreed measure.*
- AC1: Export of baseline vs current for the agreed metric (no-show %, dues ₹, reply time), from real data only.

### F20. Staff self-service basics — Planned (P2)
- AC1: Admin can deactivate a user and reset a password from Settings; both audited.

Also in v1.1: fix the one failing test (`tests/test_ui.py::test_messages_and_audit_pages`, HTML escaping on Messages) before any release.

---

## 7. v2 — after the pilot

| # | Feature | Status | Notes |
|---|---|---|---|
| F21 | **Patient app (PWA at /my):** WhatsApp OTP login, appointments with confirm/cancel, booking, bills, profile and consent, feedback | In progress | Code exists, uncommitted, no tests. Not pilot-ready: the Pay button records a UPI payment with no gateway, and the report page shows hard-coded sample lab values. Both must be removed or replaced before any patient sees it |
| F22 | **AI WhatsApp receptionist** (understands enquiries in English, Hindi and other languages; books into real free slots; hands off to staff) | In progress | Off by default (`TT_AI=on` + key). No evals yet (`app/ai/evals` is empty). Needs Domain Lead and Security sign-off, a red-team report, and rule 7.2 (no medical advice) checks before use |
| F23 | **AI owner insights** (plain-English notes on the daily numbers; invented numbers are dropped) | In progress | Module exists but is not wired into the report or dashboard |
| F24 | **CRM ↔ billing sync** with the client's actual products (scheduled pull or vendor API; write-back only when asked) | Planned | Depends on discovery answers (which CRM, which billing, API or export) |
| F25 | Report-ready and bill-ready messages with secure download | Planned | Needs link to lab system and a secure file store |
| F26 | Live OPD queue / token updates on WhatsApp | Planned | Problem 9 |
| F27 | Local-language templates (Hindi first) | Planned | `patients.language` field exists, unused |
| F28 | Family accounts, care programmes, health packages, referral rewards | Planned | Loyalty, after retention is proven |
| F29 | Pharmacy stock-outs | Planned | Phase 3 |
| F30 | ABHA / ABDM linking | Planned | `abha_id` field exists, unused |

---

## 8. Out of scope (v1 and v1.1)

- Replacing the hospital's HMS, billing, EMR, lab or pharmacy system.
- Any clinical advice, triage or diagnosis by software or AI.
- Insurance claim submission to TPAs or PM-JAY portals (we track stages; staff submit).
- Marketing broadcasts and campaigns.
- Payroll, inventory, accounting, HR.
- A native iOS/Android app (the PWA is the mobile path).
- Hosting outside India, or accounts in Tec Tha's name.

## 9. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Meta templates not approved, or free-text sends fail outside 24 h | Reminders and dues do not reach patients; pilot fails | F14 before go-live; submit templates in week 1; watch failed sends daily |
| Billing vendor gives no API or export | Manual CSV forever; data goes stale | Start with daily CSV; agree export format in discovery; ask the hospital to request it from the vendor |
| Consent not captured at registration | Most messages blocked; low impact | Consent line on the form (GO_LIVE 1); show blocked count on dashboard |
| Patient app shows fake data (sample lab values, fake payment) | Patient harm, loss of trust, legal exposure | Keep /my off for the pilot until F21 is fixed and tested |
| AI gives medical-sounding advice or wrong booking | Patient harm; breaks rule 7.2 | AI stays off in pilot; evals and red-team first |
| Single SQLite file on one small server | Data loss or downtime | Nightly backups with tested restore (F16); move to Postgres before 3+ branches |
| Branch staff see other branches' patients | Privacy breach | F18 before the second branch goes live |
| Duplicate webhook delivery | Duplicate leads and replies; staff annoyed | F15 |
| Founder-only team | Slow support during pilot | One automation at a time; hire Implementation Manager first (TEAM.md) |
| DPDP duties tighten by May 2027 | Rework | Consent, audit and India hosting already in; DPA signed before data |
