# Tec Tha Vital: Compliance and Workflow Review

Owner: Healthcare Domain & Compliance Lead
Date: 4 Nov 2026
Status: Draft for the founder, Head of Product, Architect and Security. This is not legal advice. A lawyer must check every legal statement before the first client goes live. Hospital-specific items (NABH policy numbers, retention periods) must be confirmed with the client's Medical Records Officer and Quality Manager.

## How to read this document

- **Code references** use `file:line`. They were taken from the repo on 4 Nov 2026.
- **[VERIFY]** means the statement comes from my working knowledge or from secondary commentary. Web access from this session was limited: I could search, but I could not open the official gazette texts. Confirm each [VERIFY] item against the official text, or with a lawyer, before you quote it to a client.
- **Sources I could reach** were news and law-firm summaries, not the primary texts:
  - IRDAI Master Circular on Health Insurance Business, 29 May 2024: a cashless decision within 1 hour of the request, and final discharge authorisation within 3 hours of the discharge request. Sources: [The Week](https://www.theweek.in/news/india/2024/05/30/irdai-issues-new-master-circular-to-make-health-insurance-claims-process-more-seamless.html), [Business Today](https://www.businesstoday.in/personal-finance/insurance/story/health-insurance-irdai-sets-3-hour-time-limit-for-insurers-to-clear-cashless-claims-details-here-431354-2024-05-29), [ThePrint](https://theprint.in/economy/cashless-claims-within-an-hour-and-discharge-from-hospital-in-3-hours-says-irdais-master-circular/2107998). Primary text: irdai.gov.in [VERIFY that no later amendment changes this].
  - DPDP Rules 2025, notified 13 Nov 2025 with a phased start: breach intimation to the Board without delay, then a detailed report within 72 hours; the Fourth Schedule partly exempts clinical establishments from the children's-data rules. Sources: [Protiviti](https://www.protiviti.com/sites/default/files/2025-11/flash_compliance_update_dpdp_rules-2025.pdf), [KPMG](https://assets.kpmg.com/content/dam/kpmgsites/in/pdf/2025/11/dpdp-rules-2025-guidance-to-dpdp-act-implementation.pdf), [dpdpa.com Fourth Schedule](https://www.dpdpa.com/schedule/schedule4.html), [Storyboard18](https://www.storyboard18.com/digital/breaking-govt-notifies-final-dpdp-rules-sets-staggered-rollout-with-key-obligations-for-data-fiduciaries-84201.htm). Primary text: the MeitY gazette notification [VERIFY rule numbers; commentary disagrees on whether the children's exemption sits under rule 11 or rule 12].

**Roles under DPDP.** The **hospital is the Data Fiduciary**. **Tec Tha is a Data Processor** acting on the hospital's written instructions. Meta (WhatsApp), the hosting provider, the payment gateway, the telephony provider and Anthropic (when the AI receptionist is on) are **sub-processors**.

---

## Part 1: Workflow review, one automation at a time

### 1.1 Appointment reminders: 24 h and 2 h (`app/automations.py:53-82`)

**Fits real practice?** Mostly. Indian OPDs see heavy no-shows, and a reminder the day before plus one on the day is standard. Asking the patient to reply 1, 2 or 3 works well.

**Gaps and risks**
1. **No quiet hours.** The scheduler runs every 60 s, all day and night (`app/scheduler.py`). A 2 h reminder for a 7:30 am slot goes out at 5:30 am. An appointment booked at 11 pm for the next morning gets its 24 h reminder at 11 pm.
2. **The specialty is printed in the message** (`automations.py:60-61`, "(Psychiatry)", "(Oncology)", "(Obstetrics)"). It appears on the lock-screen preview, and in India the phone is often shared with family. That reveals health information to other people.
3. **Shared family phones.** In India one mobile number often books for a child, a spouse or an elderly parent. The message names the patient, which is correct, but consent has to come from the phone owner or guardian (see 1.9 and Part 2).
4. **Reply "3" cancels at once with no check** (`app/routes/webhooks.py:103-106`). A mis-tap loses the slot.
5. **The 2 h reminder repeats the 24 h one.** If the patient already confirmed, ask for nothing more. A "see you soon" with the token number or directions is enough.
6. **Minors and deceased patients are not handled** (see 1.9).
7. **Live mode sends free text** (`app/messaging.py:63`). Outside the 24-hour customer-service window Meta accepts only approved templates, so every reminder will fail in production until the templates in Part 3 are approved.

**Fixes:** add quiet hours (no automated patient message between 9 pm and 8 am IST; hold the message and send it at 8 am, or skip it if the appointment has already passed). Drop the specialty from the text. Send interactive quick-reply buttons: Confirm / Reschedule / Cancel. On Cancel, ask "Are you sure? Reply YES to cancel." Once the patient has confirmed, send a different 2 h message. Send by template name with parameters.

### 1.2 Feedback request (`automations.py:85-98`) and feedback replies (`webhooks.py:75-89`)

**Fits real practice?** Yes. NABH patient-centred standards expect patient feedback to be collected and complaints handled with tracked closure [VERIFY current NABH 5th/6th edition chapter numbers].

**Gaps and risks**
1. **Review gating.** The Google review link goes only to patients who scored 4 or 5 (`webhooks.py:87-88`), while scores of 3 or lower go to the manager. Google's review policy forbids selectively asking satisfied customers for reviews [VERIFY current Google Business Profile policy]. A request for a review is also likely to be classed as **marketing** by Meta, not utility [VERIFY Meta category rules].
2. **The low-score reply promises "will call you today"** (`webhooks.py:85`), but the task is due in 24 h (`webhooks.py:84`). A score left at 10 pm on a Saturday cannot get a call "today". A broken promise turns a complaint into a public review.
3. **A score of 3 escalates as a complaint.** That is defensible as a policy, but it should be a setting. Also, nothing asks the patient for a free-text reason, although `feedback.comment` exists (`schema.sql`).
4. **It goes to every "Visited" OPD appointment.** That includes minors, visits that ended in admission or referral, and patients who died later. For IPD it should go after discharge, not after the OPD slot.
5. **Context is fragile.** The reply is matched to the *last outbound template* (`webhooks.py:71-75`). If a dues reminder goes out in between, "5" is no longer read as a feedback score.

**Fixes:** offer the review link to everyone who replies, or to nobody automatically; let staff send it by hand. Or run it as a separately consented marketing message. Change the low-score reply to "Our patient relations team will call you within 24 hours (9 am to 7 pm)." Ask "Would you like to tell us what went wrong?" and store the answer in `feedback.comment`. Skip patients who are deceased, admitted, or under 18 unless a guardian is recorded. Keep conversation context per related item instead of relying on the last template.

### 1.3 Dues reminders (`automations.py:101-156`, manual send `app/routes/ui.py:429-438`)

**Fits real practice?** Only in part. In Indian hospitals, **IPD bills are usually settled before discharge**: the discharge summary and gate pass are held until billing clears. Patient dues that are actually outstanding are mostly:
- OPD or diagnostics credit for known patients;
- the amount the insurer disallowed or co-pay after a TPA settlement (often found weeks after discharge);
- staff, corporate or panel credit (here the **company** pays, not the patient);
- PM-JAY and other government schemes, where the patient owes **nothing** for package-covered care. The scheme is cashless and charging the beneficiary is not allowed [VERIFY NHA guidelines].

**Gaps and risks (high)**
1. **Who pays is not checked.** `bills` has no payer type or link to `claims` (`schema.sql`, bills table; `billing.py`). The code computes `total - paid` (`automations.py:116`) and asks the **patient** to pay the whole balance, even while a TPA claim is pending or the patient is a PM-JAY beneficiary. Sending a PM-JAY beneficiary a demand for money could be treated as a scheme violation. It also causes complaints to the insurer and the hospital.
2. **Every bill item is listed on WhatsApp** (`automations.py:119-128`). Items such as "HIV ELISA", "Psychiatry consult", "MTP" or "Chemotherapy" are health data, sent to a lock screen that others may see. The message should give the amount and a link to the bill only.
3. **Tone and frequency.** Three stages at days 3, 10 and 21 (`automations.py:12`) is reasonable. But every stage uses the same wording, there is no option to dispute the bill, and no contact number is given. Hospitals are not bound by RBI's recovery-agent guidance, but the same principles apply: polite wording, sensible hours, and no pressure or threats.
4. **Quiet hours are missing** (same issue as 1.1).
5. **Staff can send the manual reminder repeatedly** (`ui.py:429-438`). Each click moves the stage forward (`automations.py:131`), with no daily cap.
6. **The payment link is built from `bill_no`** (`automations.py:121`). Bill numbers are predictable (`billing.py`, `{branch}-{yymmdd}-{id}`). If the payment page shows bill details, anyone can guess other bills. The link needs a signed token that cannot be guessed. This is a question for Security.
7. **Deceased patients.** A dues message to the family of a patient who died in the hospital is the worst possible outcome. There is no status to stop it.

**Fixes:** add `bills.payer_type` (Self / TPA-Insurance / PM-JAY / State scheme / CGHS / ECHS / Corporate / Staff) and `bills.patient_payable`. Send reminders only for the **patient-payable** part, never for PM-JAY or scheme bills, never for corporate credit, and never while a linked claim is still open. Stop listing items; show the bill number, the amount due and a secure link. Add "Questions about this bill? Call {{billing desk number}}" and "If you have already paid, please ignore this message." Cap manual reminders at one per bill per 24 h. Suppress all reminders if the patient is deceased. Send a stage-3 "call" task to a human, as the code already does, and make the human call the default from then on.

### 1.4 Follow-up reminders (`automations.py:161-179`)

**Fits real practice?** Yes: post-op reviews, suture removal, ANC visits, diabetic reviews and dialysis schedules.

**Gaps and risks**
1. **The `reason` text is free and goes straight into the message** (`automations.py:170`), for example "your chemotherapy cycle 3 review". This is the same lock-screen exposure as 1.1.
2. **Only one reminder is sent.** If the patient does not reply, no task is created, and clinically important follow-ups (post-op, ANC, oncology) are lost quietly.
3. **Who created the follow-up is not recorded.** There is no doctor and no clinical priority. The software must not decide clinical urgency (rule 7.2), but it should carry the doctor's priority flag.
4. **Minors and deceased patients** are not handled (see 1.9).

**Fixes:** send a generic "follow-up visit with Dr {{name}}". Keep `reason` internal. If there is no reply or booking within 48 h, create a `followup_call` task. For follow-ups the doctor marked high priority, make the task immediate. Add `followups.doctor_id` and `followups.priority`.

### 1.5 Claims alerts (`automations.py:195-205`, `billing.py:7`, `schema.sql:109-111`)

**Fits real practice?** The idea is right: the 1-hour and 3-hour IRDAI limits are what TPA desks fight over every day. The model is too simple, though.

**Gaps and risks**
1. **PM-JAY is treated as an insurer** (`app/seed.py:26` lists "PM-JAY" among insurers). The IRDAI timelines apply to **insurers and TPAs under IRDAI**, not to PM-JAY or state schemes. Those have their own pre-auth and claim turnaround times set by NHA or the State Health Agency [VERIFY current NHA TAT]. The claims screen states "1 hour / 3 hours" for every card (`app/templates/claims.html:6`), which is wrong for PM-JAY.
2. **Stages that drive real delays are missing:** *Query raised by TPA* (the most common hold-up), *Query replied*, *Enhancement requested/approved*, *Partially approved*, *Discharge request sent*, *Reimbursement* (non-cashless), *Settled-short* (disallowance, which then becomes patient dues).
3. **The clocks.** The 1 h pre-auth clock should start when the **complete** request is submitted, and it pauses while a query is open [VERIFY against the circular]. The code restarts the clock on every stage change (`billing.py` `set_claim_stage`). That is fine, but because there is no query state, a claim waiting on a hospital-side query is reported as an insurer delay.
4. **Approved claims with no next step are never flagged:** `PreAuthApproved` for days with no discharge, and `FinalSent` → `Settled` taking more than 30 days. The settlement ageing that owners care about is not reported.
5. **Claims are not linked to bills or admissions**, so dues (1.3) cannot be fixed until they are.
6. **Night shift.** IPD discharges happen until late at night. Tasks are created, but nobody is paged. A discharge request sent at 9 pm that is still waiting at midnight costs a bed-day.
7. **For the hospital's side of a disputed delay** (evidence for an IRDAI grievance or for the circular's provision on extra charges caused by a late discharge approval [VERIFY]), keep the request and response timestamps with an audit trail. The code does this partly through `audit_log`.

**Fixes:** add `claims.payer_type` (Insurer-via-TPA / Insurer-direct / PM-JAY / State scheme / CGHS / ECHS / Corporate), `claims.tpa`, `claims.bill_id`, `claims.admission_no` and `claims.claim_type` (cashless / reimbursement). Set the time limit **per payer type in configuration**, not in code. Add the missing stages listed above, plus a "settlement older than 30 days" alert. Send night-time escalation to the on-duty TPA executive's phone. That person is staff, so patient consent is not involved.

### 1.6 Unbilled services (`automations.py:184-192`, `billing.py:86-106`)

**Fits real practice?** For OPD lab, radiology and pharmacy, yes. Leakage there is real, and a 2-hour check is sensible.

**Gaps and risks**
1. **IPD is not separated from OPD.** IPD charges sit on a running interim bill and are finalised at discharge. Every IPD ward order, bed-day or consumable will raise a "Not billed" task after 2 h, and staff will soon ignore the alert altogether.
2. **Package billing.** For PM-JAY and insurer packages, services inside the package are *deliberately* not billed one by one. They should be marked "included in package", not flagged.
3. **Cancelled or returned orders** (a cancelled test, returned medicines) have no status, so they stay "unbilled" for ever.
4. **`add_order_to_bill` attaches the order to the latest open bill for that patient and branch** (`billing.py:91-95`). That bill could be the wrong encounter: an OPD bill, or a bill under a claim. In practice this mixes OPD and IPD charges and breaks the claim file.

**Fixes:** add `orders.encounter_type` (OPD/IPD/Daycare/Emergency), `orders.encounter_no`, `orders.status` (Active/Cancelled/Returned) and `orders.package_included`. For IPD, check unbilled orders **at the discharge-initiated event** instead of after 2 h. Attach orders only to a bill for the same encounter.

### 1.7 Owner daily report (`automations.py:210-236`)

**Fits real practice?** Yes. Owners of mid-size hospitals want exactly this at 9 am.

**Gaps and risks**
1. **The default owner number is a real-looking mobile** (`app/config.py:39`, `919900000000`). If `TT_OWNER_PHONE` is not set in live mode, the hospital's revenue figures go to a stranger. Make it required in live mode, the same way the app secret is required.
2. **The report has no IPD figures:** admissions, discharges, bed occupancy, ALOS, TPA settlements received. For a hospital (as against a clinic) these are the key numbers.
3. **No patient data appears in the report.** That is good; keep it so.
4. In live mode it needs an approved utility template, or the owner has to message the number daily to keep the 24-hour window open.

### 1.8 Inbound replies (`webhooks.py:38-112`)

**Gaps and risks (high)**
1. **Emergency handling when AI is off.** Emergency triage exists only in the AI prompt (`app/ai/prompts.py:22`, `app/ai/receptionist.py:222-225`). AI is **off by default**. With AI off, "my father has chest pain, what to do" gets the reply "Our team will reply to you shortly" (`webhooks.py:111`) and a task due in **30 minutes** (`webhooks.py:110`). This is clinically unsafe.
2. **STOP is exact-match English only** (`webhooks.py:46`). "Stop", "STOP messages", "band karo", "बंद करो", "unsubscribe" and "no more messages" are not caught. No confirmation is sent, and START cannot turn messages back on.
3. **The welcome message to a new number** (`webhooks.py:66-68`) asks for name and problem but gives **no privacy notice**. This is the first point where personal data is collected.
4. **Lead names** are stored as "WhatsApp enquiry". That is acceptable, but the free text (which can be health data) is kept with no retention limit.
5. **Matching on phone only.** A message from the shared family phone is attributed to whichever single patient owns that number (see 1.9).

**Fixes:** add a **deterministic emergency keyword check that runs before everything else, AI on or off.** It should catch English, Hindi and Hinglish: chest pain, सीने में दर्द, saans nahi, breathing, unconscious, behosh, bleeding, khoon, accident, poison, zehar, seizure, daura, suicide, pregnant + bleeding, and so on. It replies at once: "If this is an emergency, call 108 or come to {{hospital}} Emergency, {{address}}, now. Emergency phone: {{number}}". It also creates an urgent task due now. Use keyword matching only; never give a diagnosis. Extend opt-out matching (STOP, UNSUBSCRIBE, बंद, band, रोकें), always send a confirmation, and add START. Add a short privacy notice line, with a link, to the first reply to an unknown number.

### 1.9 Issues that cut across every automation

| Topic | What the code does today | Real-world issue | Fix |
|---|---|---|---|
| **One patient per phone** | `patients.phone` is UNIQUE (`schema.sql:13`). `find_or_create` matches on phone and **ignores the name** (`app/patients.py:9-22`) | A mother registering her child, or a son registering his father, either merges two people into one record or is silently given the wrong person's record. Bills, follow-ups and the patient app login (`app/routes/patient_app.py`, OTP by phone) then show one person's health data to another. This is a confidentiality breach and a wrong-patient safety risk. | Remove UNIQUE on phone. Add `patients.contact_phone` with `relationship` (Self/Parent/Spouse/Child/Guardian/Other). Match on phone **+ name + age/DOB**, and send near-matches to staff instead of auto-merging. The patient app should list the profiles linked to the phone, with a consented "family account" (a planned feature). |
| **Minors** | `age` is stored (`schema.sql:14`) and not used. The seed creates patients aged 2+ (`seed.py:67`) | DPDP s.9 requires verifiable parental consent for anyone under 18. Clinical establishments are partly exempt **only for providing health services** (Fourth Schedule) [VERIFY]. Reminders count as health-service communication; feedback and review requests probably do not. | Add `guardian_name`, `guardian_relationship` and `guardian_consent_at`. Use DOB, not age. For under-18s, send messages only to the guardian's number and only with guardian consent; no feedback or review links; and no AI conversation unless a guardian is involved. |
| **Deceased patients** | There is no status | Reminders, dues, feedback and follow-ups would go to the bereaved family. NABH and basic decency both forbid this. | Add `patients.status` (Active/Deceased/Merged/Inactive) with `deceased_at`. Every automation must skip a non-Active patient. Make it a hard filter in `messaging.send` for template sends. Bereavement dues go to a manual billing task only. |
| **IPD vs OPD** | The model is OPD only: appointments use "OPD-{id}"; there is no admission entity | Discharge, TPA, interim bills and unbilled checks all depend on the admission. | Add `admissions` (admission_no, branch, admitted_at, discharged_at, payer_type, status), linked to bills, orders and claims. |
| **Quiet hours** | None | Messages at 2 am are hostile to patients and generate complaints. | Add a central `messaging` rule: patient template sends only between 8 am and 9 pm IST; otherwise queue. OTP, emergency replies and replies inside an open conversation are exempt. |
| **Language** | `patients.language` exists (`schema.sql:17`) and is never used | Many patients prefer Hindi or the regional language. | Choose the template language from `patients.language`. Part 3 gives English and Hindi. |
| **MLC / sensitive cases** | None | Medico-legal cases, psychiatry, HIV, MTP and de-addiction need extra confidentiality. | Add `patients.sensitive` (or a per-encounter flag). When it is set, send no automated messages except the OTP and generic reminders that name no doctor. |

---

## Part 2: DPDP checklist, mapped to the code

Law: Digital Personal Data Protection Act 2023 ("Act") and DPDP Rules 2025, notified 13 Nov 2025. Most Data Fiduciary duties (notice, consent, security, breach, retention, rights) apply **about 18 months after notification, i.e. around May 2027** [VERIFY exact date in the notification]. The Data Protection Board provisions are already in force. Build to the standard now: hospitals will ask for it in the pilot contract.

Status key: **Done** = the code does it. **Partial** = some of it exists. **Missing** = nothing exists yet.

| # | Requirement | Source | Status today | What the code does / gap | Fix (owner) |
|---|---|---|---|---|---|
| 1 | **Notice before or with the consent request**, standalone, in clear language, listing the data, purposes and how to withdraw, exercise rights and complain to the Board; available in English or any Eighth Schedule language | Act s.5, s.6(3); Rules (notice rule) [VERIFY rule no.] | **Missing** | Staff tick "Patient agrees to WhatsApp reminders and reports" (`app/templates/appointments.html:55`). The patient sees no notice. | Show or hand the notice below (2.1) at registration. Send it as the first WhatsApp message to a new number. Link it in the patient app (Front-end, Product). |
| 2 | **Consent: free, specific, informed, unambiguous, by clear affirmative action, for a specified purpose** | Act s.6(1) | **Partial** | One flag, `consent_messages`, covers all purposes (`schema.sql:18`). The UI records it from a staff tick. CSV import accepts "yes" with no proof (`app/integrations/csv_import.py:22-46`). The API accepts `consent: true` from the billing software (`app/routes/api.py:46,117`). | Split consent by purpose: (a) appointment and visit messages, (b) bills and payments, (c) feedback, (d) health-programme and promotional messages. Treat (a) and (b) as the service the patient asked for. (d) needs its own opt-in. For CSV and API imports, require `consent_source` and `consent_at` from the source system, otherwise import as no consent (Backend). |
| 3 | **Proof of consent**: the fiduciary must be able to show that notice was given and consent obtained | Act s.6(10) | **Partial** | `consent_at` is **overwritten with NULL on withdrawal** (`app/patients.py:27-28`), so the history disappears from the record. `audit_log` keeps consent_given/withdrawn events (`patients.py:30`) but not the notice version, channel, the staff member who captured it, or the language. | Add a `consent_events` table (patient_id, purpose, action, notice_version, channel [desk/WhatsApp/app/import], language, captured_by, evidence ref, at). Never overwrite (Backend). |
| 4 | **Withdrawal as easy as giving consent**; processing stops within a reasonable time | Act s.6(4)-(6) | **Partial** | WhatsApp exact "STOP" (`webhooks.py:46`), the staff button (`ui.py:407-414`) and the patient app toggle (`patient_app.py:513-517`) all work and are audited. Gaps: no confirmation message, no Hindi or other keywords, no START, and withdrawal is all-or-nothing. | Fixes as in 1.8, plus per-purpose withdrawal. On withdrawal, cancel queued sends (Backend). |
| 5 | **Purpose limitation and legitimate uses**: reply to a patient-initiated message | Act s.7(a) (data voluntarily provided for a specified purpose) [VERIFY wording] | **Done, with risk** | `_reply` sends without consent (`webhooks.py:19-21`). That is defensible for direct replies. **Risk:** the feedback review link (`webhooks.py:87`) is promotional and rides on that exemption. | Keep replies; move review requests under the promotional purpose (Product). |
| 6 | **Data minimisation in messages** | Act s.6(1) ("limited to such personal data as is necessary"), s.8(5) security | **Missing** | Itemised bills (`automations.py:119-128`), specialty (`automations.py:60-61`) and follow-up reason (`automations.py:170`) all go over WhatsApp. | Part 3 templates (Backend). |
| 7 | **Children's data: verifiable parental consent**; no tracking, behavioural monitoring or targeted ads | Act s.9; Rules children's-data rule and Fourth Schedule exemption for clinical establishments (health services only) [VERIFY] | **Missing** | Age is not used. | Section 1.9 (Backend, Product). |
| 8 | **Persons with disability / lawful guardian** | Act s.9; Rules [VERIFY] | **Missing** | None. | Same guardian fields as for minors. |
| 9 | **Accuracy and completeness** when data is used for decisions or shared | Act s.8(3) | **Partial** | Phone-only matching can attach data to the wrong person (`patients.py:9-22`). | Section 1.9 matching fix (Backend). |
| 10 | **Reasonable security safeguards** (encryption, access control, logs, backups) | Act s.8(5); Rules security rule [VERIFY: includes keeping logs for at least 1 year] | **Partial** | Role logins, CSRF and audit exist (`app/auth.py`, `app/audit.py`). The SQLite file is not encrypted at rest. Payment links can be guessed (`automations.py:121`). | Security owns this: encrypted disk or SQLCipher, signed payment tokens, backups, log retention of at least 1 year. |
| 11 | **Breach notification** to each affected Data Principal and to the Board without delay, with a detailed report within 72 h | Act s.8(6); Rules breach rule | **Missing** (process) | No runbook. | Section 2.4 (Security, DevOps, Domain Lead). |
| 12 | **Retention and erasure** once the purpose is served or consent is withdrawn, unless the law requires keeping the data | Act s.8(7) | **Missing** | Everything is kept for ever: `messages.body` (`schema.sql:143`), leads and `audit_log`. | Section 2.3 (Backend). |
| 13 | **Right to information** (summary of data, processing, and who it was shared with) | Act s.11 | **Missing** | The patient app shows appointments, bills and reports, but there is no "my data" summary and no sharing list. | "Download my data" in `/my/profile` plus a staff request queue (Front-end, Backend). |
| 14 | **Right to correction, completion, updating and erasure** | Act s.12 | **Missing** | No edit or erase flow. Staff can edit some fields. | Request queue with a deadline; erasure respects clinical retention (2.3). |
| 15 | **Grievance redressal**, answered within the prescribed time | Act s.13; Rules (I believe 90 days) [VERIFY] | **Partial** | Complaint tasks exist for feedback only. | Add a "Privacy request / grievance" task kind (`tasks.kind` CHECK at `schema.sql:153` must be extended). Publish the hospital grievance officer's contact in the notice. |
| 16 | **Right to nominate** a person to act on death or incapacity | Act s.14 | **Missing** | No nominee or deceased status. | `patients.nominee_*` plus `status=Deceased` (1.9). |
| 17 | **Data Processor contract**: a fiduciary may use a processor only under a valid contract | Act s.8(2) | **Missing** | No DPA template. | Section 2.5 (Sales, lawyer). |
| 18 | **Cross-border transfer** is allowed unless the government restricts a country | Act s.16 | **Risk** | `PRODUCT_KNOWLEDGE.md` promises "India hosting", but with AI on, patient messages go to the Anthropic API (`app/ai/client.py`), and WhatsApp is processed by Meta outside India. | Name both in the notice and the DPA. Keep AI off by default (it is). Do not claim "data stays in India" (Sales, Product). |
| 19 | **Contact for queries**: the DPO for an SDF, otherwise a person who answers questions | Act s.8(9) | **Missing** | | A hospital-named contact in the notice and in every reminder footer ("Privacy: {{link}}"). |
| 20 | **Health-record law outside DPDP** (Clinical Establishments rules, IMC record retention, state rules, NABH, ABDM consent for ABHA linking) | Various [VERIFY with lawyer] | **Partial** | `abha_id` is stored (`schema.sql`) with no ABDM consent artefact. | Do not link or use ABHA until ABDM consent flows are built; treat `abha_id` as display only. |

### 2.1 Consent notice: patient-facing wording

To be shown at registration (printed or on a tablet) and sent on WhatsApp. Version: `CN-1.0`. Placeholders are in `{{ }}`. Hospital legal to approve.

**English**

> **{{Hospital name}}: How we use your contact details**
>
> We collect your name, mobile number, age, gender, and details of your appointments, bills, tests and follow-ups.
>
> **Why:** to send you appointment reminders, bills and payment links, test-report alerts, follow-up reminders, and to ask about your visit. We use WhatsApp (Meta) to send these messages.
>
> **Your choices:**
> ☐ Appointment, report and follow-up messages
> ☐ Bill and payment messages
> ☐ Feedback requests after a visit
> ☐ Health camps, packages and offers (optional)
>
> You can say no to any of these. You will still get treatment. You can stop messages at any time: reply **STOP** on WhatsApp, tell the front desk, or switch it off in the {{Hospital}} app.
>
> You can ask to see, correct or delete your data, or name a person to act for you. Contact: {{Grievance officer name}}, {{phone}}, {{email}}. If you are not satisfied, you can complain to the Data Protection Board of India.
>
> Full privacy notice: {{link}}
>
> For a child under 18, the parent or guardian gives this consent.
>
> Signature / tick: ________ Date: ______ Captured by: ______

**Hindi**

> **{{अस्पताल का नाम}}: हम आपकी जानकारी का उपयोग कैसे करते हैं**
>
> हम आपका नाम, मोबाइल नंबर, उम्र, लिंग और आपके अपॉइंटमेंट, बिल, जाँच और फ़ॉलो-अप की जानकारी रखते हैं।
>
> **किसलिए:** आपको अपॉइंटमेंट की याद दिलाने, बिल और भुगतान लिंक भेजने, रिपोर्ट तैयार होने की सूचना देने, फ़ॉलो-अप की याद दिलाने और आपके अनुभव के बारे में पूछने के लिए। ये संदेश हम WhatsApp (Meta) से भेजते हैं।
>
> **आपकी पसंद:**
> ☐ अपॉइंटमेंट, रिपोर्ट और फ़ॉलो-अप संदेश
> ☐ बिल और भुगतान संदेश
> ☐ विज़िट के बाद फ़ीडबैक
> ☐ हेल्थ कैंप, पैकेज और ऑफ़र (वैकल्पिक)
>
> आप इनमें से किसी के लिए भी मना कर सकते हैं। इससे आपके इलाज पर कोई असर नहीं पड़ेगा। संदेश कभी भी बंद करने के लिए WhatsApp पर **STOP** या **बंद** लिखें, रिसेप्शन पर बताएं, या {{अस्पताल}} ऐप में बंद करें।
>
> आप अपनी जानकारी देखने, सुधारने या हटाने के लिए, या अपनी ओर से किसी व्यक्ति को नामित करने के लिए संपर्क कर सकते हैं: {{शिकायत अधिकारी का नाम}}, {{फ़ोन}}, {{ईमेल}}। संतुष्ट न होने पर आप भारतीय डेटा संरक्षण बोर्ड (Data Protection Board of India) में शिकायत कर सकते हैं।
>
> पूरी गोपनीयता सूचना: {{link}}
>
> 18 वर्ष से कम उम्र के बच्चे के लिए माता-पिता या अभिभावक सहमति देंगे।
>
> हस्ताक्षर / टिक: ________ तारीख: ______ दर्ज करने वाले: ______

**Short WhatsApp version** (first message to a new number, and as a footer link):
- EN: "{{Hospital}} uses your number to reply to you and to send appointment and bill updates. Privacy notice: {{link}}. Reply STOP to stop messages."
- HI: "{{अस्पताल}} आपके नंबर का उपयोग आपको जवाब देने और अपॉइंटमेंट व बिल की जानकारी भेजने के लिए करता है। गोपनीयता सूचना: {{link}}। संदेश बंद करने के लिए STOP लिखें।"

### 2.2 Purpose map

| Purpose | Basis | Default | Messages in code |
|---|---|---|---|
| Replying to the patient | Legitimate use, s.7(a) [VERIFY] | Allowed | `ack_reply`, `welcome_reply`, `appt_confirmed`, `appt_cancelled`, `appt_reschedule_ack`, `feedback_ack_low`, `ai_reply` |
| Login code | Needed to provide the service the patient asked for | Allowed | `patient_otp` (`patient_app.py:208`) |
| Appointments and follow-ups | Consent (a) | Opt-in at registration | `appt_reminder_24h/2h`, `appt_confirmation`, `followup_reminder` |
| Bills and payments | Consent (b) | Opt-in | `dues_reminder` |
| Feedback | Consent (c) | Opt-in | `feedback_request` |
| Review requests, camps, packages | Consent (d), separate, never pre-ticked | Off | `feedback_review_link` (move here) |
| Owner report | Not patient data | n/a | `owner_daily_report` |

### 2.3 Retention proposal (for the hospital to approve)

Tec Tha is **not** the medical-record system. The HIS and the billing software hold the legal record. Tec Tha keeps communication and workflow data only. Proposed periods, to be confirmed with the hospital MRD and a lawyer:

| Data | Proposed retention | Reason |
|---|---|---|
| Message bodies (`messages.body`) | 12 months, then replace the body with "[redacted]" and keep the metadata | Enough for complaints and disputes; limits exposure |
| Message metadata (to, template, status, time) | 3 years | Proof of consent and contact; dispute evidence. IMC (Professional Conduct) Regulations 2002 require in-patient records for 3 years [VERIFY whether NMC 2023 rules changed this] |
| Consent events | Life of the patient relationship + 3 years after the last interaction | Proof under s.6(10) |
| Leads that never became patients | 6 months after the last contact | The purpose ends |
| Bills, claims and payments mirror | As per the hospital's billing system (usually 8 years for accounts under the Companies Act / Income Tax [VERIFY]). Ideally Tec Tha keeps only a mirror and deletes it when the source deletes. | Statutory |
| Audit log | At least 1 year (DPDP Rules log requirement [VERIFY]); proposed 3 years | Security and NABH traceability |
| Feedback | 3 years | NABH trend analysis |
| OTPs (`patient_otps`) | 24 hours | No further use |
| Deceased patients | Stop all processing except legal hold; nominee requests handled manually | s.14 |
| MLC cases | Never auto-delete; hospital legal decides (often 10+ years by state practice [VERIFY]) | Legal hold |

Implement this as a nightly retention job with an audit entry per run. Erasure requests delete Tec Tha's copy and record that the HIS copy is kept under the law.

### 2.4 Breach notification process (draft runbook)

1. **Detect and contain (hour 0):** whoever spots it tells the Tec Tha on-call person and the hospital's named privacy contact. Rotate keys (WhatsApp token, API key, session secret), block the affected access, and preserve the logs.
2. **CERT-In (within 6 hours of noticing):** CERT-In Directions of 28 Apr 2022 require reportable cyber incidents to be reported within 6 hours [VERIFY whether this applies to the hospital, Tec Tha, or both; normally the entity whose systems are affected].
3. **Data Protection Board, intimation without delay:** the hospital (as fiduciary) files a short description of the breach, its nature, extent, timing, location and likely impact. Tec Tha (processor) must tell the hospital immediately; the DPA should say **within 24 hours of becoming aware**, or sooner.
4. **Affected patients, without delay:** in plain language, on WhatsApp, SMS or by call. Say what happened, the likely consequences, what is being done, what they can do, and a contact person. EN/HI template:
   - EN: "Important notice from {{Hospital}}: On {{date}} some of your details ({{data types}}) may have been accessed without permission. We have {{action taken}}. Please {{what to do}}. For questions call {{name}}, {{phone}}."
   - HI: "{{अस्पताल}} की ओर से ज़रूरी सूचना: {{तारीख}} को आपकी कुछ जानकारी ({{जानकारी का प्रकार}}) बिना अनुमति देखी गई हो सकती है। हमने {{क्या कदम उठाए}}। कृपया {{आपको क्या करना है}}। सवालों के लिए {{नाम}}, {{फ़ोन}} पर कॉल करें।"
5. **Detailed report to the Board within 72 hours:** facts, cause, mitigation, people responsible, and the patient notifications made (the Board can extend on request) [VERIFY].
6. **Post-incident review within 14 days:** root cause, fixes, an update to this document, and a report to the owner.

Penalties under the Act's Schedule are high: up to ₹250 crore for failing to take reasonable security safeguards, up to ₹200 crore for failing to notify a breach or for children's-data failures [VERIFY]. This is the main reason hospital clients will ask about it.

### 2.5 Data Processing Agreement: points to cover (hospital ↔ Tec Tha)

Lawyer to draft. Must include:
1. Roles: the hospital is the Data Fiduciary and Tec Tha the Data Processor. Tec Tha processes only on documented instructions and for the listed purposes (2.2).
2. **Accounts in the hospital's name** (PRODUCT_KNOWLEDGE rule 7.3): WhatsApp WABA, server and database. Tec Tha has admin access only, which the hospital can revoke.
3. A list of sub-processors (Meta, hosting, payment gateway, telephony, Anthropic if AI is on). The hospital must be told in advance of any change and has a right to object.
4. Where data is stored and any transfer outside India (s.16).
5. Security measures (annex): access control, encryption, backups, logs kept at least 1 year, staff confidentiality undertakings.
6. Breach: tell the hospital within 24 hours of becoming aware, cooperate with Board and CERT-In reporting, and provide forensic logs.
7. Help with patient rights requests within a set number of days (for example 7), so the hospital can meet its own deadline.
8. Retention and deletion as in 2.3. On termination, export in an open format (CSV/SQLite) and delete within 30 days, with a deletion certificate.
9. Audit rights for the hospital (once a year, or after a breach).
10. Rules for children's data and sensitive cases (MLC, psychiatry, HIV).
11. AI use: off by default; when on, no medical advice; prompts and outputs logged; no training on hospital data by the AI provider (check the provider's terms).
12. Liability and indemnity caps that match a near-zero-budget startup. A lawyer must balance these, because the Act's penalties fall on the fiduciary.

---

## Part 3: Patient-facing templates, rewritten

Rules applied:
- **Meta utility category:** each message is tied to a specific transaction the patient started (appointment, bill, follow-up). No promotional language, no offers, no review requests. Variables use `{{1}}` style. A message does not start or end with a variable, and two variables never sit next to each other.
- **Lock-screen safe:** no specialty, test names, diagnosis or bill items.
- **Quiet hours:** 8 am to 9 pm IST.
- Each template has quick-reply buttons where shown. Footer on every template: "Reply STOP to stop messages" / "संदेश बंद करने के लिए STOP लिखें".
- [VERIFY] Meta decides the category at review. A feedback survey may be reclassified as marketing; if so, send it only to patients with consent (c) and accept the marketing price.

### T1 `appt_reminder_24h`, utility

**EN**
```
Appointment reminder from {{1}}.
Patient: {{2}}
Doctor: Dr {{3}}
When: {{4}}
Where: {{5}} branch
Booking ID: {{6}}
Please bring any old reports and your ID.
```
Buttons: `Confirm` · `Reschedule` · `Cancel`

**HI**
```
{{1}} की ओर से अपॉइंटमेंट रिमाइंडर।
मरीज़: {{2}}
डॉक्टर: डॉ. {{3}}
समय: {{4}}
स्थान: {{5}} शाखा
बुकिंग आईडी: {{6}}
कृपया पुरानी रिपोर्ट और पहचान पत्र साथ लाएं।
```
Buttons: `पक्का करें` · `समय बदलें` · `रद्द करें`

### T2 `appt_reminder_2h`, utility

**EN**
```
Your appointment at {{1}} is today at {{2}} with Dr {{3}}, {{4}} branch.
Booking ID: {{5}}. Please arrive 15 minutes early for registration.
```
Buttons (only if not yet confirmed): `Confirm` · `Reschedule` · `Cancel`

**HI**
```
आज {{2}} बजे {{1}}, {{4}} शाखा में डॉ. {{3}} के साथ आपका अपॉइंटमेंट है।
बुकिंग आईडी: {{5}}। पंजीकरण के लिए कृपया 15 मिनट पहले पहुँचें।
```

### T3 `appt_cancel_confirm` (session reply, sent after the patient taps Cancel)
- EN: "Do you want to cancel your appointment with Dr {{doctor}} on {{time}}? Reply YES to cancel, or NO to keep it."
- HI: "क्या आप {{time}} को डॉ. {{doctor}} के साथ अपना अपॉइंटमेंट रद्द करना चाहते हैं? रद्द करने के लिए YES या हाँ लिखें, रखने के लिए NO या नहीं लिखें।"

### T4 `followup_reminder`, utility

**EN**
```
Follow-up reminder from {{1}}.
{{2}}, your follow-up visit with Dr {{3}} is due on {{4}}.
Tap below to book a time, or call us on {{5}}.
```
Buttons: `Book a time` · `Call me`

**HI**
```
{{1}} की ओर से फ़ॉलो-अप रिमाइंडर।
{{2}}, डॉ. {{3}} के साथ आपकी फ़ॉलो-अप विज़िट {{4}} को है।
समय बुक करने के लिए नीचे टैप करें, या हमें {{5}} पर कॉल करें।
```
Buttons: `समय बुक करें` · `मुझे कॉल करें`

### T5 `bill_payment_reminder`, utility (replaces the itemised `dues_reminder`)

Send only for the patient-payable amount, never for PM-JAY or scheme bills, and never while a linked claim is open.

**Stage 1 (day 3)**
EN
```
Bill update from {{1}}, {{2}} branch.
Bill no: {{3}}
Amount due: {{4}}
You can see the full bill and pay by UPI or card here: {{5}}
If you have already paid, please ignore this message. For questions about the bill, call {{6}}.
```
HI
```
{{1}}, {{2}} शाखा की ओर से बिल की जानकारी।
बिल नंबर: {{3}}
बकाया राशि: {{4}}
पूरा बिल देखने और UPI या कार्ड से भुगतान करने के लिए: {{5}}
अगर आप भुगतान कर चुके हैं, तो कृपया इस संदेश को अनदेखा करें। बिल से जुड़े सवालों के लिए {{6}} पर कॉल करें।
```

**Stage 2 (day 10)**: same structure, first line changed to:
- EN: "A gentle reminder from {{1}}: bill {{2}} has {{3}} still due."
- HI: "{{1}} की ओर से विनम्र अनुस्मारक: बिल {{2}} पर {{3}} अभी बकाया है।"

**Stage 3 (day 21)**: no new message wording. Staff call the patient (task already created at `automations.py:153`). If an automated message is still sent:
- EN: "{{1}}: bill {{2}} has {{3}} due. Our billing team will call you to help. If there is a problem with the bill, please tell us."
- HI: "{{1}}: बिल {{2}} पर {{3}} बकाया है। हमारी बिलिंग टीम मदद के लिए आपको कॉल करेगी। अगर बिल में कोई समस्या है, तो कृपया हमें बताएं।"

Buttons for every stage: `Pay now` (URL with a signed token) · `Question about bill`

### T6 `feedback_request`, utility [VERIFY category]

**EN**
```
Thank you for visiting {{1}}, {{2}} branch.
How was your visit on {{3}}? Please tap a rating.
```
Buttons (list or quick reply): `5 Excellent` · `4 Good` · `3 Okay` · `2 Poor` · `1 Very poor`
(Meta allows only 3 quick-reply buttons per template [VERIFY]. Use a list message in session, or the buttons `Good` · `Okay` · `Not good`.)

**HI**
```
{{1}}, {{2}} शाखा में आने के लिए धन्यवाद।
{{3}} को आपकी विज़िट कैसी रही? कृपया रेटिंग चुनें।
```
Buttons: `अच्छी` · `ठीक-ठाक` · `अच्छी नहीं`

**Session replies**
- Low score, EN: "We are sorry your visit was not good. Our patient relations team will call you within 24 hours (9 am to 7 pm). If you like, reply here with what went wrong."
- Low score, HI: "हमें खेद है कि आपकी विज़िट अच्छी नहीं रही। हमारी पेशेंट रिलेशन टीम 24 घंटे के अंदर (सुबह 9 से शाम 7 बजे के बीच) आपको कॉल करेगी। चाहें तो यहाँ बताएं कि क्या गलत हुआ।"
- Good score, EN: "Thank you for your feedback. It helps us improve." (No review link in this flow; see 1.2.)
- Good score, HI: "आपके फ़ीडबैक के लिए धन्यवाद। इससे हमें बेहतर बनने में मदद मिलती है।"

### T7 Session replies (inside the 24-hour window, no template needed)

| Key | English | Hindi |
|---|---|---|
| `welcome_reply` | Hello, thank you for contacting {{hospital}}. We have branches at {{branches}}. Please tell us the patient's name, which branch suits you, and the doctor or department you need. **If this is an emergency, call 108 or come to our Emergency now: {{er_phone}}.** Privacy notice: {{link}} | नमस्ते, {{hospital}} से संपर्क करने के लिए धन्यवाद। हमारी शाखाएं: {{branches}}। कृपया मरीज़ का नाम, आपके लिए सुविधाजनक शाखा और जिस डॉक्टर या विभाग की ज़रूरत है, बताएं। **आपातकाल में तुरंत 108 पर कॉल करें या हमारी इमरजेंसी में आएं: {{er_phone}}।** गोपनीयता सूचना: {{link}} |
| `ack_reply` | Thank you, {{name}}. Our team has your message and will reply by {{time}}. For an emergency, call 108 or {{er_phone}}. | धन्यवाद, {{name}}। हमारी टीम को आपका संदेश मिल गया है और {{time}} तक जवाब देगी। आपातकाल में 108 या {{er_phone}} पर कॉल करें। |
| `emergency_reply` (new, keyword-triggered) | If this is an emergency, please call 108 now or come straight to {{hospital}} Emergency at {{address}}. Emergency phone: {{er_phone}}. Our team has been told. | अगर यह आपातकाल है, तो कृपया तुरंत 108 पर कॉल करें या सीधे {{hospital}} की इमरजेंसी, {{address}} पर आएं। इमरजेंसी फ़ोन: {{er_phone}}। हमारी टीम को सूचना दे दी गई है। |
| `appt_confirmed` | Thank you. Your appointment is confirmed: Dr {{doctor}}, {{time}}, {{branch}} branch. Booking ID {{id}}. | धन्यवाद। आपका अपॉइंटमेंट पक्का है: डॉ. {{doctor}}, {{time}}, {{branch}} शाखा। बुकिंग आईडी {{id}}। |
| `appt_reschedule_ack` | No problem. Our team will call you between {{window}} to choose a new time. | कोई बात नहीं। नया समय तय करने के लिए हमारी टीम {{window}} के बीच आपको कॉल करेगी। |
| `appt_cancelled` | Your appointment with Dr {{doctor}} on {{time}} is cancelled. Message us any time to book again. | डॉ. {{doctor}} के साथ {{time}} का आपका अपॉइंटमेंट रद्द कर दिया गया है। दोबारा बुक करने के लिए कभी भी संदेश भेजें। |
| `optout_confirm` (new) | You will no longer get reminder or bill messages from {{hospital}}. You can still message us at any time. Reply START to turn messages back on. | अब आपको {{hospital}} से रिमाइंडर या बिल के संदेश नहीं मिलेंगे। आप कभी भी हमें संदेश भेज सकते हैं। संदेश फिर से चालू करने के लिए START लिखें। |
| `patient_otp` (authentication template) | {{1}} is your {{2}} login code. It expires in 5 minutes. Do not share it with anyone, including hospital staff. | {{1}} आपका {{2}} लॉगिन कोड है। यह 5 मिनट में समाप्त हो जाएगा। इसे किसी के साथ, अस्पताल के स्टाफ़ के साथ भी, साझा न करें। |

Note on `patient_otp`: Meta's authentication templates have fixed wording [VERIFY]. Use Meta's preset text with a copy-code button.

---

## Part 4: Top 10 fixes, ranked by risk

| Rank | Risk | Where | Fix | Owner |
|---|---|---|---|---|
| 1 | **Clinical safety:** with AI off (the default), emergency messages get "team will reply shortly" and a task due in 30 min | `app/routes/webhooks.py:108-111`; triage exists only in `app/ai/prompts.py:22` and `app/ai/receptionist.py:222-225` | Deterministic EN/HI/Hinglish emergency keyword check at the top of `handle_inbound` (after STOP), before any other branch. Send `emergency_reply` at once and create an URGENT task due now. Show the ER number in `welcome_reply` and `ack_reply`. | Backend + Domain Lead (keyword list) |
| 2 | **Wrong patient / confidentiality:** one patient per phone; a match ignores the name, so family members merge and see each other's data | `app/schema.sql:13`, `app/patients.py:9-22`, patient app OTP login `app/routes/patient_app.py:184-210` | Drop UNIQUE on phone. Match on phone + name + DOB. Send near-matches to staff. Add contact relationship and family profiles in the patient app. | Architect + Backend |
| 3 | **Dues sent to the wrong payer:** PM-JAY, TPA-pending and corporate bills are chased from the patient | `app/automations.py:113-118, 141-156`; no payer field in `bills` (`app/schema.sql`) or link to `claims` | Add `payer_type`, `patient_payable` and `claim_id` to bills. Remind only for the patient-payable part, never for PM-JAY or scheme bills, and never while a claim is open. | Backend + Domain Lead |
| 4 | **Health data on the lock screen:** itemised bills, specialty and follow-up reason in WhatsApp text | `app/automations.py:119-128`, `:60-61`, `:170` | Use the Part 3 templates: amount and link only; no specialty; generic follow-up. | Backend |
| 5 | **Deceased patients are messaged** (reminders, dues, feedback) | No status column in `patients` (`app/schema.sql`); every query in `app/automations.py:46-179` | Add `patients.status`/`deceased_at`. Hard filter in `messaging.send` for automated sends. Dues go to a manual task only. | Backend |
| 6 | **Consent is not provable or purpose-specific:** one flag; `consent_at` is wiped on withdrawal; CSV/API consent accepted with no evidence; no notice shown | `app/patients.py:25-30`, `app/schema.sql:18-19`, `app/integrations/csv_import.py:22-46`, `app/routes/api.py:46,117`, `app/templates/appointments.html:55` | `consent_events` table (purpose, notice version, channel, captured_by). Per-purpose consent. Import defaults to no consent without evidence. Show the 2.1 notice. | Backend + Front-end + Domain Lead |
| 7 | **Children's data:** no guardian or verifiable parental consent; feedback and AI chats with minors | `app/schema.sql:14` (age unused), all automations | Store DOB and guardian fields. Send only to the guardian. No feedback, review or AI chat for under-18s. | Backend + Product |
| 8 | **Claims model wrong for PM-JAY and the real TPA flow:** IRDAI 1 h/3 h applied to every payer; no query or enhancement stages; no settlement ageing | `app/automations.py:195-205`, `app/billing.py:7`, `app/schema.sql:109-111`, `app/templates/claims.html:6`, `app/seed.py:26` | Payer type with configurable time limits per type. Add Query/Enhancement/Partial/Reimbursement stages, a settlement older than 30 days alert, and night escalation. | Backend + Domain Lead |
| 9 | **Opt-out and timing:** STOP is exact English only with no confirmation or START; no quiet hours; review link only for happy patients (review gating) | `app/routes/webhooks.py:46-49`, `:87-88`; `app/scheduler.py` (runs 24×7) | Multilingual opt-out keywords + `optout_confirm` + START. Quiet hours 8 am to 9 pm in `messaging`. Remove the score-gated review link. | Backend + Product |
| 10 | **Owner report can go to a stranger**, and **live sends are free text** (they will fail outside 24 h, or tempt staff to switch to a personal WhatsApp) | `app/config.py:39` default `919900000000`; `app/messaging.py:58-68` sends `type: text` | Require `TT_OWNER_PHONE` in live mode. Send by approved template name and parameters, with the Part 3 templates submitted for approval. | Backend + DevOps |

**Also important, just outside the top 10:** IPD/OPD encounter model and package-aware unbilled detection (`app/automations.py:184-192`, `app/billing.py:86-106`). Payment link built from a guessable bill number (`app/automations.py:121`). Retention job (2.3). Breach runbook (2.4). DPA (2.5). Do not claim "India hosting" while AI or Meta process data abroad (`docs/PRODUCT_KNOWLEDGE.md` section 2, row 12).

## What I need from other roles

- **Head of Product:** accept per-purpose consent and the payer-type model into the next release scope.
- **Architect:** design `admissions`, `consent_events`, payer type, patient status and family/contact relationships.
- **Backend:** fixes 1 to 10. Every fix needs tests, for example "deceased patient gets no message", "PM-JAY bill gets no dues reminder", "chest pain with AI off gets emergency_reply".
- **Security:** payment token, encryption at rest, log retention, breach runbook owner.
- **Sales:** keep "DPDP compliant" out of pitch material until items 1 to 7 above are done. Say "built for DPDP; consent and audit in place; full compliance work in progress".
- **Lawyer (external):** confirm every [VERIFY] item, draft the DPA, and approve the consent notice wording.
