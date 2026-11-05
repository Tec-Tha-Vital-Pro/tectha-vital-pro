# Tec Tha Vital Pro — AI Feature Research

Prepared by the Tec Tha AI Research Lead, November 2026. Research only: no code changes.

**Bottom line.** The AI that pays off fastest in an Indian hospital is the AI around the patient journey and the money: voice and WhatsApp access, no-show prediction, unbilled-service and claims checks, report explanations, bed and OT forecasts. Evidence for these is solid enough, and regulatory risk is low because nothing diagnoses or treats. Clinical prediction (sepsis, deterioration, imaging triage) is valuable but has a documented record of over-promising, and in India it now falls under CDSCO's medical device software rules. It should come later, after local validation.

How to read the evidence column: peer-reviewed studies are marked **[peer-reviewed]**, vendor or press claims are marked **[vendor claim]**, and anything I could not verify is marked **[unverified]**. Several vendor figures circulating in the market (for example "40–50% documentation time saved", "35% fewer no-shows") have no independent source; they are not used to justify any recommendation here.

---

## 1. Ranked AI feature list

Status key: **Now** = build now with rules, Claude API or simple ML on data the pilot already collects · **Pilot data** = needs 3–6 months of the hospital's own data first · **Validation** = needs a clinical validation study and a CDSCO assessment before use on patients.

| # | Feature | Module | What it does | Evidence / market example | Value for a 2-branch → 300-bed hospital | Data needed | Build approach | Regulatory risk | Effort | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Multilingual voice + WhatsApp receptionist | Patient Engagement | Books, reschedules and answers timings, fees and balances in Indian languages; emergencies to 108 | Relatient Dash Voice AI handles confirmations and rescheduling [vendor claim, about a quarter of scheduling calls offloaded]; BHASHINI–NHA MoU brings speech-to-text and text-to-speech to ABDM and PM-JAY apps | Front desks miss many calls; fewer walk-outs, 24/7 booking | Doctors, slots, fees, balances (already in Tec Tha Vital) | Claude API (structured output) + browser speech / BHASHINI ASR-TTS; code validates every slot | Low (administrative) | M | Now (built in v1; voice in progress) |
| 2 | No-show risk score + smart overbooking | Patient Experience | Scores each appointment's no-show risk and suggests targeted reminders or a safe overbook slot | Marshfield Clinic XGBoost model on about 1.26M appointments, 1 overbook advised per 6 at-risk visits [peer-reviewed]; Geisinger model found lead time and past no-shows as top predictors; a JAMIA review says benefit of model-driven overbooking is still uncertain | Empty doctor slots are lost revenue; risk-targeted calls cost less than calling everyone | Appointment history, lead time, distance, past no-shows | Gradient boosting (LightGBM/XGBoost) + rules for action | Low | S–M | Pilot data (rules now) |
| 3 | Unbilled-service and leakage agent | Financial Management | Matches orders, OT notes, nursing notes and pharmacy issues to bills; flags gaps with evidence | Pilot's rule-based unbilled check already finds gaps in sample data; RCM AI market moving to pre-submission review [vendor claim] | Direct rupees recovered every week | Orders, bills, notes | Rules + Claude for reading notes; human approves every line | Low | M | Now |
| 4 | Claims document completeness + denial-risk check | TPA & Insurance | Checks each pre-auth/claim file against the payer checklist and predicts denial risk with the missing piece named | A US community health network reported 22% fewer prior-auth denials after pre-submission AI review [vendor claim, single case] | Faster cashless approvals inside IRDAI's 1 h / 3 h limits; fewer write-offs | Claim files, payer rules, past outcomes | Rules + OCR + Claude extraction; ML once outcomes accumulate | Low | M | Now (checklist), Pilot data (prediction) |
| 5 | Lab report explainer for patients | Diagnostics | Plain-language, translated description of what each test measures and that the doctor will explain results; never interprets | LLM medication and lab studies show LLMs miss implied risks [peer-reviewed], so explanation must be template-bound | Fewer calls to the lab; patients understand reports in their language | Test catalogue, validated results | Doctor-approved templates per test + Claude translation; no result interpretation | Low (if strictly non-interpretive) | S | Now |
| 6 | Inbox draft replies for staff | Patient Engagement | Drafts replies to patient WhatsApp messages for staff to edit and send | Epic/Stanford study: 20% draft use, lower burden scores, no time saved [peer-reviewed]; 13-specialty pilot: 38% use, 23 s saved for support staff [peer-reviewed] | Lower burnout for front desk; modest time saving | Message history, hospital FAQ | Claude API with hospital-specific context; staff must send | Low | S | Now |
| 7 | Daily owner briefing with verified insights | Command Centre | Morning summary for every branch: what changed, why, one suggested action; every number checked against data | Built in v1 (insights.py verifies numbers) | Owner sees problems the same morning | Metrics already computed | Claude + numeric verification | Low | S | Now (built) |
| 8 | Bed demand and discharge forecast | Hospital Operations | Forecasts admissions and free beds for the next 4–24 h and 7 days per ward | UCLH XGBoost ED-admission forecasts, AUROC 0.82–0.90, error 4.0 vs 6.5 admissions for the rolling-average benchmark [peer-reviewed]; Imperial study: simple linear models match boosting at 1–7 day horizons | Fewer ED boarders and cancelled electives | ADT history, ED arrivals, scheduled admissions | Start with seasonal linear / Prophet; boosting for short horizon | Low | M | Pilot data |
| 9 | OT case-duration prediction + schedule optimiser | Hospital Operations | Predicts each case's duration from surgeon, procedure and patient factors; suggests the OT list | LightGBM beat scheduled durations in a pediatric hospital; 170k-case XGBoost MAE 30 min [preprint]; JMIR 2025 orthopedic study: less overtime but more under-use [peer-reviewed] | Fewer overruns and idle theatres | OT logs | LightGBM + constraint optimiser (OR-Tools) with human final say | Low | M | Pilot data |
| 10 | Churn and care-adherence engine | Patient Engagement | Scores patients likely to drop out of care programmes; explains reasons; picks the nudge | Standard retention modelling; no healthcare-specific Indian evidence found [unverified] | Chronic-care revenue and outcomes | Visits, refills, follow-ups, dues | Gradient boosting + SHAP reasons + rules | Low | M | Pilot data (rules now) |
| 11 | Pharmacy demand forecast + expiry arbitrage | Pharmacy Supply Chain | Forecasts usage per item; moves near-expiry stock or returns it in time | General retail forecasting practice; no peer-reviewed hospital-India study found [unverified] | Less expired stock written off | Dispensing, batches, expiry | Prophet/LightGBM + linear optimisation | Low | M | Pilot data |
| 12 | Clinical coding assistant (ICD-10, PM-JAY packages) | TPA & Insurance | Suggests codes with the quoted supporting sentence for a certified coder | Autonomous coding vendors report 90%+ auto-accept on routine encounters [vendor claim, no independent benchmark] | Fewer coding denials, faster discharge billing | Discharge summaries, code tables | Claude with citations + rules; coder signs | Low–Medium | M | Now (assistant only, never autonomous) |
| 13 | Ambient scribe (shadow charting) | Clinical Care | Drafts the consultation note from audio for the doctor to edit and sign | NEJM AI RCT (238 physicians): Nabla cut documentation time about 10%; scribes occasionally make clinically significant errors [peer-reviewed]; Sutter/Abridge JAMA Netw Open: promising, varied by specialty and gender [peer-reviewed] | Doctor time back; better notes | Audio (consented), templates | Speech-to-text (Indian-language ASR) + Claude; doctor signs | Medium (documentation, but errors can harm) | L | Validation (start as opt-in pilot with audit) |
| 14 | Medication safety checker | Clinical Care / Pharmacy | Interaction, allergy, renal-dose and duplicate checks at prescribing | GPT-4o identified the interacting pair only 54.7% of the time; LLMs missed metoprolol–verapamil [peer-reviewed] — so use a licensed drug database, not an LLM | Prevents harm; required by NABH | Formulary, licensed interaction database | Rules on a licensed database (e.g. CIMS); LLM only to explain alerts | Medium | M | Now (rules), never LLM-only |
| 15 | Critical value call-out tracking | Diagnostics | Ensures every critical lab value is called out, read back and acknowledged; escalates | Standard lab-safety practice (NABH) | Patient safety, accreditation | Lab results, staff roster | Rules + notifications | Low | S | Now (in Pro build) |
| 16 | Reflex testing rules | Diagnostics | Adds follow-on tests automatically by approved rule (e.g. TSH high → free T4) | Standard lab practice | Faster diagnosis, more billed tests | Lab results | Rules table approved by pathologist | Low | S | Now (in Pro build) |
| 17 | NEWS2 early-warning with trends | Clinical Care | Computes NEWS2 at every vitals entry and alerts on rising trends | NEWS2 predicts death and ICU transfer with moderate accuracy, varies by population; outcome benefit unproven [peer-reviewed reviews] | Earlier escalation on wards | Vitals | Validated published score (rules), not ML | Medium (score is published; alerting workflow matters) | S | Now, with ICU team tuning thresholds |
| 18 | Sepsis prediction model | Clinical Care | ML risk of sepsis from vitals, labs, notes | Epic Sepsis Model external validation: AUC 0.63, missed 67% of sepsis, alerts on 18% of inpatients, 109 evaluations per true case [peer-reviewed] | Potentially large, if it works locally | Vitals, labs, cultures, antibiotics | Local model only after validation | High (CDSCO medical device software) | L | Validation |
| 19 | AI-ECG low-EF screening | Diagnostics | Flags ECGs likely to show low ejection fraction for echo | Mayo EAGLE cluster RCT: low-EF diagnoses up 32% (1.6% → 2.1%), 5 new diagnoses per 1,000 screened [peer-reviewed] | Earlier heart-failure diagnosis | 12-lead ECG files | Licensed regulated model (e.g. Anumana/Eko) — integrate, don't build | High (regulated device) | M (integration) | Validation / partner |
| 20 | Chest X-ray TB and abnormality triage | Diagnostics | Prioritises abnormal X-rays and flags presumptive TB | Qure.ai qXR: WHO-evaluated for TB triage, FDA/CE cleared; Mumbai deployment found 20–30% additional TB cases [vendor claim] | Radiologist shortage; NTEP programme value | DICOM images | Integrate a regulated product via PACS | High (regulated device) | M (integration) | Partner |
| 21 | Triage assistant in ED/OPD | Clinical Care | Ranks waiting patients by urgency from complaint and vitals with reasons | No independent Indian evidence found [unverified]; red-flag rules are standard | Sickest seen first | Complaint, vitals | Rules (red flags) + Claude for free-text; nurse decides | Medium–High | M | Validation |
| 22 | Patient-friendly discharge summary | Clinical Care | Converts the signed summary into plain language in the patient's language | No direct evidence found [unverified]; low risk if generated from the signed summary only | Fewer readmission calls, better adherence | Signed discharge summary | Claude translation with doctor approval | Low–Medium | S | Now (doctor approves) |
| 23 | Staff rostering optimiser | Hospital Operations | Builds nurse and staff rosters meeting ratios, leave and fairness | Standard operations research | Fewer gaps and overtime | Roster, leave, census | OR-Tools constraint solver | Low | M | Pilot data |
| 24 | Fraud and abuse sentinel | Financial / TPA | Flags outlier length of stay, repeated packages, odd-hour billing for audit committee | Payer-side fraud analytics are established; no hospital-side Indian study found [unverified] | Audit readiness, PM-JAY empanelment safety | Claims, bills | Statistical outliers + rules | Low | M | Pilot data |
| 25 | ABHA/ABDM record summariser | Clinical Care | Summarises records pulled through ABDM consent into a one-page view for the doctor | ABDM enables consented record sharing; BHASHINI–NHA work on multilingual ABDM apps | Saves doctor time with outside records | ABDM FHIR bundles | Claude summarisation with source links | Medium | M | After ABDM M2/M3 |
| 26 | Pharmacogenomics alerts | Clinical Care | CPIC guideline alerts when a genetic report exists | CPIC guidelines are the clinical standard | Niche (specialist centres) | Structured genetic results | Rules from CPIC tables | Medium | M | Later |
| 27 | Digital twin / pathway simulator | Research | Simulates pathway and staffing changes on de-identified data | Research tool; no Indian deployment evidence | Teaching hospitals only | De-identified data | Discrete-event simulation | Low (research) | L | Later |

---

## 2. Top 8 "build now" features — engineering specs

All eight share the platform rules: consent before any patient message, audit log entry for every AI output and human decision, model name and version stored with each output, numbers in AI text verified against source data, and a human approves anything that changes a record.

### 2.1 Multilingual voice receptionist (feature 1)
- **Inputs:** patient speech (browser Web Speech API now; BHASHINI or Whisper ASR for telephony later), phone number, hospital context (doctors, free slots, fees, the patient's own upcoming visit and balance).
- **Outputs:** structured JSON from `app.ai.receptionist` (intent, language, reply, doctor_id, slot, needs_human, urgency) and spoken reply via speech synthesis.
- **Model:** Claude with structured output; effort low; prompt `RECEPTIONIST_V1` (already written).
- **Guardrails:** code validates doctor and slot against the database; emergency keyword rule runs before the model; no medical advice; no audio stored, transcripts only; consent captured for voice.
- **UI:** mic button on the patient app and public demo with a visible "Type instead" fallback.
- **Tests:** booking happy path; invalid slot rejected; emergency phrase in Hindi and Tamil returns the 108 reply; AI-off menu works.

### 2.2 Unbilled-service and leakage agent (feature 3)
- **Inputs:** orders, OT logs, nursing notes, pharmacy issues, bills, tariff master.
- **Outputs:** findings (type, amount, evidence with quoted source line, suggested bill item, status).
- **Model:** rules first; Claude reads free-text notes and returns candidate services with the quoted sentence (structured output).
- **Guardrails:** never edits a bill on its own; only services documented as delivered; dismissal reason required.
- **UI:** AI Labs findings queue with Accept (adds to bill) / Dismiss; weekly rupees-recovered tile on the dashboard.
- **Tests:** an order without a bill line creates exactly one finding; Accept adds one bill item; repeat runs are idempotent; a note without a delivered service creates no finding.

### 2.3 Claims document checker (feature 4)
- **Inputs:** claim, payer/TPA, uploaded documents (OCR text), payer checklist table.
- **Outputs:** missing items list, readiness score, suggested query response draft.
- **Model:** rules for the checklist; Claude extracts fields from OCR text with citations.
- **Guardrails:** never submits claims; drafts only; payer rules maintained by the insurance desk.
- **UI:** checklist panel on each claim card; red/amber/green readiness with words.
- **Tests:** a claim missing a discharge summary is flagged; complete claim scores ready; OCR field extraction validated against a fixture.

### 2.4 No-show risk (rules now, ML after data) (feature 2)
- **Inputs:** lead time, past no-shows, first visit or follow-up, distance band, payment status, reminder response.
- **Outputs:** risk band (low/medium/high) with top reasons; action (extra reminder, call task, overbook suggestion).
- **Model:** points-based rule score now; LightGBM once 3 months of local data exist, compared against the rule score before switching.
- **Guardrails:** overbooking only suggested, capped per doctor per session; no use of religion, caste or other sensitive attributes.
- **UI:** risk chip on the appointment list; "Call high-risk patients" task list.
- **Tests:** reasons always present; caps respected; sensitive fields absent from features.

### 2.5 Lab report explainer (feature 5)
- **Inputs:** validated test names and the patient's language.
- **Outputs:** per-test description of what it measures, plus "Your doctor will explain your results."
- **Model:** doctor-approved English templates per test, translated by Claude once and cached after review.
- **Guardrails:** never mentions the patient's values as good or bad, never suggests diagnoses or medicines; released only after validation.
- **UI:** "What is this test?" link on each report in the patient app.
- **Tests:** output contains no numbers from the result; blocked phrases list (e.g. "you have", "normal for you") never appears.

### 2.6 Staff inbox draft replies (feature 6)
- **Inputs:** last 10 messages in the thread, hospital FAQ, patient's next visit and balance.
- **Outputs:** draft reply in the patient's language.
- **Model:** Claude; effort low.
- **Guardrails:** never auto-sends; staff edits and sends; no clinical advice; drafts logged with whether they were used.
- **UI:** "Suggest reply" button in the Messages composer.
- **Tests:** draft never sent without a staff action; emergency messages bypass drafts and show the emergency banner.

### 2.7 Clinical coding assistant (feature 12)
- **Inputs:** signed discharge summary, procedures, PM-JAY package list, ICD-10 tables.
- **Outputs:** suggested codes, each with the quoted supporting text and confidence.
- **Model:** Claude with citations; rules validate codes against the payer's package rules.
- **Guardrails:** a certified coder accepts or edits every code; accuracy tracked monthly.
- **UI:** coding panel on discharge billing.
- **Tests:** every suggested code has a citation that exists in the source; invalid codes rejected by rules.

### 2.8 NEWS2 with trend alerts (feature 17)
- **Inputs:** respiration rate, SpO₂ (scale 1/2), oxygen, BP, pulse, consciousness, temperature.
- **Outputs:** score, risk band, trend over the last 24 h, escalation task.
- **Model:** the published NEWS2 scoring (rules), not machine learning.
- **Guardrails:** thresholds set by the ICU/medical team; alerts reviewed monthly for fatigue; doctors decide treatment.
- **UI:** score chip beside vitals; ward board sorted by score.
- **Tests:** published scoring examples reproduce exactly; trend alert fires once per rise, not on every entry.

---

## 3. What not to build (and why)

- **An in-house sepsis prediction model shipped without local validation.** The most widely deployed commercial model performed far worse in external validation than reported (AUC 0.63, missed 67% of sepsis, alerts on 18% of inpatients). Alert fatigue is itself a safety risk.
- **LLM-only drug-interaction checking.** Studies show LLMs miss known interactions and do worse with implied risks; use a licensed interaction database and let the LLM only explain alerts.
- **Autonomous coding or claim submission without a human.** Accuracy claims are vendor-reported only; denials and audit risk fall on the hospital.
- **Building our own imaging AI (X-ray, CT, ECG).** These are regulated devices with years of validation behind products such as Qure.ai qXR and Mayo's AI-ECG; integrate certified products instead.
- **AI that gives patients medical advice or interprets their results.** Likely CDSCO-regulated and unsafe without clinician review.
- **Marketing headlines as product promises.** Figures like "40–50% less documentation time" or "35% fewer no-shows" have no independent source; independent trials show around 10% time saving for scribes.

---

## 4. AI governance

Aligned to ICMR's *Ethical Guidelines for Application of AI in Biomedical Research and Healthcare* (2023) — principles including accountability and liability, autonomy, data privacy, validity, explainability, non-discrimination and risk minimisation — and to the DPDP Act 2023.

1. **Model registry.** Every model and prompt has an entry: name, version, purpose, intended users, data used, validation results, owner, date approved, retirement plan. Prompts are versioned constants in code (as `RECEPTIONIST_V1` already is).
2. **Human in the loop.** No AI output changes a clinical or financial record without a named person approving it. The approval is logged.
3. **Logging.** Each AI call logs the model version, inputs reference (not raw personal data where avoidable), output, validation result and the human decision. Logs are kept per the hospital's retention policy.
4. **Validity before use.** Clinical features go through a local retrospective check, then a silent run (shown to no one), then a supervised pilot, before general use — ICMR's validity principle. A CDSCO medical-device-software assessment is done before any feature that diagnoses, predicts disease or recommends treatment.
5. **Bias checks.** Performance is reported by sex, age band, branch, language and payer type at each review. Sensitive attributes (religion, caste) are never model features.
6. **Patient autonomy and consent.** Patients are told when AI is used and can choose to deal with a person instead (ICMR autonomy). Consent covers AI processing; patient data sent to providers outside India requires explicit consent and a data processing agreement (DPDP).
7. **Monitoring.** Monthly review of accuracy, alert volumes, override rates and complaints; automatic alert if acceptance or performance drifts.
8. **Incident process.** Any AI-related harm or near miss is reported like a clinical incident, the feature can be switched off per hospital in one click, and the root cause is reviewed by the clinical safety committee within 7 days.
9. **Change control.** Model or prompt changes follow a documented change protocol (CDSCO guidance discusses change protocols for adaptive AI software) and are re-validated before release.

---

## 5. Sources

Only pages returned by searches during this research are listed. Several are secondary summaries; where a claim came only from a vendor or blog it is marked in the table above.

- Ambient scribes: [Ambient AI Scribes in Clinical Practice: A Randomized Trial (PubMed)](https://pubmed.ncbi.nlm.nih.gov/41497288/), [Sutter Health ambient AI study (EurekAlert)](https://www.eurekalert.org/news-releases/1107474), [Health systems increase use of Microsoft ambient AI (Becker's)](https://www.beckershospitalreview.com/healthcare-information-technology/ai/health-systems-increase-use-of-microsoft-ambient-ai-4-notes)
- Sepsis model: [External validation of the Epic Sepsis Model (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC8218233), [Healthcare IT News summary](https://www.healthcareitnews.com/news/research-suggests-epic-sepsis-model-lacking-predictive-power)
- NEWS2: [PROBAST systematic review of NEWS2 (medRxiv preprint)](https://www.medrxiv.org/content/10.1101/2025.03.03.25322780.full.pdf), [NEWS2 in cardiac admissions (BMJ Open)](https://bmjopen.bmj.com/content/13/3/e066131.full.pdf)
- Radiology AI in India: [Qure.ai with PATH India (Qure.ai)](https://qure.ai/news_press_coverages/Qure-ai-Teams-Up-with-PATH-India-to-Implement-AI-Enabled-Chest-X-Ray-Solution-for-TB-and-Covid-19-Screening-in-Maharashtra-through-Unitaid-Funding), [MCGM case study](https://qure.ai/impact_stories/artificial-intelligence-for-covid-19-detection-management-in-mumbai-by-mcgm), [Business Standard on incidental TB findings](https://www.business-standard.com/india-news/ai-based-tool-boosting-incidental-tuberculosis-findings-in-india-124030300292_1.html)
- AI-ECG: [EAGLE trial (Nature Medicine)](https://www.nature.com/articles/s41591-021-01335-4), [TCTMD summary](https://www.tctmd.com/news/ai-ecg-allows-early-diagnosis-low-ef)
- No-show prediction: [Marshfield Clinic model (PMC)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10503036/), [Geisinger case study](https://www.geisinger.org/innovation-steele-institute/case-studies/2020/02/13/20/48/case-studies-machine-learning)
- Bed forecasting: [UCLH real-time admission forecasts (medRxiv)](https://www.medrxiv.org/content/10.1101/2022.03.07.22271999v3), [ED demand forecasting comparison (BMC Emergency Medicine)](https://bmcemergmed.biomedcentral.com/track/pdf/10.1186/s12873-020-00395-y), [Bed-assignment optimisation (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10709483)
- OT scheduling: [Predict-then-optimize for arthroplasty (JMIR Med Inform 2025)](https://medinform.jmir.org/2025/1/e70857/PDF), [ML case-duration pilot (PubMed)](https://pubmed.ncbi.nlm.nih.gov/30656433/), [170k-case XGBoost (medRxiv preprint)](https://medrxiv.org/content/medrxiv/early/2020/06/12/2020.06.10.20127910.full.pdf)
- LLM inbox drafts: [Stanford AI-drafted replies (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10955355/), [13-specialty pilot (Thieme)](https://www.thieme-connect.com/products/ejournals/abstract/10.1055/a-2576-0579), [Dutch hospital cohort (Frontiers)](https://www.frontiersin.org/articles/10.3389/fdgth.2025.1588143/full)
- Medication safety and LLMs: [LLM medication management performance analyses (arXiv)](https://arxiv.org/pdf/2402.01741v2.pdf), [LLM contraindication reasoning (arXiv 2025)](https://arxiv.org/pdf/2511.04328v1)
- Revenue cycle AI [mostly vendor content]: [ASP-RCM on autonomous coding](https://asprcmsolutions.com/ai/), [Nym Health](https://blog.nym.health/ai-in-healthcare-revenue-cycle-management), [Becker's on coding and denials](https://go.beckershospitalreview.com/hit/ai-for-smarter-coding-denials-management-without-the-headaches)
- Voice agents [mostly vendor content]: [Relatient Dash Voice AI](https://www.smartcustomerservice.com/Articles/News-Briefs/Relatient-Launches-Dash-Voice-AI-Agent-to-Automate-Patient-Appointment-Management-in-Call-Centers-169286.aspx), [Becker's on agentic AI in call centers](https://www.beckershospitalreview.com/healthcare-information-technology/redefining-patient-access-through-agentic-ai-in-healthcare-call-centers)
- India: [ICMR Ethical Guidelines for AI in Healthcare 2023 (PDF)](https://www.icmr.gov.in/icmrobject/custom_data/pdf/Ethical-guidelines/Ethical_Guidelines_AI_Healthcare_2023.pdf), [BHASHINI–NHA partnership (Devdiscourse)](https://www.devdiscourse.com/article/humor/3775197-bhashini-partners-with-nha-to-enable-multilingual-ai-across-ayushman-bharat-platforms), [CDSCO medical device software guidance (Emergo by UL)](https://www.emergobyul.com/news/india-cdsco-finalizes-guidance-medical-device-software), [CDSCO draft guidance takeaways (India Briefing)](https://india-briefing.com/news/cdsco-draft-guidance-medical-software-40691.html) — the finalisation date of CDSCO's guidance could not be confirmed against the official text [unverified].
