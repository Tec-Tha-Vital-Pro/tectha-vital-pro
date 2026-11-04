# Objection Handling: Top 15 from Indian Hospital Owners

Internal. Each answer matches what is actually built today (see [PRODUCT_KNOWLEDGE.md](../PRODUCT_KNOWLEDGE.md) section 6). Where something is planned or in progress, the answer says so. Never claim a result we have not measured at this hospital.

Pattern for every objection: **acknowledge, ask one question, answer honestly, offer the small next step (the pilot).**

---

### 1. "It's too expensive" / "We don't have budget for this"

> "Understood. That's why we start with one branch and one problem, not the whole system. Can I ask: how much is pending in dues right now? If the pilot collects even part of that, it pays for itself, and you'll see it in your own numbers, not ours. If it doesn't, you stop with no further commitment."

Rules: reduce scope (one branch, one automation, shorter pilot) before reducing price. Never cut the price below the floor in PRICING_NOTES.md.

### 2. "Is our patient data safe? Where does it go?"

> "Your data stays on a server in India, in your hospital's name. Tec Tha is only an administrator; you can remove us at any time. Every staff member has their own login and sees only their branch and role. Every message and every change is logged with who did it and when. We sign an NDA and a data processing agreement before touching any patient data."

Honest note: the system stores data in a single database file on that server. Nightly backups to a second location are part of our setup checklist. We have not yet had an external security audit; say so if asked directly.

### 3. "Our billing software vendor already does this"

> "Good, then let's use it. Can you show me what it sends to patients today? Most billing software is strong at billing, pharmacy and lab. What it usually doesn't do is follow up with patients on WhatsApp, combine both branches in one morning report, or flag services done but not billed. We don't replace your billing software; we read from it. If your vendor already covers a problem, we'll pick a different one for the pilot."

Do not criticise the vendor. Ask for the vendor's contact so we can request an export or API.

### 4. "We already have a CRM"

> "We keep your CRM. The gap we usually see is that the CRM and the billing software don't talk to each other, so a lead in the CRM never shows whether the patient paid or came back. We connect the two. For the pilot, we start with a daily file export, so nothing changes in your CRM."

Honest note: the full CRM-to-billing sync is Phase 2. In the pilot we use CSV import and our REST API.

### 5. "My staff won't use another system"

> "That's the right worry. Most of it runs on its own: reminders, dues follow-ups and feedback go out without anyone pressing a button. Staff see one inbox for enquiries and a task list for missed calls and complaints. We train them on site, and we start with one automation at a time so nobody is overloaded. Who would be our coordinator?"

Honest note: staff still need to log in for the inbox and tasks. The data import is a daily upload until the billing API is connected; that is a small manual step we should name up front.

### 6. "WhatsApp will ban our number"

> "Fair question. We use the official WhatsApp Business Platform (Cloud API) from Meta, not unofficial tools that get numbers banned. Messages go only to patients who have consented, reminders use templates Meta approves in advance, and patients can reply STOP any time. Bans usually happen when businesses send bulk messages to people who didn't ask for them; we are built not to do that."

Honest note: no one can guarantee Meta's decisions. If patients block or report the number a lot, Meta can lower its quality rating. We send only useful, consented messages to keep that risk low. One more practical point: the number used for the API cannot also be used on the normal WhatsApp app at the same time.

### 7. "What if Tec Tha disappears? You're a small company"

> "You're right that we're new, which is exactly why everything is in your name: the WhatsApp account, the server and the data. If we disappear tomorrow, your data and your WhatsApp number are still yours. The software is standard Python with a standard database, so another developer can run it. And we offer a written exit: a full copy of your data and removal of our access."

Honest note: do not promise source-code escrow or an SLA we can't staff. Offer what we can keep.

### 8. "What if the AI makes a mistake or tells a patient something wrong?"

> "The system you'll see today doesn't use AI for patient messages. Reminders, dues and feedback are fixed messages you approve. We're building an optional AI receptionist, but it's off by default, it never gives medical advice, it can only book slots that are really free, and anything it isn't sure about goes to a staff member as a task. We'd only switch it on with your written approval, after testing."

Honest note: the AI receptionist and owner insights are **in progress**, not part of the pilot. Do not demo them as finished.

### 9. "Will it give medical advice to patients?"

> "No. It handles communication and admin only: appointments, reminders, bills, reports, feedback. Any clinical question goes to your staff and doctors."

### 10. "Is this compliant with the DPDP Act / NABH?"

> "We're built around consent: no message without the patient's agreement, STOP to opt out, role-based access and an audit log of every send and change. Those are the main things the DPDP Act asks of you. We'll sign a data processing agreement with you. For NABH, the audit log and complaint tracking help your documentation, but certification is your hospital's process, not something software gives you."

Honest note: do not say "certified" or "fully compliant". Recommend their lawyer reviews the data processing agreement. Most DPDP Rules duties apply from May 2027.

### 11. "We tried something like this before and it didn't work"

> "What happened? [Listen.] That's why we keep the pilot small and agree the success measure before we start. You'll see the starting number and the end number side by side. If it doesn't move, you'll know in 30 to 45 days, not after a year."

### 12. "Patients here don't use WhatsApp / prefer phone calls / speak Tamil, Hindi..."

> "Some patients will always prefer a call, and that's fine; the front desk still calls them. WhatsApp handles the routine reminders so staff can spend their time on the calls that matter. Which languages do your patients mostly use?"

Honest note: today's message templates are in English. Local-language templates can be written and submitted to Meta for approval; treat each language as setup work, not a ready feature. Missed calls already become tasks with a 15-minute deadline.

### 13. "How long will setup take? We're busy"

> "For the pilot, about a week before the first message goes out: set up WhatsApp and the server in your name, import your data, train staff, and get Meta's approval for message templates. Meta's approval is outside our control and usually takes a few days. Your team's time is mainly one coordinator for about half an hour a day in the first week."

### 14. "Can you integrate with our billing software directly?"

> "That depends on your vendor. If they provide an API or a scheduled export, yes. We already accept bills, payments, orders, claims and leads through our API, and a CSV import that works with any software that exports to Excel. We start with the daily file and move to the API once your vendor agrees. Can you introduce us to their contact person?"

Honest note: we have not yet integrated with any specific named billing product. Do not claim "we work with X" until we have.

### 15. "Give it to us free for the pilot, then we'll pay"

> "I understand. We keep the pilot small so the fee stays small, and a paid pilot means both of us take it seriously: your team gives the time and data, and we commit to a result. What we can do is adjust the pilot fee against the setup fee if you continue."

Rules: a free **audit** (discovery visit and findings report) is fine. A free **pilot** is not; see PRICING_NOTES.md.

---

## Things we never say

- "Guaranteed" increase in collections, reduction in no-shows, or any percentage we have not measured at their hospital.
- "Certified", "fully DPDP compliant", "NABH approved".
- "Works with [named billing/CRM product]" before we've integrated with it.
- "AI handles your patients" (AI is in progress and off by default).
- Anything that sounds like medical advice.
- "Live token updates" or "OPD queue messages" as finished: they are planned. Token numbers on bookings exist; live queue messages do not yet.
- "Inventory / stock-outs" as a feature: planned, phase 3.
