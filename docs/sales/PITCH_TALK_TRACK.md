# Pitch Talk Track (10 minutes) and Discovery Questions

Internal. For the founder. Use with [DEMO_SCRIPT.md](../DEMO_SCRIPT.md) (the 25-minute demo) and [PILOT_PROPOSAL.md](PILOT_PROPOSAL.md).

**Goal of the meeting:** the owner picks one problem and one branch for a paid pilot, and agrees how we will measure success.
**Rule:** say only what is built. If something is planned or in progress, say "planned" or "in progress". Never quote numbers we have not measured at their hospital.

## Before you walk in

- [ ] `python -m app.seed`, start the app, type their hospital and branch names in Settings.
- [ ] Tabs open: Dashboard, Messages, Billing, Claims. Backup clickable demo page open.
- [ ] Optional: live mode with Meta's free test number and the owner's phone verified.
- [ ] Two printed copies of PILOT_PROPOSAL.md with blanks, and a pen.
- [ ] Know your price range (PRICING_NOTES.md) and your walk-away floor before you arrive.

## The 10-minute track

### 0:00–1:00 Open (who we are, why we are here)

> "Thank you for your time, sir/madam. I'm [name] from Tec Tha. We don't sell a new hospital software. Your billing and CRM stay exactly as they are. We connect them to WhatsApp and give you one view of both branches. Before I show anything, can I ask you three quick questions? I want to show you only what matters to you."

### 1:00–3:00 Their problem, in their words

Ask, then stop talking. Write down the exact answers and numbers.

1. "How much is pending in patient dues right now, roughly, across both branches?"
2. "Out of every 10 appointments booked, how many patients don't turn up?"
3. "When you want yesterday's numbers for both branches, how do you get them?"

If they don't know a number, that is a finding: "That's fine. In the pilot, the first week is us measuring it with your team."

### 3:00–4:30 The owner's morning (Dashboard)

> "This is what you'd see every morning, both branches together, or one at a time. 'Needs attention' shows stuck insurance claims, services that look done but not billed, and missed calls. The same summary comes to your WhatsApp at 9 am. Nobody has to make an Excel sheet."

(Note: this is sample data. Say so: "These are sample numbers, not yours.")

### 4:30–6:30 The patient's experience (Messages)

Run automations, then simulate replies.

> "A patient gets a reminder 24 hours and 2 hours before the appointment. They reply 1 and it's confirmed, no phone call needed. After the visit they get a feedback request. If they give a low score, a task goes to your manager the same minute, before they post a bad review. A high score gets your Google review link. And a message from a new number becomes an enquiry in the front-desk inbox straight away."

### 6:30–8:00 Money (Billing and Claims)

> "Pending dues: a polite reminder with a payment link, repeated on a schedule. Unbilled services: things done in lab or ward but not on any bill, your billing team can add them with one click. Claims: red cards are past the insurer's 1-hour cashless or 3-hour discharge limits, so someone follows up today, not next week."

### 8:00–9:00 Trust

> "Four promises. One: no message goes to a patient without their consent, and they can reply STOP. Two: the WhatsApp account, the server and the data are in your hospital's name, not ours. If you stop working with us, you keep everything. Three: every staff member has their own login and sees only their branch and role; every message and change is logged. Four: the system never gives medical advice. Clinical decisions stay with your doctors."

### 9:00–10:00 The ask

> "I don't want you to commit to the whole thing. Let's do a small paid pilot: one branch, one problem, 30 to 45 days. We agree today what success looks like, for example '₹X of old dues collected' or 'no-shows from X% to Y%'. If we hit it, we talk about both branches. If we don't, you've lost very little and you get a written report. Which problem should we fix first: dues, no-shows, or enquiry follow-up?"

Then stop talking and wait.

## Closing moves

- **They pick a problem:** take out the proposal, fill section 3 together, agree a start date. Ask for the billing vendor contact.
- **"Send me a proposal":** "Of course. So it's useful, can we fill the success measure now? It takes two minutes." Send the filled proposal within 24 hours.
- **"Let me think":** "Sure. What would you need to see to say yes?" Book the next meeting before you leave.
- **"Too expensive":** see OBJECTIONS.md #1. Reduce scope, not price.

## Discovery questions

Ask the ones you did not cover in the meeting. Fill gaps in a follow-up call with their admin or billing head.

### Systems
1. Which CRM do you use? Who set it up, and who manages it?
2. Which billing software at each branch? Same at both?
3. Can the billing software export bills and payments to Excel/CSV? Does the vendor offer an API? Who is the vendor's contact person?
4. Which WhatsApp do you use today: personal phones, WhatsApp Business app, or an API provider (Gupshup, Interakt, AiSensy, WATI, other)? Which number do patients know?
5. Do you use a telephony system (Exotel, Knowlarity, other) for incoming calls?

### Patients and enquiries
6. Where do new patients come from? (Walk-in, referrals, Practo, Google, ads, camps, corporate tie-ups.)
7. Who replies to WhatsApp and calls today? How fast, on average? What happens after hours?
8. Roughly how many OPD appointments per day at each branch?
9. Do you track no-shows? What do you do when a patient misses an appointment?
10. Does your registration form ask for consent to message patients?

### Money
11. How much is pending in patient dues? How old is the oldest?
12. Who follows up on dues today, and how (calls, WhatsApp, letters)?
13. Have you found services done but not billed? How often?
14. What share of your revenue is insurance/TPA and PM-JAY? Where do claims get stuck?

### Owner and operations
15. How do you get each branch's numbers today? How often?
16. What work does your staff re-type from one system into another every day?
17. Is the same patient sometimes registered twice?
18. What is the one problem that, if fixed, would make the biggest difference this quarter?

### Decision
19. Who else needs to agree before a pilot starts (partner, administrator, IT, billing vendor)?
20. Is there a budget for this, and who approves it?
21. When would you want the pilot to start?
