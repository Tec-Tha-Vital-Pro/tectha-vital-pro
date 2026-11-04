# Bug list

Owner: QA Lead. BUG-001 to BUG-009 were found in the Phase 1 run on 04 Nov 2026, and BUG-011 to BUG-013 in the Phase 2 release run on build 4942f02 (fresh seed, simulator mode, server on port 8020, `node tests/e2e/demo_flow.js`, plus targeted TestClient probes). Line numbers are from the working tree on that date. Teammates are still editing, so lines will move.

Severity: **Critical** = blocks the demo or leaks or loses data or money with no workaround. **High** = wrong money, privacy or patient messaging in a normal flow. **Medium** = wrong behaviour with a workaround, or limited reach. **Low** = cosmetic or edge case.

| ID | Severity | Title | Status |
|---|---|---|---|
| BUG-001 | Critical | "Simulate a patient message" is rejected (403): the form has no CSRF token | Fixed (architect): CSRF field on the simulator form; e2e 09–11 pass |
| BUG-002 | High | Dues reminders: an old bill gets stage 1, 2 and 3 reminders on back-to-back runs | Fixed (architect): minimum gap between dues stages; e2e 07 passes |
| BUG-003 | High | Branch-bound billing user can pay, remind, add to bill and move claims for another branch | Fixed: branch check on every id route returns 404 (tests/test_security.py) |
| BUG-004 | Medium | Messages screen is not limited to the user's branch | Fixed: Messages scoped to the branch's patients and enquiries; owner report and OTP admin-only |
| BUG-005 | Medium | "Send reminder now" on a paid or deleted bill crashes (HTTP 500) | Fixed: paid bill → friendly error; missing or other-branch bill → 404 page |
| BUG-006 | Low | "Automations ran" message shows raw Python dicts and a message id as a count | Fixed: plain-English summary (automations.summary) |
| BUG-007 | Medium | After reseeding on demo day, the 9 am owner report cannot be sent again | Fixed (architect): seed clears last_owner_report_date; e2e 17 passes with TT_OWNER_PHONE set |
| BUG-008 | Low | Unit tests are out of date after deliberate UI and API changes | Fixed: full suite green (149 passed) |
| BUG-009 | Low | Reply "1" can re-confirm an appointment that is already past or marked no-show | Fixed (architect): only future Booked/Confirmed visits are confirmed |
| BUG-010 | Low | E2E step 13 regex expects "Balance due ₹", but the reminder says "balance due of ₹" | Fixed in the test script (9ab4b0c); step 13 passes |
| BUG-011 | Low | Manual "Send reminder now" sends a dues WhatsApp during quiet hours (9 pm to 8 am) | Open (needs a product decision) |
| BUG-012 | Low | Patient app in Hindi: the code step and the footer are still in English | Open |
| BUG-013 | Low | Phone width: patient-name links in list rows are 21 px tall, under the 24 px minimum touch target | Open |

---

## BUG-001 — Critical — Simulator form on Messages is rejected with 403

**Steps**
1. Seed, log in as admin, then Settings → Run automations now.
2. Messages → open a patient who received a reminder.
3. In "Simulate a patient message", type `1` and press Send as patient.

**Expected:** the appointment shows Confirmed and the reply appears in the chat (DEMO_SCRIPT section 3).
**Actual:** `POST /webhooks/simulate-inbound` returns **403** `{"detail":"This form has expired. Reload the page and try again."}`. The browser shows raw JSON. Replies `1`, `2` and messages from a new number all fail, so demo section 3 cannot be shown at all. E2E steps 09, 10, 11 and 22 fail.

**Cause:** `app/routes/webhooks.py:215-231` (`simulate_inbound`) now requires the staff CSRF token (or an API key), but the form in `app/templates/messages.html:62-69` does not send one. It needs `{{ csrf_field(csrf) }}`. The unit tests did not catch it because they post with the API key, not through the page form.
**Owner:** Front-end (template) together with Backend. **Re-test:** e2e steps 08–11.

## BUG-002 — High — Dues reminders are sent back to back for old bills

**Steps**
1. Fresh seed, then Settings → Run automations now, and Run automations now again (or let the scheduler run twice, 60 s apart).
2. Look at the `dues_reminders` table or Billing → Reminders.

**Expected:** each run sends at most one reminder per bill, with a real gap between stages (3 / 10 / 21 days is the design), so one patient gets one message.
**Actual:** on the second run, 6 more dues messages went out. For example, bill A-261021-00003 got stage 1 at 12:08:59 and stage 2 at 12:09:00, one second apart. In a probe, a 40-day-old bill (for example one imported from the billing software) got reminders on 3 consecutive one-minute runs (stages 1, 2 and 3) plus a call task.

**Cause:** `app/automations.py:148-163` (`dues_reminders`) picks the next stage from the bill's **age** only (`age < DUES_STAGES[nxt]`, line 153). It never looks at when the last reminder went out. Fix: add a minimum gap since the previous reminder (for example, the difference between stage thresholds), and start old bills at stage 1.
**Impact:** patients get spam about money (complaint risk), more WhatsApp cost in live mode, and every CSV import of old dues sets it off. The unit test `test_dues_stages` only covers a bill that ages step by step.

## BUG-003 — High — Branch isolation is missing on billing and claims actions

**Steps (TestClient probe)**
1. Create a billing user tied to branch B (Settings → Add login, Branch = B).
2. As that user, POST to `/billing/{id}/payment`, `/billing/{id}/remind`, `/billing/orders/{id}/add` and `/claims/{id}/stage` with IDs of **branch A** records. The CSRF token from that user's own Billing page is enough.

**Expected:** 403 "You don't have access", as `appointment_status` already does (`app/routes/ui.py`, branch check before the update).
**Actual:** all four succeed with 303 and a success message. A ₹100 payment was recorded on a branch-A bill, a branch-A patient got a WhatsApp reminder, a branch-A order was billed and a branch-A claim was moved to Settled.

**Where:** `app/routes/ui.py:434` `billing_remind`, `:446` `billing_payment`, `:459` `billing_add_order`, `:491` `claim_stage`. The same pattern is in `:289` `lead_status` and `:522` `task_done` (found by reading, not yet probed). The list pages are scoped correctly. Only the actions are not.
**Impact:** this breaks rule 5 in PRODUCT_KNOWLEDGE ("sees only what their role and branch allow"), and money can change in the wrong branch. The IDs are sequential, so they are easy to guess.

## BUG-004 — Medium — Messages screen shows every branch's conversations

**Steps:** log in as a front-desk user tied to branch B, then open Messages.
**Expected:** only conversations of branch-B patients and enquiries, or a product decision written down that front desk sees every branch.
**Actual:** branch-A patients' WhatsApp threads are listed and readable (probe: a branch-A patient's name appears).
**Where:** `app/routes/ui.py:535` `messages_page` loads the last 500 messages with no branch filter. Patients (`:378`) is not scoped either. That may be intended (one patient ID across branches), but the Head of Product and Domain Lead must decide.

## BUG-005 — Medium — "Send reminder now" crashes on a paid or missing bill

**Steps:** two staff members have Billing open. One records the full balance of a bill. The other then presses Send reminder now on the same row, which is still on their screen.
**Expected:** a friendly error such as "This bill has no balance due".
**Actual:** an unhandled `ValueError` ("Bill … has no balance due") gives HTTP 500. A bill ID that doesn't exist raises `LookupError`, also a 500.
**Where:** `app/routes/ui.py:434-443`. Only `messaging.SendBlocked` is caught (line 439), while `billing_payment` and `billing_add_order` also catch `ValueError` and `LookupError`.

## BUG-006 — Low — Run automations confirmation is not readable

**Actual:** the message reads "appointment reminders: {'reminder_24h': 35, 'reminder_2h': 4, 'blocked': 4}, … daily owner report: 74". Those are Python dicts, and 74 is a message **id**, not a count.
**Expected:** plain English for the demo, for example "39 reminders sent (4 blocked, no consent) · 11 dues reminders · owner report sent".
**Where:** `app/routes/ui.py:600`.

## BUG-007 — Medium — After a reseed on demo day, no owner report can be sent

**Steps:** run the e2e flow, or the demo, once after 9 am. Reseed (`python -m app.seed`, as DEMO_SCRIPT "Before the meeting" says), then press Run automations now.
**Expected:** the 9 am report is sent, and the dashboard's "9:00 am owner report" shows it. The dashboard text tells the admin to send it from Settings → Run automations.
**Actual:** nothing is sent. `last_owner_report_date` stays in `settings`, which the seed does not wipe (`app/seed.py:3,29`), and `app/automations.py:242-244` skips the report. E2E step 17 fails on the second run of the day.
**Fix idea:** the seed clears `last_owner_report_date`, or the manual "Run automations now" can force the report.

## BUG-008 — Low — Unit tests are out of date after deliberate changes

At different moments today: `tests/test_ui.py::test_login_success_and_dashboard_renders` expected "Owner dashboard" (the heading is now "Operations overview"); `tests/test_patient_app.py::test_pay_records_payment` expected "DEMO" (it passed in a later run); `tests/test_api.py::test_health_needs_no_key` expects `{"ok": true}` but `/api/health` now returns more fields. These are not product bugs. Whoever changes a screen or response updates its test in the same change. Re-run after the redesign. Note for Security: check that the new `/api/health` fields are safe to show without an API key.

## BUG-009 — Low — Reply "1" can confirm a visit that is past or marked no-show

**From reading the code:** `app/routes/webhooks.py:~105-110` sets `status = 'Confirmed'` for the appointment linked to the last reminder, and does not check its current status or time. A patient who replies `1` hours after a missed 2 h-reminder visit (already marked NoShow) changes the visit to Confirmed. That makes the no-show rate on the dashboard and in the owner report wrong.
**Expected:** only Booked visits in the future are confirmed. Otherwise reply "This appointment has passed, reply here to book again" and create a staff task.
**Not yet reproduced** (Phase 2 e2e).

## BUG-011 — Low — Manual dues reminder ignores quiet hours

Found in the Phase 2 run at about 23:35 IST (build 4942f02).
**Steps:** after 9 pm IST, open Billing and press Send reminder now on any bill with a balance.
**Expected:** the same rule as the automations. `run_all` pauses patient messages from 9 pm to 8 am (`app/automations.py:293-307`, "patient messages paused for quiet hours"). Either the manual button holds the message until 8 am, or it asks "It is after 9 pm. Send anyway?"
**Actual:** the payment reminder goes out at once, at night (status `simulated`, which means `sent` in live mode).
**Where:** `app/routes/ui.py:656` `billing_remind` calls `automations.send_dues_reminder` with no `in_quiet_hours` check. Severity is Low because a staff member chose to send it. The Head of Product and Domain Lead should decide whether money reminders at night are acceptable.

## BUG-012 — Low — Hindi patient login is partly English

**Steps:** open /my/login on a phone, tap हिन्दी, enter a mobile number, then tap the "get code" button.
**Expected:** every line in Hindi.
**Actual:** these lines stay in English (screenshot `qa/mobile/my-unknown-hi.png`):
- "If this number is registered with us, we have sent a 6-digit code on WhatsApp to …" (`app/templates/patient/login.html:32`)
- "Demo: your code is on the staff Messages screen." (`:37`)
- "Your health details stay private to you and your hospital." (`:49`)

These lines are hard-coded and do not use `t()`. The field label and buttons are translated correctly.

## BUG-013 — Low — Small touch targets at 390 px

Patient-name links in the Billing, Appointments and Enquiries lists are 21 px tall at phone width. WCAG 2.2 (2.5.8) asks for at least 24 px. They still work, but they are easy to miss with a thumb. Owner: Product Designer / Front-end.

---

## E2E run log

| Date | Build | Result | Notes |
|---|---|---|---|
| 04 Nov 2026, 23:3x IST | 4942f02 (UX round 3), port 8020, TT_OWNER_PHONE set, fresh seed | **23 PASS / 0 FAIL / 0 SKIP of 23** | The 5 failures and 3 skips reported after the redesign were drift in the test script, not product bugs: toasts are now signed (read from the toast region), the simulator moved to its own panel, the code label changed. Runs between 9 pm and 8 am: Run automations correctly sends nothing to patients, so the script creates the reminders by calling the automation functions directly (data setup only) |
| 04 Nov 2026 | security fixes (port 8030, TT_OWNER_PHONE set) | 22 PASS / 1 FAIL / 0 SKIP of 23 | FAIL: 13 (BUG-010, regex in the test script). Without TT_OWNER_PHONE, 17 also fails, because the report is skipped and audited |
| 04 Nov 2026 | working tree, mid-redesign | 17 PASS / 6 FAIL / 0 SKIP of 23 | FAIL: 07 (BUG-002), 09, 10, 11 and 22 (BUG-001), 17 (BUG-007, second seed of the day; it passed on the first run). Screenshots in the QA scratchpad `qa/` folder |
