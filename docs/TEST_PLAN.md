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
export TT_DB_PATH=/tmp/claude-0/-home-user/5f540028-1c92-5b5c-889b-342c486a270d/scratchpad/qa.db TT_API_KEY=qa-key TT_SCHEDULER=off TT_OWNER_PHONE=919800000001
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

## 9. Current status (Phase 2 release run, 04 Nov 2026, build 4942f02)

- Unit suite: **167 passed**.
- E2E demo flow: **23 passed, 0 failed, 0 skipped of 23** (fresh seed, port 8020, TT_OWNER_PHONE set).
- What changed in the script:
  - Toast text is read from the page's live region, because ?msg / ?err are signed now.
  - The simulator is found by its form name "Simulate a patient message", and its panel is opened when it is collapsed.
  - The OTP field is found by the label "code".
  - When the run falls in quiet hours (9 pm to 8 am IST), step 06 checks that no patient message was sent, then creates the reminders by calling the automation functions directly so steps 08–10 can run. Step 07 also repeats that direct run and expects 0 sends.
- Exploratory check at phone width (390 px) on the demo screens: no horizontal page scroll; the bottom tab bar and More reach every screen; the simulator panel and the Record payment sheet both work; the claims board scrolls sideways inside its own area (by design); no JS errors. Found BUG-012 (Hindi gaps) and BUG-013 (small touch targets).
- **Pilot demo decision: GO.** No Critical, High or Medium bug is open. BUG-001 to BUG-009 are fixed and re-tested end to end. The open bugs are Low (BUG-011, 012, 013) and need a fix date, not a block.
- Conditions:
  - Run the demo between 8 am and 9 pm IST, or the reminders will not appear (quiet hours, by design).
  - Set TT_OWNER_PHONE.
  - Reseed before the meeting.
- Live go-live still needs the security sign-off and the items in GO_LIVE.md.

---

# Pro (pro-foundation) — test plan and release run

Owner: QA Lead. Build **8a91943**, run 05 Nov 2026 (IST). Bugs are in [BUGS_PRO.md](BUGS_PRO.md). The rules in sections 1, 6 and 7 above still apply.

## P1. New risks

| # | Flow | What can go wrong | Impact | Priority |
|---|---|---|---|---|
| R15 | Login for 8 roles, branch binding | A role can't open its own screen, or can open a screen it shouldn't | Legal (DPDP), operations | **P1** |
| R16 | Two-step login (TOTP, recovery codes, policy), OIDC, idle timeout, sign out other devices | A code is replayed, a recovery code works twice, a role skips required 2FA, a shared terminal stays logged in | Security | **P1** |
| R17 | Lab pipeline and critical values | A critical value is validated without a read-back call-out, is not escalated, or the wrong role enters results; a wrong reference range auto-verifies an abnormal result | **Patient harm** | **P1** |
| R18 | Radiology and PCPNDT Form F | An obstetric scan is performed without Form F; any field for the sex of a foetus | **Legal (PCPNDT Act)** | **P1** |
| R19 | Pharmacy FEFO and Schedule H register | Wrong batch, stock not reduced, a scheduled drug missing from the register, bill ≠ sum of items, double dispense | Legal, money | **P1** |
| R20 | AI Labs and AI features (no-show risk, draft replies, coding, NEWS2, explainers) | AI acts without a person, a draft is sent by itself, an explainer interprets a result, NEWS2 is mis-scored | Patient harm, trust | **P1** |
| R21 | Voice agent | Booking without consent or for an unverified number; bill amounts told to an unverified caller; emergency not caught | Legal, patient harm | **P1** |
| R22 | Command Centre and notifications bell | Another branch's numbers shown; someone else's notification opened | Privacy | P2 |

## P2. End-to-end: `tests/e2e/pro_flow.js`

Plain Node and Playwright (Chromium is pre-installed; never run `playwright install`). Selectors use roles, labels and visible text. Hidden form fields are read by name only to build the negative POSTs that a browser form would never send. Steps:

| Step | Checks | Risk |
|---|---|---|
| P00–P02 | Every role logs in and lands on its home screen with HTTP 200; 9 wrong-role screens give 403 with the access message; the nurse menu hides Command Centre and AI Labs, and the owner menu shows them | R15 |
| P03 | Google sign-in when not configured: back to login with "not set up" | R16 |
| P04–P06 | 2FA set-up: a wrong code is refused, a right code turns it on and shows 10 recovery codes; at login, the password alone opens nothing, a wrong code gets 401, a right code gets in, the same code is refused in a second browser (no replay); a recovery code works once | R16 |
| P07 | Admin requires 2FA for nurses: the nurse is held at /account/2fa until the policy is cleared | R16 |
| P08 | Idle timeout: a session idle for 16 min goes to /login, one idle for 1 min works (cookie built with the app's own signer) | R16 |
| P09–P10 | "Sign out on every other device" ends the other browser only; a wrong current password is refused | R16 |
| P11 | Lab: order (₹250 service, unbilled) → Collect (sample ID shown) → Receive → K 4.2 auto-verified | R17 |
| P12–P14 | Critical K 6.8: no Validate button; a crafted validate POST is refused; a call-out without read-back is refused; an urgent task is due in 15 min; the doctor's bell shows it, opens the lab row and marks it read; someone else's notification gives 404; the call-out with read-back closes the task; then Validate works | R17, R22 |
| P15 | Time travel +40 min: an un-called critical escalates to admin and owner, once only | R17 |
| P16 | Reflex: TSH 8.4 adds Free T4 and waits for a pathologist | R17 |
| P17 | Patient with no age or sex: HCT 37 must not be auto-verified on the child range | R17 |
| P18–P19 | A branch-B order is 404 and unchanged for a branch-A lab user; pharmacy can't post results; front desk can't move a lab test | R15, R17 |
| P20–P21 | An obstetric USG can't be performed without Form F (crafted POST refused), then works with the box ticked; an obstetric X-ray is refused; Lab / radiology staff can act on scans; front desk can't sign a report | R18 |
| P22–P24 | The pharmacy role opens the Pharmacy counter; Dispense picks the earliest-expiry in-date batch, reduces stock by the exact quantity and writes one register row per scheduled drug; Create bill gives total = sum(items) = ₹110; a double-submitted Dispense must not also bill | R19 |
| P25 | Command Centre: a branch-bound doctor sees only branch A; bed occupancy (65%) and beds matched to the database; wall mode loads; nurse gets 403 | R22 |
| P26–P27 | AI Labs: agents find 16 open items and decide none; the owner sees no Accept and a crafted accept gives 403; the order stays unbilled until a person presses Accept, then lands on a bill with total = sum(items); a second accept is refused; Dismiss needs a reason | R20 |
| P28 | No-show risk pill with reasons, labelled "decision support" | R20 |
| P29 | Draft reply fills the box, sends 0 messages and logs one "suggested" decision; a draft for a branch-A conversation gives 404 to branch-B front desk | R20 |
| P30 | Coding: a coder edits and saves the codes ("edited" in governance); the claim stage is unchanged; a second decision is refused; owner gets 403; another branch's claim gives 404 | R20 |
| P31 | NEWS2: 25 / 91 / air / 90 / 131 / A / 39.5 scores exactly 14 with an emergency alert; a text SpO₂ is refused cleanly; Acknowledge closes one alert; another branch's alert gives 404 | R20 |
| P32 | Explainers: text that interprets a result is refused; an edit goes back to Draft until approved | R20 |
| P33–P34 | Patient OTP login (390 px); a validated K shows 4.2 and the approved explainer; an un-validated TSH value is hidden; another patient's critical result is not shown | R17, R20 |
| P35–P36 | /my/voice: no consent gives 400, a wrong CSRF token gives 403; booking by voice makes exactly one appointment; an emergency phrase gets the 108 reply. /voice/demo typed flow: an unverified booking makes a call-back task and no appointment; no ₹ bill amount is told | R21 |
| P37 | No HTTP 5xx and no JS errors during the run | all |

Run (fresh seed and logins every time; the script changes data and turns on 2FA for `doctor`):

```bash
S=/tmp/claude-0/-home-user/5f540028-1c92-5b5c-889b-342c486a270d/scratchpad
export TT_DB_PATH=$S/qa-pro.db TT_API_KEY=qa-key TT_SCHEDULER=off TT_OWNER_PHONE=919800000001
rm -f $TT_DB_PATH && python3 -m app.seed
TT_ADMIN_PASSWORD='Qa@12345' python3 -m app.auth create-admin admin "QA Admin"
# then create, with password Qa@12345: nurse, lab, pharmacy, doctor, billing (branch A), owner (no branch),
# frontb (frontdesk, branch B), via Settings -> Add login or app.auth.create_user
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8021 &
node tests/e2e/pro_flow.js
E2E_BASE_URL=http://127.0.0.1:8021 node tests/e2e/demo_flow.js   # after a second fresh seed
```

## P3. Release run, 05 Nov 2026, build 8a91943

- Unit suite: **241 passed**.
- `tests/e2e/pro_flow.js` on a fresh seed: **RESULT: 39 passed, 6 failed, 0 skipped of 45 steps.** Every failure is a product bug, not a script problem:
  - P01 (pharmacy) and P22: BUG-P01
  - P17: BUG-P04
  - P19: BUG-P02
  - P21: BUG-P03
  - P24: BUG-P05
- `tests/e2e/demo_flow.js` (pilot) on a second fresh seed, port 8021: **RESULT: 23 passed, 0 failed, 0 skipped of 23 steps.**
- Exploratory pass at 390 and 1920 px: admin, lab, nurse and owner on every Pro screen. Results:
  - No JS errors.
  - No page-level horizontal scroll, except Appointments at 390 px (BUG-P09).
  - Wall mode, the bell and the dialogs work at both widths.
  - Manual probes found BUG-P06 and BUG-P07, and confirmed there is no open redirect via `next=/\…`.
- Bugs: 0 Critical, **4 High**, 3 Medium, 2 Low.
- **Pro demo decision: NO-GO**, until BUG-P01 to BUG-P04 are fixed and P01, P17, P19, P21 and P22 pass on a fresh seed. BUG-P05 should be fixed in the same change (P24).
  - If the client meeting can't move, a demo driven **only by the admin login** avoids the broken role paths. It still shows BUG-P04 if a test is ordered from the dialog, so use the seeded patients only. This is a workaround for one meeting, not a release.
- Pilot (non-Pro) demo flow is unaffected: it is still GO under the conditions in section 9.
