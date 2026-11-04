# Master prompt — Tec Tha Vital Pro (Hospital OS, Pro edition)

Paste everything below the line into a new Claude Code session to build or extend Tec Tha Vital Pro. Code: GitHub `sanjay5777/tectha-vital-pro` (branch `pro-foundation`). Front-end demo synced with Lovable: `sanjay5777/tec-tha-vital`. Read `docs/PRODUCT_KNOWLEDGE.md`, `docs/AI_FEATURE_RESEARCH.md` and the blueprint before starting.

---

You are the lead engineer for **Tec Tha Consultancy Services**. Build **Tec Tha Vital Pro**, the full Hospital OS for Indian hospitals from 2 branches to 300+ beds, starting from the QA-approved pilot (everything in the pilot master prompt applies: consent, no medical advice, no silent failures, audit, branch isolation, quiet hours, Indian context, brand).

## Starting point
The pilot codebase (FastAPI + Jinja + SQLite, automations, billing, claims, WhatsApp, patient app, security, 167 tests). Feature modules add tables in `app/schemas/NN_name.sql` (loaded after `schema.sql`). Keep every pilot test green.

## Pro features (build in this order)
1. **Login for all** — roles owner, admin, doctor, nurse, frontdesk, billing, lab, pharmacy; password + TOTP two-step login with recovery codes; admin can require 2FA per role; Google/Microsoft sign-in via OIDC (enabled only when configured; maps to existing users; never auto-creates admins); idle timeout on shared terminals; account page (password, 2FA, sessions). Patients: mobile + one-time code.
2. **Diagnostics & Pharmacy** — tabs Laboratory / Radiology / Pharmacy counter. Lab catalogue with reference ranges by sex/age and critical limits; pipeline Collected → Received → Resulted → Validated with "Advance ›"; auto-flagging (↑/↓ amber, !! red), delta checks, auto-validate normals, pathologist validation for abnormal; critical call-out with read-back, urgent task, notification and 15-minute escalation; reflex rules (e.g. TSH high → add Free T4); radiology Scheduled → Performed → Reported with PCPNDT Form F flag for obstetric scans; pharmacy queue → FEFO dispense → billed, Schedule H/H1/X registers; patient report released only after validation, never interpreted.
3. **Command Centre** — live wall view for both branches: beds, OPD queue, critical values, claims past limit, unbilled amount, staff on duty; 30 s refresh; 1920 wall mode.
4. **Notifications** — bell with count, deep links; `notify()` API used by every module.
5. **AI voice agent** — mic on the patient app and website; browser speech-to-text and speech synthesis (en/hi/ta/te/kn/ml/mr-IN) → `/voice/turn` → the AI receptionist (Claude structured output; code validates doctor and slot; emergency rule first; no medical advice); deterministic menu when AI is off; transcripts only, never audio; telephony (Exotel/Twilio) as the next step.
6. **AI Labs (automation agents)** — framework with enabled flag, schedule and a findings queue (evidence, suggested action, Accept/Dismiss, audited): revenue-loss agent, claims document checker, follow-up/churn agent, stock/expiry agent, daily owner briefing.
7. **Next AI features** (from `docs/AI_FEATURE_RESEARCH.md`, build-now list): no-show risk score (rules first, ML after 3 months of data; overbooking only suggested and capped), lab report explainer for patients (doctor-approved templates, never interpreting results), staff inbox draft replies (staff edit and send), clinical coding assistant (ICD-10 / PM-JAY suggestions with quoted evidence; coder signs), NEWS2 early-warning with trend alerts (published score as rules; ICU-tuned thresholds).
8. **Enterprise foundation** (for big hospitals) — PostgreSQL with replica and PgBouncer, SQLAlchemy Core + Alembic, organisation → branch → department → ward → bed, leader-elected scheduler, Redis, FHIR R4 server, ABDM M1–M3, NHCX, observability, Locust load tests (500 users), HA deployment, ISO 27001 controls.

## AI governance (must ship with every AI feature)
Model registry (name, version, prompt version), human-in-the-loop for every clinical or financial action, logging of input summary/output/decision, bias checks, incident process, clinician safety committee for clinical AI, CDSCO software-as-medical-device assessment before any diagnostic or triage feature goes live, patient consent for AI processing and for data leaving India (Anthropic API).

## Front end
Lovable demo (`tec-tha-vital`, TanStack Start + Tailwind v4): premium landing (Geist, Instrument Serif accent, graphite hero, live preview), demo with 9 languages (Arabic/Urdu RTL), 6 currencies, roles, guided tour, the founder's CareOS look (graphite sidebar, violet active pill, lavender demo strip). Production screens can move to React when the team grows.

## Acceptance for every release
All pytest green; Playwright e2e for the changed flows; security review of new routes (CSRF, branch isolation, CSP, rate limits); screens checked at 390/768/1366/1920 in light and dark; docs updated; commits pushed to `pro-foundation`, never to the pilot.
