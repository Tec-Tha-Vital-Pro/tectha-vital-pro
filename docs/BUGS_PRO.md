# Tec Tha Vital Pro — Bug list (QA release pass)

Owner: QA Lead. Build: `pro-foundation` at 8a91943. Run date: 05 Nov 2026, about 10:00–11:00 IST.
Environment: fresh seed (`python -m app.seed`), simulator mode, `TT_SCHEDULER=off`, server on 127.0.0.1:8021.
Logins: admin and owner (no branch); doctor, nurse, lab, pharmacy, billing (branch A); frontb (front desk, branch B).
All patient data is **sample data** from the seed.

How to reproduce any item: run `tests/e2e/pro_flow.js` on a fresh seed (see TEST_PLAN.md, Pro section). The step that
fails is given for each bug.

Severity: **Critical** = patient harm or data leak likely, stop everything. **High** = wrong clinical or money result,
legal exposure, or a role cannot do its job; blocks release. **Medium** = wrong result with a workaround, or a safety
net missing. **Low** = cosmetic or demo-only.

| ID | Severity | Area | Title | Status |
|---|---|---|---|---|
| BUG-P01 | High | Pharmacy / roles | Pharmacy role is locked out of its own screen. Front desk and billing can dispense Schedule H drugs instead | Open |
| BUG-P02 | High | Lab / roles | Front desk and nurses can collect, receive and enter lab results and record critical call-outs | Open |
| BUG-P03 | High | Radiology / roles | Front desk can tick Form F, mark scans performed and sign radiology reports. The "Lab / radiology" role can't do radiology | Open |
| BUG-P04 | High | Lab / clinical | A patient with no age or sex is judged against the child reference range, and abnormal adult results are auto-verified as normal | Open |
| BUG-P05 | Medium | Pharmacy, lab / idempotency | A double-click on Dispense also creates the bill. A double-click on Collect skips Receive | Open |
| BUG-P06 | Medium | Lab, radiology / patient identity | Ordering by mobile number silently uses the existing patient and ignores the typed name | Open |
| BUG-P07 | Medium | Lab / input checks | Impossible result values are accepted (potassium −45), which raises a false critical alert | Open |
| BUG-P08 | Low | Seed / demo | The seeded open critical value is timestamped 15 minutes in the future | Open |
| BUG-P09 | Low | Appointments / mobile | At 390 px the Appointments page scrolls sideways (424 px wide) because of the filter chips | Open |

No Critical bugs. **4 High, 3 Medium, 2 Low.**

---

## BUG-P01 — Pharmacy role is locked out. Front desk and billing can dispense Schedule H drugs instead

- **Severity:** High (a role can't do its job at all, plus a regulatory exposure: Schedule H/H1 dispensing by non-pharmacy staff)
- **Where:** `app/routes/diagnostics.py:15` `RX_ROLES = {"admin", "frontdesk", "billing", "pharmacist"}` and `:16` `VIEW_ROLES`. The role in `app/auth.py:27` is `pharmacy`, not `pharmacist`. The same wrong name is in `app/routes/command.py:12` (`NOTIFY_ROLES`). The pharmacy login is sent to this screen by `app/routes/ai_features.py:166`.
- **Steps:**
  1. Log in as `pharmacy` (role Pharmacy, branch A).
  2. You land on `/diagnostics`.
  3. Open `/diagnostics?tab=rx`.
- **Expected:** The Pharmacy counter opens, and the pharmacist can Dispense and Create bill. Only pharmacy staff (and admin) dispense Schedule H/H1/X drugs and sign the register.
- **Actual:** HTTP 403 "You don't have access to this screen" on the home page right after login, and on every Diagnostics tab. Front desk and billing logins can press Dispense, and the Schedule H register then records `dispensed_by = user:frontb` or `user:billing`.
- **e2e:** P01 (pharmacy), P22.
- **Fix hint (for Backend):** use `pharmacy` in `RX_ROLES` and drop `frontdesk` and `billing` from dispensing (billing may keep Create bill). Remove the unused role names `pharmacist` and `radiology` everywhere. Add a role × screen test for every role in `auth.ROLES`.

## BUG-P02 — Front desk and nurses can enter lab results and record critical call-outs

- **Severity:** High (clinical data entry by non-lab staff; a normal value is auto-verified and shown to the patient with no lab person involved)
- **Where:** `app/routes/diagnostics.py:12` `LAB_ROLES = {"admin", "doctor", "frontdesk", "lab", "nurse"}`. It guards ordering, and also `lab_advance` (`:146`), `lab_result` (`:157`) and `lab_callout` (`:192`).
- **Steps:**
  1. Log in as `frontb` (front desk, branch B).
  2. Open Diagnostics → Laboratory. Collect, Receive and the result box are all shown.
  3. On a branch-B test in Collected, press Receive, then type a normal value and press Advance.
- **Expected:** Front desk can order a test. Only lab staff (and doctors and admin) collect, receive, result and call out. Nurses may collect a sample at the bedside, but should not enter results.
- **Actual:** Front desk moved lab order 9 from Collected to Received (HTTP 200). A normal result entered by front desk is auto-verified, and the patient sees it in /my. Front desk can also record a critical-value call-out with read-back.
- **e2e:** P19.

## BUG-P03 — Front desk can sign radiology reports. The Lab / radiology role can't do radiology

- **Severity:** High (a radiology report is a clinical document, and the PCPNDT Form F confirmation can be ticked by front desk)
- **Where:** `app/routes/diagnostics.py:14` `RAD_ROLES = {"admin", "doctor", "frontdesk", "radiology"}`. There is no `radiology` role. `app/auth.py:29` labels `lab` as "Lab / radiology", and `auth.LAB` says it covers the radiology worklists.
- **Steps:**
  1. Log in as `lab` (branch A) and open Diagnostics → Radiology. There is no Performed or Write report button.
  2. Log in as `frontb` and open Diagnostics → Radiology. On the branch-B CT "Head plain" (Performed), press Write report, type text and save.
- **Expected:** Lab / radiology staff (and doctors and admin) perform and report scans. Front desk only schedules them.
- **Actual:** The lab role sees no actions. Front desk saved the report: scan 3 became Reported with `reported_by = user:frontb`. Front desk can also tick "Form F completed" and mark an obstetric ultrasound performed.
- **e2e:** P21.

## BUG-P04 — Child reference range used for patients with no age or sex; abnormal adult results auto-verified

- **Severity:** High (a wrong "normal" result is released to the patient without a pathologist)
- **Where:** `app/diagnostics.py:32-44` `reference_range()`. When `age` is None the age check is skipped (`:39`), and when sex is unknown only `sex='A'` rows match. For HCT and CREAT the only `A` row is the child range 0–12 years (`RANGES`, `:355-360`). The Order a test dialog (`app/templates/diagnostics.html:90-95`) never asks for age or sex, so every patient created there has neither.
- **Steps:**
  1. As `lab`, use Order a test for a new patient (name and mobile only). Choose Haematocrit.
  2. Collect, Receive, then enter 37 and press Advance.
- **Expected:** With no age or sex there is no safe reference range. The result should wait for a pathologist (no auto-verify), and the screen should say the range is unknown. (37% is low for an adult man, whose range is 40–50.)
- **Actual:** The range is set to 35–41 (the child range), the flag is N, `validated_by = auto-verify`, and the patient app shows it as validated. The same happens for creatinine: an adult with 0.5 mg/dL is judged against 0.3–0.7.
- **e2e:** P17.

## BUG-P05 — Double-submit moves the workflow two steps (Dispense → Billed, Collect → Received)

- **Severity:** Medium (no money is lost, because the bill amount is right, but a bill is created before the pharmacist meant to. On the lab side the "Received in lab" time is faked, which breaks sample chain-of-custody)
- **Where:** `app/routes/diagnostics.py:233` `rx_advance` and `:146` `lab_advance` post only "advance", with no expected current state. `app/diagnostics.py:277` `advance_rx` and `:76` `advance` move from whatever the state is now.
- **Steps:** As admin, on Pharmacy counter, send the Dispense form twice (double-click on a slow network, or two tabs).
- **Expected:** The second submit is refused ("already dispensed") or does nothing. The prescription stays Dispensed.
- **Actual:** Prescription 3 ended as Billed with a new bill (bill 350) from two Dispense clicks. Collect clicked twice moves a sample straight to Received.
- **e2e:** P24.
- **Fix hint:** send the expected `from` status in each form and refuse a mismatch. The same pattern is already used for findings ("already decided").

## BUG-P06 — Lab or radiology order by mobile number silently uses the existing patient

- **Severity:** Medium (risk of putting a test on the wrong patient's record. The toast does show the matched name, which is the only warning)
- **Where:** `app/routes/diagnostics.py:42` `_patient_from_form` → `patients.find_or_create(name, phone)` matches on phone only, and the typed name is dropped.
- **Steps:** As admin, Order a test with name "Totally Different Person" and the mobile number of the seeded patient Rekha Kulkarni.
- **Expected:** A confirmation step: "This number belongs to Rekha Kulkarni (TT-000005). Order for her?" Or a choice from the patient search.
- **Actual:** The order is created for Rekha Kulkarni (lab order 15), and the toast says "Test ordered for Rekha Kulkarni". Nothing asks the user to confirm the name change.

## BUG-P07 — Impossible lab values accepted and raised as critical

- **Severity:** Medium (false critical alerts to doctors and the owner; alarm fatigue on a safety feature)
- **Where:** `app/routes/diagnostics.py:157-165` `lab_result` accepts any float.
- **Steps:** Receive a potassium test and enter `-45`.
- **Expected:** "That value is not possible for Serum potassium (mmol/L). Check and enter again." The same kind of plausibility limits that NEWS2 vitals already have.
- **Actual:** The value is stored as −45, flagged LL, a call-out is opened, and "Critical value: Serum potassium -45 mmol/L" goes to doctors and admin.

## BUG-P08 — Seeded open critical value is timestamped in the future

- **Severity:** Low (demo only)
- **Where:** `app/diagnostics.py:409` plan row `(11, "B", "K", 25, "Resulted", 2.3)` is resulted at +40 min (`:422`), which is 15 minutes after now.
- **Actual:** The result time and the call-out's `created_at` are 15 minutes in the future, so the "not called out in 15 min" escalation can't fire until about 30 minutes after seeding. Seed this row about 60 minutes ago.

## BUG-P09 — Appointments page scrolls sideways at 390 px

- **Severity:** Low (phone width; page is 424 px wide)
- **Where:** `app/templates/appointments.html:25-27`. The chips "All 21 · Not confirmed 10 · Still to come 17" don't wrap or scroll inside their own row.
- **Steps:** Open Appointments as nurse or admin at 390 × 844.
- **Expected:** No horizontal page scroll (as in the pilot release check).
- **Actual:** `scrollWidth` is 424 against a 390 viewport.

---

## Checked and not a bug

- Login `next=/\example.org`: Starlette URL-encodes the backslash (`Location: /%5Cexample.org`), so the browser stays on the site. There is no open redirect.
- The lab worklist at 390 px scrolls inside its own panel (by design, like the claims board).
- NEWS2 scoring matches the RCP 2017 table for every parameter used in P31 (25 / 91 / air / 90 / 131 / A / 39.5 → 14).
