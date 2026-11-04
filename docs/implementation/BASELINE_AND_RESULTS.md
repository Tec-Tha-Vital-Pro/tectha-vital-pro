# Baseline measurement and monthly results report

Owner of this document: Implementation & Customer Success Manager, Tec Tha.

**Rule:** every number in a client report comes from the hospital's own records or from Tec Tha Vital, with its source written next to it. Estimates are labelled as estimates. Sample data is never shown as a result (PRODUCT_KNOWLEDGE.md section 7).

## Part A: Measuring the baseline (week 1, before go-live)

- **Period:** the last 30 complete days before the discovery visit. Use the same period for both branches.
- **Who:** the hospital's pilot lead pulls the records; Tec Tha calculates and shows the working; the Owner signs the baseline sheet.
- **Both branches:** measure Branch 1 (pilot) and Branch 2 (comparison) the same way.
- **When records are missing:** if a number cannot be measured from records, write "not measured" and start counting by hand from the visit day for 7 days. Do not guess.

| # | Measure | Definition (same before and after go-live) | Where to get it before go-live | Where to get it after go-live |
|---|---|---|---|---|
| 1 | **No-show rate** | No-shows ÷ (visited + no-shows) for booked appointments in the period. Walk-ins without a booking are not counted. Cancelled appointments are not counted | Appointment register or CRM export: count booked appointments marked as not attended | Dashboard → **No-show rate, 30 days** (it uses Visited and NoShow marks, so the front desk must mark them correctly) |
| 2 | **Dues aged over 30 days** | Total unpaid balance (₹) and number of bills where the bill date is more than 30 days before the measurement date | Billing software outstanding or ageing report | Billing → **Pending dues**: add up rows with Age over 30 days (no on-screen total yet; done by hand or from the database by Tec Tha) |
| 3 | **Enquiry reply time** | Minutes from the enquiry arriving to the first reply. Report the median, and the % answered within 5 minutes | Sample 50 enquiries from WhatsApp chats and call logs (time received vs. time of first reply). Missed calls never called back count as "not replied" | Dashboard → **Enquiries answered in 5 min**, and the First reply column on **Enquiries** |
| 4 | **Enquiry to paid conversion** | Enquiries in the period whose patient made at least one payment after the enquiry ÷ all enquiries in the period | CRM export of leads matched by mobile number against the billing software's paid bills | Dashboard → **Enquiry to paid patient, this month** |
| 5 | **Claims past the time limit** | Cashless claims where the pre-auth decision took more than 1 hour, or the discharge approval took more than 3 hours (IRDAI 2024 limits). Report the count and the % of all claims | TPA desk register: time sent and time of the insurer's reply for each claim in the period. If times are not written down, count by hand for 7 days | **Claims** board red cards and **Tasks → Stuck claims** (the board is correct only if the desk presses **Move** at every stage change) |

Also record for context (not success measures): number of OPD visits, number of enquiries, number of cashless claims, and total billed in the period. A change in volume can explain a change in a rate.

### Baseline sheet (sign before go-live)

| Measure | Branch 1 (pilot) | Branch 2 (comparison) | Source and period | How measured (records / 7-day hand count) |
|---|---|---|---|---|
| No-show rate | __ % (__ of __) | __ % (__ of __) | | |
| Dues over 30 days | ₹ __ across __ bills | ₹ __ across __ bills | | |
| Enquiry reply time | median __ min; __ % within 5 min | median __ min; __ % within 5 min | | |
| Enquiry to paid | __ % (__ of __) | __ % (__ of __) | | |
| Claims past time limit | __ of __ (__ %) | __ of __ (__ %) | | |
| **Success measure agreed** | from __ to __ by day __ | n/a | | |

Signed (Owner): ____________ Date: ________ Signed (Tec Tha): ____________

## Part B: Monthly one-page results report (template)

Sent by the 5th working day of each month to the Owner and pilot lead, as one page (PDF or WhatsApp image) and talked through in a 20-minute call. Rupees in Indian format (₹1,25,000); dates in IST.

---

**[Hospital name]: Tec Tha Vital results, [Month YYYY]**
Branch(es) live: [Branch 1] since [date] · Comparison: [Branch 2] · Prepared by [name], Tec Tha, on [date]

**1. Headline (one sentence, real numbers only)**
Example shape: "In [month], [N] more patients came to their booked appointment and ₹[X] of old dues was collected at [Branch 1]."

**2. Money (₹)**

| | Baseline | This month | Change | Source |
|---|---|---|---|---|
| Dues over 30 days (₹, open at month end) | | | | Billing → Pending dues |
| Old dues collected after a WhatsApp reminder (₹) | n/a | | | Payments on bills that had a reminder sent |
| Unbilled services found and added to a bill (₹) | n/a | | | Billing → Possibly unbilled services (**Add to bill**) |
| Collected this month (₹), for context | | | | Dashboard |

**3. Patients**

| | Baseline | This month | Change | Source |
|---|---|---|---|---|
| No-show rate (%) and number of no-shows | | | | Dashboard |
| Patients who came after a reminder (no-shows avoided, estimate*) | n/a | | | (baseline rate − this month's rate) × booked appointments |
| Enquiries answered within 5 min (%) | | | | Dashboard |
| Enquiries that became paying patients (number and %) | | | | Dashboard funnel |
| Claims past the time limit (number and %) | | | | Claims board / Tasks |
| Complaints raised from feedback, and how many closed | n/a | | | Tasks → Complaints |

\*Label this line "estimate" in the report. It assumes the volume and mix of patients is similar to the baseline month.

**4. Pilot branch against comparison branch**
Same table rows for Branch 2. If both branches improved by the same amount, say so: the change may not be due to the system.

**5. Messages and consent**
WhatsApp sent: __ · Failed: __ (main reason: __) · Blocked for no consent: __ · Patients with consent: __ of __ registered this month (__ %) · Patients who replied STOP: __
WhatsApp cost passed through at actual Meta cost: ₹ __

**6. Problems this month and what we did**
Up to 3 lines from the support log: date, what happened, fixed or not.

**7. Next month**
Up to 3 actions, each with an owner (Tec Tha or hospital) and a date.

---

### Rules for filling the report

- Same definitions as the baseline. If a definition changes, show both the old and new number for one month.
- If a number moved the wrong way, show it. Do not drop a row because it looks bad.
- Never claim revenue we did not see in a payment record. "Dues collected" means payments recorded, not reminders sent.
- Small numbers: if fewer than 30 appointments or 20 enquiries are behind a % figure, show the counts with it and say it is too few to be sure.
