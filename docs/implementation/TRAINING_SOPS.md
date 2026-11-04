# Staff training SOPs (one page per role)

Owner of this document: Implementation & Customer Success Manager, Tec Tha.
Print each role's page and keep it at that desk. Screen and button names below are exactly what staff see in Tec Tha Care Connect.

**Rules for everyone (सभी के लिए नियम)**

1. Use only your own login. Never share your password. Log out when you leave the desk.
   *केवल अपना लॉगिन इस्तेमाल करें। पासवर्ड किसी को न बताएं।*
2. No WhatsApp message goes to a patient without consent. Ask every patient.
   *मरीज़ की सहमति के बिना कोई WhatsApp संदेश नहीं जाता। हर मरीज़ से पूछें।*
3. Never give medical advice on WhatsApp. Clinical questions go to the doctor.
   *WhatsApp पर कोई डॉक्टरी सलाह न दें। इलाज के सवाल डॉक्टर को भेजें।*
4. If the system is down, work the old way (paper register) and tell the pilot lead. The patient must never wait for the software.
   *सिस्टम बंद हो तो पुराने तरीके से काम करें और पायलट लीड को बताएं। मरीज़ को इंतज़ार न कराएं।*
5. Everything you do is recorded in the Audit log with your name.
   *आपका हर काम आपके नाम से रिकॉर्ड होता है।*

How to train: 30 to 45 minutes per role, on the practice (simulator) system, using real cases from that desk. Each person does the "Practice" tasks on their page before go-live.

---

## 1. Front desk (login role: `frontdesk`)

**Your screens:** Enquiries, Appointments, Patients, Messages, Tasks.

**Start of shift (5 min)**
1. Log in. Your home screen is **Enquiries**.
2. Open **Tasks**. Call back every item under **Missed calls** first. Each one has a 15-minute deadline.
   *पहले मिस्ड कॉल वापस करें — 15 मिनट के अंदर।*

**When a patient registers or books**
1. **Appointments → Book an appointment**: enter Patient name, Mobile number, Doctor, Date and time.
2. Ask: "Can we send your appointment reminders, reports and bills on WhatsApp? You can reply STOP any time."
   *"क्या हम आपको अपॉइंटमेंट, रिपोर्ट और बिल WhatsApp पर भेज सकते हैं? कभी भी STOP भेजकर बंद कर सकते हैं।"*
3. Tick **Patient agrees to WhatsApp reminders and reports** only if the patient says yes. Press **Book**.
4. Tell the patient their token number (shown in the green message after booking).
5. Returning patient? Type the same mobile number; the system finds the same patient ID (TT-xxxxxx). Do not create a second record.
   *पुराने मरीज़ का वही मोबाइल नंबर डालें — नई एंट्री न बनाएं।*

**Recording consent later:** **Patients** → search name, mobile or TT- ID → open the patient → **Record consent**. If the patient asks to stop: **Withdraw consent**.

**Enquiries**
1. New enquiries from WhatsApp appear on **Enquiries** on their own. Phone, walk-in or referral? Use **Add an enquiry**.
2. Reply fast. The owner sees the "Enquiries answered in 5 min" number every day.
   *हर पूछताछ का जवाब 5 मिनट के अंदर दें।*
3. Update the status every time: **New → Contacted → Booked → Converted**, or **Lost** (press **Save**).

**Appointments for the day**
- Mark each patient: **Confirmed**, **Visited**, **NoShow** or **Cancelled**. Mark **NoShow** only at the end of the doctor's session. The no-show rate is calculated from these marks, so be correct.
  *दिन के अंत में हर अपॉइंटमेंट का सही स्टेटस लगाएं।*

**Messages:** shows every WhatsApp sent and received. If a patient's message is a complaint or a medical question, tell the manager or doctor. Do not argue on WhatsApp.

**End of shift:** **Tasks** shows no missed call older than today. Every enquiry from today has a status.

**Practice:** book 2 appointments (one with consent, one without), add a phone enquiry and move it to Booked, record consent for an existing patient, close one missed-call task with **Mark done**.

---

## 2. Billing and insurance (TPA) desk (login role: `billing`)

**Your screens:** Billing, Claims, Tasks. The hospital's billing software stays the main record. This screen helps you follow up.
*बिलिंग सॉफ़्टवेयर ही मुख्य रिकॉर्ड है। यह स्क्रीन फॉलो-अप के लिए है।*

**Every morning (15 min)**
1. **Billing → Pending dues**: sorted with balance, Age (days) and number of reminders already sent.
   - Reminders go out on their own at 3, 10 and 21 days. Use **Send reminder now** only when the patient asks for the link again.
   - When a patient pays: enter the amount, choose the mode (**UPI**, **Card**, **Cash**, **Insurance**) and press **Save**. Enter the same payment in the billing software too.
     *भुगतान दोनों जगह दर्ज करें — बिलिंग सॉफ़्टवेयर में भी।*
2. **Billing → Possibly unbilled services**: services done in the lab or ward that are not on any bill. Check with the department, add the charge in the billing software, then press **Add to bill**.
   *जो सेवा बिल में नहीं है, उसे जांचें और बिल में जोड़ें।*
3. **Tasks → Unbilled services** and **Stuck claims**: work these and press **Mark done** when finished.

**Claims (all day)**
1. **Claims** is a board: Pre-auth requested → Pre-auth approved → Final bill sent → Settled (or Denied).
2. A **red card** has waited longer than the insurer's limit: 1 hour for pre-auth, 3 hours for discharge approval. Call the TPA right away.
   *लाल कार्ड = समय सीमा पार। तुरंत TPA को फोन करें।*
3. Every time a claim changes, choose the new stage and press **Move**. If the board is not updated, the timers are wrong.

**Never:** promise a patient a discount or waive dues on WhatsApp without the manager's approval.

**Practice:** record a UPI payment, send one reminder, add one unbilled service to a bill, move a claim from Pre-auth requested to Pre-auth approved.

---

## 3. Doctor (login role: `doctor`)

**Your screens:** Appointments, Patients. That is all you need.

1. **Appointments** shows today's list with token numbers. Pick another day with the date box and press **Show**.
   *आज के मरीज़ों की सूची टोकन नंबर के साथ।*
2. Open a patient (**Patients** → search) to see past visits at both branches, bills, messages and feedback.
3. Mark **Visited** when you see the patient, if your front desk does not do it for you.
4. The software sends only reminders and admin messages. It never gives medical advice. Medical decisions stay with you.
   *सॉफ़्टवेयर कोई डॉक्टरी सलाह नहीं देता। इलाज का फैसला सिर्फ़ डॉक्टर का।*
5. Want a follow-up reminder sent? Tell the front desk the follow-up date.

**Training time:** 10 minutes, at the doctor's convenience, not during OPD.

---

## 4. Owner or director

**What you use:** the 9 am WhatsApp report on your phone, and the **Dashboard**.

1. **9 am report** (daily on WhatsApp): yesterday's OPD visits, billed, collected, dues, no-show rate and problems that need attention, for both branches.
   *रोज़ सुबह 9 बजे WhatsApp पर कल का पूरा हिसाब।*
2. **Dashboard** (needs a login with Dashboard access; ask Tec Tha):
   - Top row: OPD visits yesterday, Billed yesterday, Collected yesterday, Outstanding dues, No-show rate (30 days), Enquiries answered in 5 min.
   - **Collections, last 7 days**, by branch.
   - **Enquiry to paid patient, this month**: how many enquiries became paying patients.
   - **Needs attention**: stuck claims, possibly unbilled services, missed calls, complaints.
   - Use the branch filter to see one branch or both.
3. Once a week, ask the pilot lead about anything in **Needs attention** that stays high.
4. Once a month you get a one-page results report from Tec Tha, in rupees and patients.
   *हर महीने एक पेज की रिपोर्ट — रुपये और मरीज़ों में।*

**Training time:** 15 minutes, one to one.

---

## 5. Tec Tha admin (login role: `admin`)

**Screens:** everything, including Import, Settings and Audit log. Keep admin logins to Tec Tha staff and the hospital's named IT person.

**Daily (during the pilot)**
1. **Import**: choose **Patients** or **Bills**, upload the day's CSV, press **Import**. Read **Rows that need fixing** and send that list to the hospital to fix at the source. Do not edit data by hand to hide problems.
2. **Messages**: check for Failed messages (Meta's error is shown) and Blocked ones (no consent). Blocked is correct behaviour, not a bug.
3. **Audit log**: search for `automation_error`. Any error is a support ticket (SUPPORT.md).
4. Settings → **Automations** shows **Live** or **Simulator**. Confirm it is the mode you expect.

**When staff join or leave**
- Settings → **Add a staff login**: Username, Full name, Password (8+ characters), Role (`frontdesk`, `billing`, `doctor`, `admin`), Branch. Choose the branch for desk staff, so they see only their branch.
- When someone leaves, disable their login the same day. Settings has no disable button yet, so the Tec Tha Engineer sets the user to Disabled in the database; Settings → Staff logins then shows **Disabled**. Never reuse a login for a new person.

**Never:** mark patients as consenting in bulk without proof; run **Run automations now** on the live system just to test (it sends real messages); change WhatsApp or server accounts out of the hospital's name.

**Before a demo or training only:** `python -m app.seed` resets the data. **Never run it on the hospital's live database.**
