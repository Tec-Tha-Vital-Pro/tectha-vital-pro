# Tec Tha Care Connect — Roadmap

Owner: Head of Product · Last reviewed: 4 Nov 2026. Feature numbers (F1–F30) refer to [PRD.md](PRD.md).

Each phase ends at a **gate**. We move on only when every item in the gate is true, and the owner agrees in writing. No dates are promised to the client beyond the current phase.

## Phase 0 — Demo-ready (done)

v1 features F1–F13 work in simulator mode with seed data for two branches. 63 of 64 tests pass.

**Gate 0 → Pilot (what must be true to sign a paid pilot)**
- [ ] Discovery answered: which CRM, which billing software, export or API, WhatsApp type, biggest pain (PRODUCT_KNOWLEDGE section 9).
- [ ] The owner picks **one branch and one problem** (dues collection or appointment reminders).
- [ ] Success measure written down with the baseline from the hospital's own data, for example "no-shows from X% to Y% in 45 days".
- [ ] NDA and data processing agreement signed; consent line added to the registration form.
- [ ] All tests pass (fix `test_messages_and_audit_pages`).

## Phase 1 — Pilot hardening and pilot (next 4 weeks of build, then 30–45 days live)

Build F14 templates, F15 safe webhook, F16 backups and alerts (all P0), then F17 payment link and F18 branch restriction (P1), F19 results report, F20 user management. The patient app (/my) and AI stay **off**.

| Week | Ship |
|---|---|
| 1 | Submit Meta templates; F15 message-ID dedupe and status callbacks; server, HTTPS, backups (F16) |
| 2 | F14 template sending; failed/blocked sends on dashboard; scheduler alert |
| 3 | F18 branch restriction with tests; F20; daily CSV import from the pilot branch |
| 4 | F17 payment link (if dues is the pilot problem); F19 report; QA and Security sign-off; go live one automation at a time |

**Gate 1 → Both branches**
- [ ] The agreed success measure is met, or the owner accepts the result in writing.
- [ ] 30 days live with zero messages sent without consent and zero silent failures (every failure visible on the Messages screen or audit log).
- [ ] Live delivery success ≥ 95% on approved templates (failures explained).
- [ ] Backup restore tested; no data loss incidents.
- [ ] Branch restriction (F18) tested on every screen and action.
- [ ] Front desk and billing staff at the pilot branch use their own logins daily; no shared logins.
- [ ] Owner agrees the price for phase 2.

## Phase 2 — Both branches

Roll out all v1 automations at both branches; the owner dashboard and 9 am report go live across branches. Start F24 groundwork (map the second branch's billing software if different).

**Gate 2 → Core sync**
- [ ] Both branches live for 30 days with the Gate 1 quality bars held.
- [ ] Owner uses the dashboard or 9 am report on most working days (asked, not assumed).
- [ ] Duplicate patients across branches: none created through Care Connect.
- [ ] The billing vendor has agreed an API or scheduled export, in writing, with a named contact.
- [ ] Monthly results report delivered and accepted twice.

## Phase 3 — Core sync (CRM ↔ billing)

F24: scheduled sync with the client's actual CRM and billing products, write-back only for agreed fields; F25 report and bill-ready messages; F27 Hindi templates. If the owner wants it, start F21 patient app and F22 AI receptionist, each behind its own gate below.

**Gate 3 → Retainer**
- [ ] Sync runs daily for 30 days with mismatches reported, not dropped; manual re-entry hours down against the baseline.
- [ ] No sync-caused data errors in billing (checked with the billing desk).
- [ ] Support runbook written; issues answered within the agreed time.
- [ ] Owner signs the monthly retainer (setup fee per phase plus monthly fee; WhatsApp costs at actual cost).

**Extra gates for features that touch patients directly**
- Patient app (F21): sample lab values and the gateway-less "Pay" button removed or replaced with real data; tests for every /my route; Security review; Domain Lead sign-off.
- AI receptionist (F22): written evals with pass rate agreed by the Domain Lead; red-team report showing no medical advice; staff hand-off on every uncertain case; Security review.

## Phase 4 — Retainer and growth

Monthly results report, F26 live queue updates, F28 loyalty features, F30 ABHA, F29 stock-outs. Move from SQLite to Postgres before a third branch or a second hospital.
