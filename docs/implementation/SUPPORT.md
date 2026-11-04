# Support: hours, severity, escalation

Owner of this document: Implementation & Customer Success Manager, Tec Tha.
Give a printed copy to the hospital's pilot lead and keep one at each desk.

**Note:** Tec Tha is a small team. The hours and times below are what we can promise now. Change them only when the team grows, and update the pilot agreement to match.

## 1. Support hours (IST)

| Period | Hours | How |
|---|---|---|
| **Hypercare** (go-live to the end of week 4) | Monday to Saturday, 8 am to 8 pm; Implementation Manager on site for the first 3 days | Phone and WhatsApp to the Implementation Manager |
| **Normal support** (after hypercare) | Monday to Saturday, 9 am to 7 pm | WhatsApp support group or phone; email for non-urgent requests |
| **Outside hours** | Severity 1 only (see below) | Phone the on-call number. No answer in 15 minutes? Call the founder |

Sundays and public holidays: Severity 1 only.

Contacts (fill in at go-live):
- Support WhatsApp group: "[Hospital] – Tec Tha support" (pilot lead, branch managers, Tec Tha team)
- Implementation Manager: name ______ phone ______
- On-call (Severity 1): phone ______
- Founder (escalation): name ______ phone ______
- Email: ______

## 2. Severity levels and response times

"Response" means a Tec Tha person replies and starts work. "Fix or workaround" is the target, not a guarantee.

| Severity | What it means | Examples | Response | Fix or workaround target |
|---|---|---|---|---|
| **S1 – Critical** | Patient safety, patient data at risk, or wrong messages going to patients | Messages sent to the wrong patient; messages sent to someone who said STOP or gave no consent; one patient able to see another's data; staff login not working at both branches | **30 minutes**, any time | Stop the harm within **2 hours** (for example switch automations off); full fix and written report in 2 working days |
| **S2 – High** | A main screen or automation is down for a branch; staff fall back to paper | Cannot log in at one branch; reminders not going out; daily import failing; all WhatsApp sends Failed | **1 hour** in support hours | Workaround the same day; fix within 1 working day |
| **S3 – Medium** | Something is wrong but there is a way to keep working | A dashboard number does not match the billing software; one message template rejected; a red claim card that should not be red | **4 working hours** | Within 3 working days |
| **S4 – Low** | Question, training need or improvement idea | "How do I...?"; add a new staff login; change message wording; new report idea | **1 working day** | Planned with the pilot lead; new features go to the Head of Product |

Any possible data leak is S1 until proven otherwise, and the Security & Privacy Engineer is told at once (the hospital may have duties to report it under the DPDP Act; the DPA sets out who does what).

When in doubt, the hospital reports at the higher level. Tec Tha can lower it after checking.

## 3. Escalation path

| Step | Who | When |
|---|---|---|
| 1 | Staff member tells the **hospital pilot lead** (or the shift manager) | Straight away |
| 2 | Pilot lead reports to **Tec Tha support** (WhatsApp group or phone; phone for S1 and S2) | Straight away |
| 3 | **Implementation Manager** owns the ticket, keeps the hospital updated, brings in the Engineer | Within the response time |
| 4 | **Founder** | S1 at once; S2 not fixed in 1 working day; any ticket where the hospital is unhappy with progress |
| 5 | **Owner / director meeting** with the founder | S1 that happened twice, or any issue still open after 5 working days |

Updates to the hospital: S1 every 30 minutes until the harm is stopped; S2 every 2 hours; S3 and S4 when the status changes.

After every S1 and S2: a short written report within 2 working days (what happened, how many patients were affected, cause, fix, how we stop it happening again).

## 4. What the hospital must report, and how

**Report straight away (phone for S1 and S2, then write in the WhatsApp group):**
- Any WhatsApp sent to the wrong patient, with wrong details, or to a patient who said no or replied STOP.
- A patient complaint about a message.
- Anyone seeing data they should not see, or a lost or shared password.
- The system or a screen not working, or staff going back to paper.
- A big mismatch between Tec Tha Vital and the billing software (amounts, dues, payments).

**Report the same day:**
- A staff member joining, leaving or changing role or branch (their login must be created or closed the same day).
- A change in the billing software, its export, the CRM or the hospital's WhatsApp number.
- A new doctor, a doctor leaving or a timing change.

**Every report should say (copy and fill):**

```
Branch:
Your name and role:
Screen (e.g. Billing, Claims, Messages):
What happened:
When (date and time):
Patient ID (TT-xxxxxx) or bill number, if any — no medical details:
How many patients or staff affected:
Screenshot: yes / no
What you did meanwhile:
```

Hindi: *शाखा, आपका नाम, कौन सी स्क्रीन, क्या हुआ, कब हुआ, मरीज़ ID या बिल नंबर (कोई मेडिकल जानकारी नहीं), कितने लोग प्रभावित, स्क्रीनशॉट।*

**Do not** send patients' medical details, reports or full bills in the support group. The patient ID (TT-xxxxxx) or bill number is enough; Tec Tha looks up the rest in the system.

## 5. What Tec Tha does every day without being asked (hypercare and normal support)

- Checks the Messages screen for Failed sends and the Audit log for `automation_error`.
- Checks the nightly backup ran.
- Checks that the daily import ran and reads "Rows that need fixing".
- Tells the pilot lead about anything found, with its severity.
