# Onboarding plan: 2-branch hospital pilot

Owner of this document: Implementation & Customer Success Manager, Tec Tha.
Read with: [GO_LIVE.md](../GO_LIVE.md) (technical steps), [TRAINING_SOPS.md](TRAINING_SOPS.md), [BASELINE_AND_RESULTS.md](BASELINE_AND_RESULTS.md), [SUPPORT.md](SUPPORT.md).

## The pilot in one paragraph

The pilot follows the offer in the demo: **one problem, 30 to 45 days, with a success measure agreed in writing before go-live**. The automations go live at **Branch 1 (the pilot branch)**. **Branch 2** is measured the same way but stays on its old process, so we can compare the two. Branch 2 data may be imported so the owner sees both branches on the Dashboard. Automations for Branch 2 are switched on only after the week-4 review says yes (see "Known product limits" below; this needs care).

Who does what:

- **Tec Tha (TT):** Implementation Manager (IM), founder and engineer (Eng).
- **Hospital (H):** Owner or director (Owner), the hospital's **pilot lead** (one named person, usually the front office or operations manager), front desk, billing and insurance (TPA) desk, IT person or billing vendor.

"Both" means TT does the work and H must approve it or provide something.

## Week 0: Before the pilot starts (paperwork)

| # | Task | Owner | Done when |
|---|---|---|---|
| 0.1 | Pilot agreement signed: branch, problem, 30 to 45 days, fee, success measure (for example "no-shows from X% to Y%" or "₹Z of dues older than 30 days collected") | Both (Owner signs) | Signed copy on file |
| 0.2 | Mutual NDA signed | Both | Signed |
| 0.3 | Data processing agreement (DPA) signed and reviewed by a lawyer | Both (H's lawyer reviews) | Signed |
| 0.4 | Hospital names its pilot lead, and that person gets an hour a day for the first 2 weeks | H (Owner) | Name and phone shared |
| 0.5 | Meta Business account created **in the hospital's name**, and business verification started (this can take several days, so start now) | H creates, TT guides | Verification submitted |
| 0.6 | Server (Indian region) or laptop chosen; account in the hospital's name with TT as admin | Both | Login works |

## Week 1: Discovery visit and baseline

| # | Task | Owner | Done when |
|---|---|---|---|
| 1.1 | **Discovery visit** (half a day at each branch): sit with the front desk, billing desk and TPA desk; follow 3 patients from enquiry to payment; get answers to the open questions in PRODUCT_KNOWLEDGE.md section 9 (which CRM, which billing software, export or API, WhatsApp type, main patient sources) | TT (IM) leads; H gives access | Visit notes written up and sent to the pilot lead within 2 working days |
| 1.2 | List every daily manual task and how long it takes (re-typing, phone follow-ups, Excel reports) | TT (IM) | List agreed with the pilot lead |
| 1.3 | **Baseline measurement** for both branches, last 30 days (method in BASELINE_AND_RESULTS.md): no-show rate, dues older than 30 days, enquiry reply time, enquiry-to-paid conversion, claims past the time limit | Both: H pulls the records, TT calculates | Baseline sheet signed by the Owner |
| 1.4 | Confirm the success measure using the real baseline number (replaces the X, Y and Z in 0.1) | Both (Owner approves) | Written in the pilot agreement or by email |
| 1.5 | Ask the billing vendor for a daily CSV or Excel export of patients and bills (columns in `docs/samples/`) | H asks, TT supplies the column list | First export file received |
| 1.6 | Submit WhatsApp message templates to Meta: appointment reminder, dues reminder, report ready, follow-up reminder, feedback request, owner report | TT drafts, H approves the wording | All submitted |
| 1.7 | Print the consent line and add it to the registration form at **both** branches | H prints and uses it; TT supplies the text | New forms in use at the desk |

Consent line (from GO_LIVE.md): *"I agree to receive appointment, report and billing messages on WhatsApp. Reply STOP to opt out."*
Hindi: *"मैं WhatsApp पर अपॉइंटमेंट, रिपोर्ट और बिल से जुड़े संदेश पाने के लिए सहमत हूँ। बंद करने के लिए STOP भेजें।"*
(Have the Domain & Compliance Lead approve the final wording, and translations for any other local language.)

## Week 2: Setup, data import, consent rollout

| # | Task | Owner | Done when |
|---|---|---|---|
| 2.1 | Install, HTTPS, environment settings, nightly backup, **test one restore** (GO_LIVE.md section 2) | TT (Eng) | Restore tested and written down |
| 2.2 | Settings → **Hospital and branch names**: enter the real names | TT (IM) | Names show on every screen |
| 2.3 | Settings → **Staff logins**: one login per person, with the right role and branch. No shared logins. Front desk and billing staff are tied to their own branch | TT creates, H gives the staff list | Every trained person can log in |
| 2.4 | Doctors list per branch loaded (names, specialty) so the front desk can book | Both | Appointments → Book an appointment shows every doctor |
| 2.5 | **Data import**, test run: Import → Patients, then Import → Bills, using last month's export. Check "Rows that need fixing" and fix them at the source | TT runs, H fixes the source data | Fewer than 2% of rows rejected, and every rejected row explained |
| 2.6 | Spot check: 20 random patients and 20 random bills compared side by side with the billing software (name, mobile, total, paid, balance) | Both (H's billing desk checks) | 40 of 40 match, or each difference is explained |
| 2.7 | Agree the daily import routine: who exports, at what time, who uploads | Both | Named person and time agreed |
| 2.8 | **Consent rollout at registration**: every new or returning patient is asked; the desk ticks "Patient agrees to WhatsApp reminders and reports" when booking, or presses **Record consent** on the patient's page | H (front desk); TT trains | Consent recorded for most patients registered this week (track the count daily) |
| 2.9 | Old patients: set `consent=yes` in the patients CSV **only** where the hospital holds a signed or recorded consent. Never mark yes in bulk without proof | H decides; TT imports | Pilot lead confirms in writing |
| 2.10 | Staff training sessions (see TRAINING_SOPS.md): front desk, billing and TPA desk, doctors, owner | TT (IM) | Each person has done the practice tasks in simulator mode |
| 2.11 | Practice day in **simulator mode**: staff use the real screens on real workflows; nothing goes to patients | Both | No open questions from staff |
| 2.12 | Meta templates approved; live mode switched on with the hospital's number; one test message sent to the pilot lead's phone | TT (Eng) | Test message received |

## Week 3: Go-live and hypercare

**Go-live day: a weekday morning, Tuesday to Thursday. Not a Monday and not the day before a holiday.** IM is at the pilot branch from opening time.

| # | Task | Owner | Done when |
|---|---|---|---|
| 3.1 | Go/no-go call at 9 am with the pilot lead using the checklist below | Both | Every box ticked, or the date is moved |
| 3.2 | Switch on the **pilot problem's automation only** (for example appointment reminders). Watch the **Messages** screen all day: every message is Sent, Failed (with Meta's error) or Blocked (no consent) | TT (Eng, IM) | End-of-day count of sent, failed and blocked shared with the pilot lead |
| 3.3 | Daily 10-minute stand-up with the pilot lead (in person days 1 to 3, then phone) | Both | Notes kept |
| 3.4 | Daily: check **Tasks** (missed calls, complaints, stuck claims) are being closed by staff, not piling up | H (pilot lead); TT reviews | Open tasks older than 1 day: 0 or explained |
| 3.5 | Daily: data import done on time | H | Import result screen shows today's file |
| 3.6 | Daily: Settings → **Audit log** checked for `automation_error` | TT (Eng) | None, or a fix logged |
| 3.7 | Owner gets the 9 am WhatsApp report from day 2 | TT | Owner confirms it arrived and is readable |

**Hypercare** runs from go-live until the end of week 4: same-day fixes, IM reachable on phone and WhatsApp during OPD hours, and a daily check of the numbers. See SUPPORT.md.

## Week 4: Hypercare and review

| # | Task | Owner | Done when |
|---|---|---|---|
| 4.1 | Add the second automation only if week 3 was stable (for example dues reminders after appointment reminders) | Both (pilot lead agrees) | Agreed by email |
| 4.2 | Staff refresher, 20 minutes, on whatever went wrong in week 3 | TT (IM) | Done |
| 4.3 | **Week-4 review meeting** (45 min) with the Owner and pilot lead: pilot branch against baseline, pilot branch against Branch 2, issues log, staff feedback, consent coverage. Use the results template in BASELINE_AND_RESULTS.md, clearly labelled **early results (2 weeks live)** | TT (IM) presents; Owner decides | Written decision: continue as is / change / stop |
| 4.4 | Decide next step: extend to day 45, add Branch 2, add the next problem, or stop | H (Owner) | Decision recorded |
| 4.5 | Hand over from hypercare to normal support (SUPPORT.md) | TT | Pilot lead has the support numbers and severity levels |

## Day 30 to 45: Pilot close

- Final results report (BASELINE_AND_RESULTS.md template) against the success measure agreed in week 1.
- Owner decides: both branches, CRM and billing sync, monthly partnership (PRODUCT_KNOWLEDGE.md section 8). Sales Lead owns the offer.

## Go-live checklist (tick every line on the morning of go-live)

**Paperwork and accounts**
- [ ] NDA, DPA and pilot agreement signed, with the success measure written as a number.
- [ ] WhatsApp Business account, number, server and data are **in the hospital's name**; Tec Tha is admin only.
- [ ] Baseline sheet signed by the Owner.

**System**
- [ ] HTTPS works; Settings → Automations shows **Live**.
- [ ] Meta templates for the automation going live are **approved** (not pending).
- [ ] Test WhatsApp received on the pilot lead's phone, and a reply (`1`) was received back on the Messages screen.
- [ ] Backup ran last night, and a restore has been tested at least once.
- [ ] Audit log shows no `automation_error` in the last 24 hours.
- [ ] `TT_OWNER_PHONE` is the owner's real number; the payment link and review link are the hospital's real links, not example URLs.

**Data**
- [ ] Today's patients and bills imported; "Rows that need fixing" reviewed.
- [ ] 20 patients and 20 bills spot-checked against the billing software.
- [ ] Doctors listed for each branch.
- [ ] Consent recorded only where the patient actually agreed. Patients without consent show "No consent: no messages are sent".

**People**
- [ ] Every staff member on shift has their own login and has logged in once.
- [ ] Front desk, billing desk and doctors trained and have done the practice tasks.
- [ ] Printed one-page SOP at each desk (TRAINING_SOPS.md).
- [ ] Pilot lead knows how to report a problem and the severity levels (SUPPORT.md).
- [ ] Plan B agreed: if the system is down, the desk works the old way (paper register, phone calls) and enters the data later. Patients are never made to wait for the software.

**Go / no-go:** if any line in "System" or "Data" is not ticked, move go-live by one day. Do not go live partly ready.

## Known product limits that affect this plan (for the Head of Product and Architect)

These came from reading the current code (`app/routes/ui.py`, `app/auth.py`, `app/config.py`). The plan above works around them; they should be fixed before a wider rollout.

1. **No per-automation or per-branch switch.** `TT_SCHEDULER` turns all automations on or off together, for all branches. GO_LIVE.md says "turn on one automation at a time", and the pilot runs at one branch, but neither can be done from Settings today. Workaround until fixed: control by data and consent (import only the pilot branch's bills while dues reminders are being tested; Branch 2 does not record WhatsApp consent until it joins). This is fragile, so the Engineer must confirm it before go-live.
2. **No owner role.** The Dashboard is visible only to the `admin` role, and admin can also change users and settings. The owner either gets an admin login (too much power) or only the 9 am WhatsApp report. A read-only owner role is needed.
3. **No "dues older than 30 days" figure on screen.** Billing → Pending dues has an Age column, but there is no total for dues older than 30 days. It is counted by hand for now (see BASELINE_AND_RESULTS.md).
4. **No way to disable a staff login from Settings.** The Staff logins table shows Active or Disabled, but only "Add login" exists. Leavers must be disabled by the Engineer directly for now.
5. **Consent wording on screen** ("Patient agrees to WhatsApp reminders and reports") is shorter than the form's wording (which also covers billing messages). The Domain & Compliance Lead should align the two.
