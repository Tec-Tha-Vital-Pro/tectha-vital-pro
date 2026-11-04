# Tec Tha Vital — Test Plan

Owner: QA Lead. Status: **Phase 1** (plan, first end-to-end run, first bug list). Bugs are in [BUGS.md](BUGS.md).

The QA Lead decides release go / no-go ([TEAM.md](TEAM.md)). Nothing ships with a failing test or an open Critical or High bug.

## 1. Approach

We test by risk. The flows that can hurt a patient, lose the hospital money, break the law (DPDP consent) or embarrass us in the client demo get tested first and most often, at every level. Cosmetic screens come last.

How we score risk: **Impact** (patient harm, money, legal, demo) × **Likelihood** (how complex the code is, how often it changes, what history says). H×H = P1, run on every build. H×M or M×H = P2, run before every release. Everything else = P3, run before a client release.

The staff UI and the patient app are being redesigned right now. End-to-end tests find things by visible text, labels and roles, never by CSS class. When an e2e step fails only because a label changed, we log it as "re-run after redesign", not as a product bug.

## 2. Risk register (critical flows)

| # | Flow | What can go wrong | Impact | Likelihood | Priority |
|---|---|---|---|---|---|
| R1 | Login, roles, branch isolation | A branch-B user sees or changes branch-A data; a doctor opens billing; a session or CSRF bypass | Legal (DPDP), trust | High: every route checks this separately | **P1** |
| R2 | Consent blocking | A message goes to a patient who has not consented, or who sent STOP | Legal (DPDP Act 2023) | Medium | **P1** |
| R3 | Appointment reminders 24 h / 2 h | A double send, a missed send, the wrong time window, a reminder for a cancelled visit | Patient experience, cost | Medium (time windows) | **P1** |
| R4 | Dues reminders and payment recording | Wrong balance in the text, escalation stages sent back to back, overpayment, paid ≠ sum of payments | Money, complaints | High (state machine) | **P1** |
| R5 | Unbilled services → Add to bill | Order added twice, bill total ≠ sum of items, task left open, wrong patient or branch bill | Money (revenue leakage is problem #1) | Medium | **P1** |
| R6 | Stuck claims alerts | No alert past the IRDAI 1 h pre-auth / 3 h discharge limits, duplicate alerts, alert not closed when the stage moves | Money, patient waiting at discharge | Medium | P2 |
| R7 | Inbound WhatsApp replies 1 / 2 / 3 | "1" confirms the wrong appointment, or one that is already past or cancelled; a reply is lost | Patient experience, no-show numbers | High (depends on "last message") | **P1** |
| R8 | Feedback low / high | A score of 3 or less makes no complaint task; the review link goes to an unhappy patient | Reputation | Low | P2 |
| R9 | Missed-call API | No API key check; no 15-minute task; bad phone accepted | Lost enquiries, security | Low | P2 |
| R10 | CSV import, including bad rows | A bad row silently dropped, a duplicate bill on re-import, a wrong paid amount | Money, data quality | Medium | **P1** |
| R11 | Owner report (9 am) | Numbers that don't match the dashboard, sent twice, never sent | Owner trust (main buyer) | Medium | P2 |
| R12 | Patient app: OTP, book, pay | OTP leaked or brute-forced, a patient sees another patient's bill, a double booking, a "payment" recorded without real money outside demo mode | Legal, money | Medium (new code) | **P1** |
| R13 | Demo flow (DEMO_SCRIPT.md) | Any step breaks in front of the client | Sales | High (UI being redesigned) | **P1** |
| R14 | Audit log and no silent failures | A send, block or error not stored or audited | Legal, support | Low | P2 |

## 3. Test levels

| Level | Tool | Where | Runs |
|---|---|---|---|
| Unit and integration (module + FastAPI TestClient, fresh SQLite per test) | pytest | `tests/test_*.py` | Every change: `python -m pytest -q` |
| AI evals | `app/ai/evals/run_evals.py` | `app/ai/evals/cases.jsonl` | When prompts or the model change (AI is off by default) |
| End-to-end, browser against a running server | Playwright for Node (Chromium) | `tests/e2e/demo_flow.js` | Before every release and every client demo |
| Exploratory and role checks | Manual, with this plan | — | Before a client release |
| Security review | Security & Privacy Engineer | — | Before go-live (QA does not replace it) |

## 4. Unit test coverage map and gaps

From reading `tests/` (107 tests at the last run).

| Area | Covered now | Gaps to add (owner: the engineer for that module; QA reviews) |
|---|---|---|
| Auth and roles (`test_ui.py`) | Password hash; login required; wrong password audited; front desk blocked from Settings; CSRF rejected; logout | Full role × screen matrix (doctor, billing, front desk, admin); session expiry; inactive user |
| Branch isolation | Only `GET /leads` for a branch-B front desk user | **All POST actions** (payment, reminder, add to bill, claim stage, task done, lead status); Messages, Tasks, Claims and Billing lists; `?branch=` cannot widen a branch-bound user's scope. See BUG-003 and BUG-004 |
| Consent (`test_automations`, `test_webhooks`, `test_patient_app`) | Reminder blocked without consent and not retried; STOP withdraws consent; manual dues reminder blocked records the stage; booking without consent | Every automation type blocked once (feedback, follow-up, dues); consent re-given after STOP; reply-to-inbound allowed without consent |
| Appointment reminders | 24 h and 2 h sent once (idempotent) | Visit booked less than 2 h ahead; cancelled or no-show visit not reminded; exact window edges (2 h, 24 h) |
| Dues and payments (`test_automations`, `test_billing`, `test_api`) | Stages at day 3 / 10 / 21; paid bill skipped; overpayment rejected; manual reminder | **An old bill seen for the first time gets one reminder, not three in three minutes** (BUG-002); reminder on a paid or missing bill from the UI (BUG-005); paid always equals sum(payments); UI amount 0, negative or text |
| Unbilled → Add to bill | Goes onto the open bill and closes the task; makes a new bill when none is open | Adding the same order twice (second is refused); bill total equals sum(items) after the add; branch-B user adding a branch-A order |
| Claims | Stage change closes the stuck task; detection at 60 / 180 min | Exactly 60 and 180 minutes; a Denied or Settled claim never alerts; one alert per claim per stage |
| Inbound replies (`test_webhooks`) | 1 / 2 / 3 after a reminder; feedback low / high; unknown number → lead; other text → staff task; signatures; unsupported types | "1" after another message was sent since the reminder; "1" on a visit already past or marked no-show (BUG-009); feedback score 3 (edge of "low"); **the Messages simulator form path with its CSRF token** (BUG-001 got past the tests because they post with the API key) |
| Missed call | API key required | Unknown branch is a 400; bad phone is a 400; the task is due in 15 minutes |
| CSV import (`test_csv`) | Sample files; bad patient and bill rows reported; re-import skipped; missing columns | Non-UTF-8 upload through the UI; the same bill_no split across rows with different patients; paid larger than total; an old bill imported, then run automations (ties to BUG-002) |
| Owner report | Sent once after 9 am | Report figures equal the dashboard figures for the same day; reseeding on demo day still allows a report (BUG-007) |
| Patient app (`test_patient_app`) | OTP success, wrong code, attempt limit, expiry, rate limit, CSRF; booking and taken slot; confirm / cancel / reschedule; pay; cannot see another patient's bill; consent toggle; feedback | Pay in live mode is refused (no fake payments); booking outside the 7-day window; two patients booking the same slot at the same time |
| Metrics | Seed builds data in both branches; API dashboard | KPI values checked against hand-calculated fixtures per branch |

## 5. End-to-end scenarios

Automated in `tests/e2e/demo_flow.js` (it follows DEMO_SCRIPT.md in order). Each step prints PASS / FAIL / SKIP; a failure saves a full-page screenshot. The script reads the server's SQLite file (read-only) to pick test patients, read the OTP and check the money.

| Step | Scenario | Checks | Risk |
|---|---|---|---|
| 00–03 | Health, redirect to login, wrong password, admin login | Redirect to /login; error shown; logged in | R1 |
| 04–05 | Dashboard, both branches then one branch | KPI labels, ₹ amounts, chart; outstanding dues equal the database sum, overall and per branch | R11, R13 |
| 06 | Settings → Run automations now | Confirmation; reminders created | R3, R4, R6 |
| 07 | Run automations a second time | **No new outbound messages** (idempotency) | R3, R4 |
| 08–09 | Messages shows a reminder; patient replies `1` | Appointment becomes Confirmed in the database, in the chat and on Appointments | R7 |
| 10 | Patient replies `2` to a feedback request | One new complaint task, shown on Tasks | R8 |
| 11 | Message from a new number | Lead appears in Enquiries | R7 |
| 12 | Missed-call webhook | 401 without key; lead plus a task due in 15 minutes | R9 |
| 13 | Billing → Send reminder now | One dues message with balance and payment link, or a clear "no consent" error | R2, R4 |
| 14 | Billing → Record payment ₹100 | paid +100 exactly; bills.paid equals sum(payments); form max equals balance | R4 |
| 15 | Billing → Add to bill | Order linked to a bill; bill total equals sum(items); unbilled task closed; list shrinks by one | R5 |
| 16 | Claims board | Loads; stuck-claim tasks exist for seed claims past the limits | R6 |
| 17 | Owner report | Sent after 9 am IST with attention block and ₹ figures; shown on dashboard | R11 |
| 18 | Patient app OTP login | Code read from the messages table; code not shown on the page; lands on /my/ | R12 |
| 19 | Patient app booking | Branch → doctor → day → slot → Confirm; one new appointment | R12 |
| 20 | Patient app pay (demo) | Page says DEMO; bill fully paid after Pay | R12 |
| 21 | Patient opens another patient's bill | Not shown | R1, R12 |
| 22 | Whole run | No HTTP 5xx; no 403 on a form POST | R13 |

To automate in Phase 2 (in this order): role matrix (front desk, billing, doctor, branch-bound users, using Settings → Add login); consent journey (STOP, then try every automation); CSV import with `docs/samples/` and a bad-rows file through the UI; a "time travel" run of dues reminders over 25 days; reply `3` cancels and `2` makes a reschedule task; mobile viewport (390 px) for staff screens.

## 6. Test data and environment

- Database: a throwaway SQLite file, never `data/tectha.db`.
- Seed: `python -m app.seed` gives 2 branches, about 80 patients (about 90% with consent), bills of several ages, unbilled orders, claims in every stage and visits from 30 days ago to 3 days ahead. All of it is **sample data**.
- Run the e2e flow on a fresh seed every time. It changes data (payments, bookings), so a second run on the same database is not a clean run.

```bash
export TT_DB_PATH=/tmp/claude-0/-home-user/5f540028-1c92-5b5c-889b-342c486a270d/scratchpad/qa.db TT_API_KEY=qa-key TT_SCHEDULER=off
python -m app.seed
TT_ADMIN_PASSWORD='Qa@12345' python -m app.auth create-admin admin "QA Admin"   # first time only; seed keeps logins
uvicorn app.main:app --port 8020 &
node tests/e2e/demo_flow.js            # E2E_BASE_URL, E2E_USER, E2E_PASSWORD, E2E_SHOTS, E2E_HEADED=1 optional
```

- The scheduler is off (`TT_SCHEDULER=off`) so only the test triggers automations.
- WhatsApp is in simulator mode: nothing leaves the machine.
- Time: all times are IST. Step 17 depends on the clock (the report only goes out after 9 am IST).

## 7. Entry and exit criteria

**Entry (QA starts a release cycle when):** the feature has acceptance criteria from the Head of Product; it is merged to the release branch; `python -m pytest -q` is green on the developer's machine; seed runs cleanly; UI labels used by the e2e script are final, or the change is listed in the release notes.

**Exit (QA can sign off when):**
- Unit suite 100% green, with no skipped tests except documented optional modules.
- E2E demo flow: every step PASS on a fresh seed (SKIP only for a documented data or clock reason).
- No open Critical or High bug. Medium bugs have an owner, a date and a workaround the Implementation team knows about.
- Every P1 risk in section 2 has at least one passing automated check.
- Security review done for the release (Security & Privacy Engineer).

## 8. Release sign-off checklist

- [ ] `python -m pytest -q`: all green (paste the summary line)
- [ ] `node tests/e2e/demo_flow.js` on a fresh seed: all PASS (paste the RESULT line)
- [ ] Branch isolation: a branch-B user cannot view or change branch-A bills, claims, tasks, enquiries or messages
- [ ] Consent: patients without consent get no automated message; each blocked attempt is stored as `blocked_no_consent`
- [ ] Idempotency: Run automations twice → second run sends 0 messages; old bills get at most one dues reminder per run and per gap
- [ ] Money: after payments and Add to bill, bills.paid = sum(payments) and bills.total = sum(bill_items) for every bill (SQL check)
- [ ] Rupees in Indian format (₹12,34,567) on every screen and message checked
- [ ] Simulator demo path works: reply 1 / 2 / 3, feedback 1–5, a new number, STOP
- [ ] Patient app: OTP never shown on screen; Pay only in demo mode and labelled DEMO
- [ ] Owner report sent once after 9 am and matches the dashboard
- [ ] No HTTP 5xx in the server log during the e2e run
- [ ] Live-mode start-up refuses missing WhatsApp credentials, webhook secret or session secret
- [ ] BUGS.md updated; every Critical or High bug closed and re-tested
- [ ] Security sign-off: ______  Head of Product: ______  **QA Lead go / no-go: ______**

## 9. Current status (Phase 1, 04 Nov 2026)

- Unit suite: in flux while teammates edit the app. Two runs today: 97/99 passed, then 106/107. The failures were tests out of date after deliberate changes (dashboard heading, pay-page label, health response), not product bugs. Re-run after the redesign.
- E2E demo flow: **17 passed, 6 failed, 0 skipped of 23** (fresh seed, port 8020). The failures come from BUG-001 (simulator blocked, 3 steps plus the 403 check), BUG-002 (idempotency) and BUG-007 (owner report after reseed).
- **Release decision: NO-GO.** BUG-001 is Critical (it blocks demo section 3), and BUG-002 and BUG-003 are High.
