# Pricing Notes (internal, do not share with the client)

Owner: Sales & BD Lead. Price and offer decisions: Sales Lead, after consulting the Head of Product and the founder (see TEAM.md).

> **Every ₹ figure in this file is an ASSUMPTION for the founder to adjust.** None of them is a market fact or a researched benchmark. Before quoting, check them against (a) what this hospital tells us in discovery and (b) any competitor quotes the hospital shares. Replace each assumption with a real number as soon as one exists, and note the source.

## 1. Structure (fixed, do not change per deal)

1. **Free audit:** discovery visit, plus the operations and patient-side audit, plus a findings report in ₹. This builds trust and costs only our time.
2. **Paid pilot:** one branch, one problem, 30–45 days, one-time fee, success measure agreed in writing.
3. **Setup fee per phase:** one-time, for each phase (Phase 1 messaging for both branches, Phase 2 CRM and billing sync, Phase 3 later modules).
4. **Monthly retainer:** starts after the pilot. Covers running, monitoring, support, the monthly results report and small changes.
5. **Pass-through at actual cost, no markup:** WhatsApp (Meta) charges, the server, and the optional AI API. Show the invoice or the dashboard figure every month.

Why this structure: the setup fee pays for our time up front (we have no funds to carry a client), the retainer keeps the relationship and the monthly report alive, and pass-through costs keep us honest because the hospital sees exactly what Meta charges.

## 2. Suggested ranges (ASSUMPTIONS, founder to adjust)

For a 2-branch mid-size hospital. GST extra.

| Item | Assumed range | Reasoning (also an assumption) |
|---|---|---|
| Pilot fee (one branch, one problem, 30–45 days) | ₹15,000 – ₹35,000 one-time | Small enough for an owner to approve alone; covers about 1–2 weeks of founder time for setup, training and weekly reviews. |
| Phase 1 setup (both branches, all messaging, dashboard) | ₹40,000 – ₹1,00,000 | Template approvals, second branch, staff training at both sites. |
| Phase 2 setup (CRM and billing sync) | ₹60,000 – ₹1,50,000 | Depends almost entirely on the vendor: CSV only (low end), a documented API (middle), or custom work with the vendor (high end, or scope separately). |
| Monthly retainer (2 branches) | ₹15,000 – ₹40,000 per month | Support, monitoring, backups check, monthly report, small changes. Low end is messaging only; high end includes the sync. |
| Extra branch (later) | ₹[__] setup + ₹[__] per month | Decide after the first client; do not quote before then. |

Pilot fee credit: if the hospital moves to Phase 1 within 30 days of the pilot ending, adjust the pilot fee against the Phase 1 setup fee. This is the main lever to close; use it before any discount.

Payment terms (suggested): pilot 50% on signing and 50% at the final report; setup fees 50% / 50% at go-live; retainer monthly in advance.

## 3. Cost to serve (what each client costs us or them every month)

All items run in the hospital's name where possible, so the hospital can pay the provider directly. Figures are assumptions to check against the provider's current price page before quoting.

| Item | Who pays | Assumed monthly cost | Notes |
|---|---|---|---|
| VPS (1–2 GB, Indian region) | Hospital, at actual cost | ₹500 – ₹1,500 | Check the current price with the provider. Pilot can start on a laptop for the demo only, never for real patient data. |
| Domain and HTTPS certificate | Hospital | Domain about ₹1,000/year (assumption); Let's Encrypt is free | Meta webhooks need HTTPS. |
| Backup storage (second location) | Hospital | Small; often free tier | Nightly copy of the database file, restore tested once. |
| WhatsApp Business Platform (Meta) charges | Hospital, at actual cost | Depends on volume and category | Meta charges for template messages by category (utility, marketing, authentication), and the rate card changes. Check Meta's current India rate card before quoting, and show the client how the charges add up for their volume. Replies within 24 hours of a patient's message are generally cheaper or free; check current rules. Marketing messages cost more than utility, so keep reminders, dues and reports as utility templates. |
| Optional AI API (Claude) | Hospital, at actual cost | Usage-based | Off by default (`TT_AI=on` plus an API key). Not part of the pilot. Estimate only after we measure message volume. |
| Telephony missed-call webhook (Exotel, Knowlarity) | Hospital's existing contract | Their existing cost | We only receive the webhook. |
| Payment links | Hospital's own gateway or UPI page | Gateway's own fees | We only build the link from `TT_PAYMENT_LINK_BASE`; we do not process payments. |
| Founder or Tec Tha time | Covered by the retainer | Hours per month: track it | Track hours in the first 3 months. If support takes more than the retainer covers, reprice at renewal. |

**WhatsApp cost estimate for the proposal:** (number of reminders + dues messages + feedback requests + owner reports per month) × Meta's current per-message rate for that category. Do the sum with their real appointment and bill volumes; never use a made-up volume.

## 4. Discount rules

Order of levers. Use the first one that works:

1. **Cut scope, not price:** shorter pilot (30 days), one automation, one branch.
2. **Credit the pilot fee** against Phase 1 setup.
3. **Phase the payment:** split the setup fee across go-live milestones.
4. **Price discount:** last resort, within the limits below.

| Discount | Who can approve | Condition |
|---|---|---|
| Up to 10% off a setup fee | Sales Lead | Signed within 7 days of the proposal, or a written case study or referral agreement. |
| 10–20% off a setup fee | Founder | First client (design partner), with a case study, a reference call and permission to use their name. |
| Retainer discount for prepaying 6 or 12 months | Founder | Up to [__]%. Only once the product has run 3 months without major incidents. |
| More than 20%, or a free month | Not allowed | Reduce scope instead. |

Every discount is written in the proposal as "discount", not hidden in a lower list price, so the next renewal starts from the real price.

## 5. Never discount and never give free

- **Pass-through costs** (Meta, server, AI API): always at actual cost. Never absorb them; at volume they could exceed our fee.
- **The pilot itself:** the audit is free, the pilot is paid. A free pilot gets no coordinator time and no data from the hospital.
- **Data safety work:** NDA, data processing agreement, consent setup, one login per staff member, backups, audit log. Never offered as an optional extra or traded away for price.
- **Staff training:** a pilot without training fails, and that hurts our reputation more than the lost fee.
- **The monthly results report:** it is what makes the retainer renewable.

## 6. Walk-away rules

- The hospital insists the WhatsApp account or server is in Tec Tha's name: decline. It breaks rule 3 (accounts in the hospital's name).
- The hospital wants bulk marketing messages to patients who have not consented: decline. It breaks rule 1 (consent) and risks the number.
- The hospital wants us to "guarantee" a percentage or ₹ result: offer the agreed success measure, never a guarantee.
- The price falls below what covers our time for the pilot (founder sets this floor: ₹[______]).

## 7. Before quoting this hospital: checklist

- [ ] Discovery answers filled (PITCH_TALK_TRACK.md): billing software, export or API, WhatsApp type, volumes.
- [ ] Phase 2 effort estimated with the Solution Architect once we know the billing vendor.
- [ ] Meta's current India rate card checked, and the WhatsApp estimate based on their real volume.
- [ ] Server price checked with the provider.
- [ ] Founder has set the final numbers and the floor, and replaced every assumption above that is used in the quote.
