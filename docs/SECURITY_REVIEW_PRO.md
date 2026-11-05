# Tec Tha Vital Pro: Security & Privacy Review

Reviewer: Security & Privacy Engineer · Date: 2026-11-05 · Branch `pro-foundation` at `8a91943`.
Scope: everything changed since `bdbc638` (`git diff --stat bdbc638..HEAD`, 81 files, +6,561 lines). The pilot code was reviewed earlier in [SECURITY_REVIEW.md](SECURITY_REVIEW.md); its fixes are not repeated here.

**Method.** I read every new or changed module: `app/auth.py`, `app/twofactor.py`, `app/oidc.py`, `app/routes/account.py`, `app/routes/voice.py`, `app/ai/voice.py`, the receptionist changes, `app/static/voice.js`, `app/agents/*`, `app/routes/ai_labs.py`, `app/diagnostics.py`, `app/routes/diagnostics.py`, `app/routes/command.py`, `app/notify.py`, `app/ai_features/*`, `app/routes/ai_features.py`, the new schemas and templates. The test suite passed (241 passed). I checked each finding marked **Verified** with a script against a throwaway SQLite database seeded by `python -m app.seed` logic (`TT_DB_PATH` in a scratch folder, `TestClient` only, no network server, the demo DB was not touched). **Code-read** findings come from reading the code only.

## Plain-English summary for the hospital

The new login security is built well. Two-step login (authenticator app codes), recovery codes, Google/Microsoft sign-in, idle time-outs and "sign out other devices" all follow good practice, and every new screen checks the branch before it shows or changes a record. No SQL injection, no inline scripts, and no secrets in the code were found.

The main problems are about **who is allowed to do clinical actions**, not about hackers:

1. A **front-desk** user can type a lab result. If it is in the normal range, the system approves it automatically and the **patient sees it in their app**. No lab technician or pathologist ever looked at it.
2. A **front-desk** user can press "acknowledge" on an **emergency NEWS2 alert** (a deteriorating ward patient). That stops the alert being escalated to the senior team.
3. An **admin** (which includes Tec Tha support staff) can change the NEWS2 alert levels to values where even a very sick patient (score 12) raises **no alert**, with no doctor sign-off.
4. A **front-desk** user can write a radiology report and tick "PCPNDT Form F completed" for a pregnancy scan. Under the PCPNDT Act, Form F is the hospital's legal duty and a tick-box by non-clinical staff is not a safe record.

Fix these four before the Pro modules hold real patients. None of them need a large rewrite: they are role lists and one extra approval step.

## Findings table

Severity counts: **Critical 0 · High 4 · Medium 6 · Low 11 · Info 1** (22 items).

| ID | Sev | Location | Scenario | Fix | Check |
|---|---|---|---|---|---|
| P-01 | High | `app/routes/diagnostics.py:12` (`LAB_ROLES` includes `frontdesk`, `nurse`), `:156` `lab_result`; `app/diagnostics.py:119-125` | A front-desk user enters a lab value. A value in the normal range with no delta flag is stored as `Validated` by `auto-verify`, so it appears on the patient's report in `/my`. **Verified**: `fd_a` advanced a branch-A test to Received, entered a value, status became `Validated`, `validated_by = auto-verify`, audit actor `user:fd_a`. | Result entry: `{"admin", "lab"}` only. Auto-verification only when the result came from a lab user or an instrument interface; otherwise always `Resulted` for review. Keep nurses and front desk to ordering and sample collection. | Verified |
| P-02 | High | `app/routes/ai_features.py:17` (`VITALS_ROLES = CLINICAL \| {"nurse"}`, and `CLINICAL` includes `frontdesk`, `app/auth.py:35`), `:54-61` `vitals_ack` | Front desk can record vital signs and **acknowledge NEWS2 alerts**. Acknowledging stops `escalate_overdue` (`app/ai_features/news2.py:130-144`), so the emergency never reaches admin/owner. **Verified**: `fd_a` acknowledged an `emergency` alert (HTTP 303, `acknowledged_by = user:fd_a`). | Define `WARD = {"admin", "doctor", "nurse"}` for recording and acknowledging. Acknowledging an `emergency` alert should need `doctor` (or nurse plus a named doctor), and the ack form should take a short "reviewed by / action" note. | Verified |
| P-03 | High | `app/routes/ai_features.py:64-73`, `app/ai_features/news2.py:20-33` | Any admin can set urgent 19, emergency 20, rise 10, escalation 120 min. The checks only require `1 ≤ urgent < emergency ≤ 20`. **Verified**: with those values a patient scoring NEWS2 12 (no single parameter of 3) raised **no alert**; with the defaults the same vitals raised an `emergency` alert. "Admin" includes Tec Tha support logins, who are not clinicians. | Lock the RCP NEWS2 values (urgent 5, emergency 7, any single 3) as a floor: allow only stricter settings (lower numbers, shorter escalation, max 30 min). Any change needs a doctor's approval (second person) and shows on the vitals screen with who approved it. | Verified |
| P-04 | High | `app/routes/diagnostics.py:14` (`RAD_ROLES` includes `frontdesk`), `:220-229`; `app/diagnostics.py:246-261`; `app/templates/diagnostics.html:115-131` | Front desk can (a) tick "Form F completed" for an obstetric ultrasound, and (b) write and sign the radiology report (free text, 4,000 chars). There is no Form F number, no link to the signed form, and nothing stops sex-of-foetus words in the report text. The report snippet is shown to every role that can open the Radiology tab. **Verified**: `fd_a` wrote a report (`reported_by = user:fd_a`) and set `form_f_recorded = 1` on an obstetric scan. | Reporting: a `radiologist` (or `doctor`) role only. Form F: record the Form F serial number, the doctor who signed it and the upload, by the sonologist only. Add a server-side block-list for sex disclosure words (English and Hindi: "male foetus", "female", "ladka", "ladki", "बेटा", "बेटी" and so on) on obstetric reports, and hide obstetric report text from billing and owner. | Verified |
| P-05 | Medium | `app/routes/ai_features.py:18`, `:88-107`; `app/ai_features/explainers.py:114-149` | The same person can write and approve a patient-facing explainer, and admins (non-clinicians) can approve. The word filter only catches phrases like "your result is". **Verified**: admin saved and approved "Your INR is fine, stop warfarin if over 3." (`edited_by = approved_by = user:adm`); it would show on patients' validated INR reports. This breaks rule 2 (no medical advice from software). | Approve: `doctor` only, and never the same user as `edited_by`. Extend the filter to advice verbs ("stop", "start", "take", "increase", "reduce", "fine", "normal", "बंद", "लें") and to drug names, and show the final text with the patient's report preview before approval. | Verified |
| P-06 | Medium | `app/routes/diagnostics.py:13-16`; `app/routes/ai_features.py:165-166`; `app/auth.py:27, 38-39` | Diagnostics uses role names `pharmacist` and `radiology` that do not exist (`auth.ROLES` has `pharmacy` and `lab`). Results: the **pharmacy** role gets 403 on its own home screen (`/diagnostics`), so Schedule H/H1/X drugs are dispensed by **billing or front desk** instead; and the `lab` role (technicians) can **validate** results, which is the pathologist's sign-off. `auth.LAB` and `auth.PHARMACY` are defined but never used. **Verified**: pharmacy user `GET /diagnostics?tab=rx` → 403; billing user dispensed a Schedule-drug prescription (`dispensed_by = user:bill_a`). | Use the constants from `app/auth.py` everywhere. Dispensing: `{"admin", "pharmacy"}`. Validation: `doctor` (pathologist) only, or add a `pathologist` role. Add a test that every role named in a route is in `auth.ROLES`. | Verified |
| P-07 | Medium | `app/routes/diagnostics.py:16` (`VIEW_ROLES`), `:68-126` | Everyone in `VIEW_ROLES` (front desk, billing, owner, nurse, doctor) sees every lab value, critical call-out and obstetric scan for their branch. Billing and owner do not need result values. **Verified**: a billing user's `/diagnostics?tab=lab` page contains result values. | Show billing only test names, status and price; owner only counts. Show result values to doctor, nurse, lab. Log every view of a result (DPDP minimum necessary). | Verified |
| P-08 | Medium | `app/auth.py:51, 266`; `app/routes/account.py:229-246`, `:273-293` | When an admin makes two-step login compulsory for a role, existing users enrol with **only their password**. Anyone who already knows a nurse's password (shared, written on the terminal) logs in, adds their own authenticator, and from then on the real nurse is locked out and the attacker holds both factors. Also, an admin can reset another admin's two-step login and turn the policy off with no re-entry of password or code. **Verified**: `nurse_a` with 2FA required was sent to `/account/2fa` and could enrol a new authenticator with the password session alone. | Enrolment for a required role: needs a one-time enrolment code given by an admin in person, or the admin approves the new device. Ask for the admin's own password plus TOTP code before `2fa-reset`, `security-policy` and user password resets. Notify the user (bell plus WhatsApp to staff mobile) when their 2FA changes. | Verified |
| P-09 | Medium | `app/routes/voice.py:60-91`, `:100-108`; `app/ai/voice.py:141-145`, `:218-222` | `/voice/demo` is public whenever `TT_WHATSAPP_MODE=simulator`, which is the **default**. Anyone can start 30 sessions an hour per IP, each with any phone number, and each creates a staff call-back task; an emergency phrase creates an **URGENT** task containing 60 characters of the caller's text ("call Dr Rao on 9000000000"), which is a phishing path to staff. `/voice/turn` has no limit at all; with AI on, every turn is a paid Claude call. **Verified**: 29 sessions with fake numbers created 29 tasks before the 429; 60 turns in one session all returned 200. | Serve `/voice/demo` only when `TT_ENV=dev` or a separate `TT_VOICE_DEMO=on`, never on a hospital install. Rate-limit `/voice/turn` (e.g. 20 per session, 120 per IP per hour) and cap turns per session. Strip phone numbers and URLs from caller text copied into task titles. | Verified |
| P-10 | Medium | `app/ai_features/drafts.py:50-56`; `app/ai_features/coding.py:53-63, 84-87`; `app/agents/actions.py:98-108`; `app/ai/voice.py:146-148` | With `TT_AI=on`, four new paths send patient data to Anthropic (outside India): the last 10 WhatsApp messages of a conversation (not branch-filtered) for draft replies; order, bill-item and lab-test lines for coding; AI Labs findings with patient names and amounts for "Explain"; and voice conversations. This widens pilot finding S-15 (still open). | Keep AI off until the hospital signs off the data flow and a DPA is in place. Pseudonymise before sending (replace names, phones, UIDs with tokens and map back locally). Record each feature in the governance register with its data categories. | Code-read |
| P-11 | Low | `app/ai/voice.py:111-117`; `app/schemas/10_auth_ai.sql:27-45` | Voice session tokens never expire and voice turns are kept forever. **Verified**: a session back-dated to 2020 still accepted a turn (200). | Expire sessions after 30 min idle / 2 h total. Delete or anonymise `voice_turns` after the retention period the hospital chooses (e.g. 90 days). | Verified |
| P-12 | Low | `app/twofactor.py:81`, `:121-123`; `app/db.py` migrate (`totp_secret TEXT`) | TOTP secrets are stored in plain text, so anyone with a database backup can generate every staff member's codes. Recovery codes are HMAC'd with `TT_SESSION_SECRET`, so rotating that secret silently breaks every recovery code. | Encrypt `totp_secret` with a separate key (`TT_TOTP_KEY`, e.g. Fernet). Hash recovery codes with a dedicated key or plain salted SHA-256, not the session secret. Document the rotation effect. | Code-read |
| P-13 | Low | `app/twofactor.py:99-110`, `:138-147` | Code checks are read-then-write. Two parallel requests with the same TOTP code or recovery code can both succeed. Sequential replay is correctly refused (**Verified**: same code accepted once, then refused). | Use a conditional update: `UPDATE users SET totp_last_step = ? WHERE id = ? AND totp_last_step < ?` and check `rowcount`; the same for `used_at IS NULL` on recovery codes. | Code-read |
| P-14 | Low | `app/routes/account.py:258-268` | Turning off your own two-step login does not end your other sessions, unlike password change and admin reset. | Call `auth.end_sessions` and reissue this browser's cookie, as `/account/password` does. | Code-read |
| P-15 | Low | `app/routes/account.py:74-83` | The 5-wrong-codes limit is per user only. Anyone who knows the password can keep the real user locked out of the second step indefinitely. | Key the limit on user + IP, plus a higher per-user limit; tell the user by bell/WhatsApp after repeated failures. | Code-read |
| P-16 | Low | `app/oidc.py:347`, `:405-410`, `:425-432`; `app/routes/account.py:94-108` | Microsoft defaults to the `organizations` tenant and accepts any tenant's issuer; the domain allow-list reads the `email`/`preferred_username` claim, which Microsoft does not verify. Linking needs a password session and login matches on `sub`, so this is not an account takeover, but the allow-list gives false comfort. Without `TT_OIDC_ALLOWED_DOMAINS`, staff can link personal Gmail accounts. Starting a link is a GET without CSRF, so another site can restart (and break) a staff member's sign-in. | Require `TT_OIDC_MICROSOFT_TENANT` to be the hospital's tenant id and check `tid`. Require `TT_OIDC_ALLOWED_DOMAINS` when SSO is on. Make `?link=1` a POST with CSRF. | Code-read |
| P-17 | Low | `app/agents/actions.py:39-65` | Accepting a finding checks `status = 'open'` and then runs the action. A double-click or two admins at once can run a stock transfer or bill addition twice. | Claim the finding first: `UPDATE findings SET status='accepting' WHERE id=? AND status='open'` and act only if `rowcount == 1`, all in one transaction. | Code-read |
| P-18 | Low | `app/routes/ui.py:943`; `app/ai_features/drafts.py:70-78` | `draft_id` sent with a reply is not checked against the phone or branch, so any front-desk user can mark another conversation's draft as "sent/edited" and skew the governance log. | Load the draft with `id = ? AND phone = ?` for the phone being replied to. | Code-read |
| P-19 | Low | `app/static/app.js:98-106`, `app/templates/command.html:6`, `app/auth.py:177-208` | The Command Centre reloads itself every 30 s, and every request pushes the idle clock forward. A doctor who leaves `/command` open on a shared terminal is never logged out by the 15-minute idle rule (only the 8-hour limit applies). | Give wall displays a separate read-only kiosk login, or skip the idle refresh for auto-reload requests (send a header such as `X-Auto-Refresh: 1` and don't refresh on it). | Code-read |
| P-20 | Low | `app/routes/diagnostics.py:75` | Every `GET /diagnostics` runs `diagnostics.sweep`, which writes escalations and notifications. Page loads (or a script) cause writes and extra load. | Leave the sweep to the scheduler only. | Code-read |
| P-21 | Low | `app/ai_features/coding.py:56-62`, `:89` | Evidence check is "the evidence string appears somewhere in a record line", so a one-word quote passes. The record is gathered across all branches for the patient, so a branch-A coder sees branch-B orders in the evidence. | Require the evidence to be a whole record line (exact match) and filter record lines by the claim's branch. | Code-read |
| P-22 | Info | New templates | CSP check passed: no inline `<script>`, no `on*=` handlers, no `javascript:` URLs in any new template; `voice.js` uses `textContent` only. One `style="--w:..."` attribute in `command.html:42` is allowed by the current `style-src 'unsafe-inline'`. | None now. When `style-src 'unsafe-inline'` is removed, set the meter width with a class or `data-` attribute and JS. | Code-read |

## Details

### P-01 Lab results released without lab review (High)

`enter_result` sets `status = 'Validated'` and `validated_by = 'auto-verify'` when the flag is `N` and the delta check passes (`app/diagnostics.py:119-125`). The route that calls it allows `LAB_ROLES = {"admin", "doctor", "frontdesk", "lab", "nurse"}`. Auto-verification is a recognised lab practice, but it relies on the value coming from an analyser or a trained technician. Here, a typing error at the front desk (for example 4.2 entered for a test where the true value was 6.2, both in range) goes straight to the patient. The patient app shows validated results (`app/routes/patient_app.py` `report_detail`), so the wrong value reaches the patient with the hospital's name on it.

Fix: result entry and auto-verification for `lab` (and `admin` for support) only; front desk and nurses can order and collect. Add a test that a front-desk POST to `/diagnostics/lab/{id}/result` is 403.

### P-02 and P-03 NEWS2 alerts can be silenced (High)

NEWS2 is the Royal College of Physicians' early-warning score. The published trigger levels are a total of 5 (urgent review) and 7 (emergency), or 3 in any single parameter. Two separate weaknesses let an alert disappear:

- **Who can acknowledge.** `VITALS_ROLES` includes front desk because `CLINICAL` includes front desk. Acknowledging is the only thing that stops escalation to admins and owner after 15 minutes.
- **Who can change thresholds.** `set_thresholds` accepts urgent up to 19 and emergency up to 20. A simple typing slip (15 instead of 5) would also turn most alerts off. Only `admin` can change them, but admin includes Tec Tha support staff, which conflicts with rule 2 (clinical decisions stay with doctors).

Verified run (scratch DB): vitals RR 22, SpO₂ 92 on oxygen, SBP 95, pulse 120, temperature 39.5, alert → NEWS2 12. With 19/20 thresholds: `alert = null`. With 5/7: `emergency`.

### P-04 Radiology reports and PCPNDT Form F (High)

The module correctly has no field for foetal sex and blocks "Performed" on an obstetric scan until Form F is recorded. But the record is a checkbox anyone in `RAD_ROLES` (admin, doctor, front desk) can tick, and the report is free text by the same roles. Under the PCPNDT Act 1994 and Rules, the sonologist must fill and sign Form F and the centre must keep it; disclosing the sex of a foetus is an offence. The software should make the safe path the only path: only the sonologist ticks Form F, with its serial number; only a radiologist or doctor reports; and the server refuses obstetric report text containing sex-disclosure words.

### P-06 Role names that do not exist (Medium)

`app/routes/diagnostics.py:11` says the roles "the auth module may add", but the auth module chose different names. Because Python sets accept any string, nothing fails, and tests pass. The effect is that the new `pharmacy` login cannot open its screen (`HOME["pharmacy"] = "/diagnostics"` makes it land on a 403 after login), so the counter will be run from a billing or front-desk login. This also means the Schedule register's `dispensed_by` will name a non-pharmacist.

### P-08 Two-step login enrolment (Medium)

Two-step login is only as strong as the moment the authenticator is added. Today it is added with the password session alone. For roles where the hospital makes 2FA compulsory (likely admin, owner, billing), the hospital should hand each user a one-time enrolment code in person, or an admin should approve the new device on the Account page.

### P-09 Public voice demo on hospital installs (Medium)

`_demo_mode()` is `TT_WHATSAPP_MODE == "simulator"`, and simulator is the default and the expected mode for the pilot. So a pilot server on the internet exposes `/voice/demo` to anyone. The demo is designed carefully (a typed number never sees a record or books under that number), but it still writes staff tasks and stores free text. Tie it to an explicit demo switch.

### What I checked and found sound

- **Sessions:** cookie holds user, `session_version`, CSRF token, issued-at and last-activity; absolute 8 h and idle 15 min limits are enforced in `_session_data`; `session_version` is bumped on logout, password change, deactivation, "sign out others" and admin 2FA reset; the refresh middleware rechecks `session_version` and `active` before reissuing.
- **TOTP:** RFC 6238, ±1 step, constant-time compare, replay of a used step refused (verified), recovery codes 48-bit random, stored hashed, single use; second-step cookie is signed, 5 minutes, bound to `session_version`, and has its own CSRF token; 5 failures per 15 min throttle.
- **OIDC:** authorization code with PKCE S256, `state` in a signed 10-minute cookie compared in constant time, `nonce` checked, issuer, audience and expiry checked, Google `email_verified` required, login matches on provider `sub` (not email), no account is ever created from SSO, linking requires the same logged-in user at callback, and SSO login still goes through two-step login when it is on.
- **Open redirects:** `safe_next` keeps `/` paths and refuses `//`; Starlette percent-encodes `\` (pilot review). Notification links are checked the same way.
- **Branch isolation (IDOR):** every new id route loads the row and checks the branch (`diagnostics._own`, `ai_labs._own_finding`, `vitals_ack`, coding `_own`), and notifications are filtered by `user_id`.
- **CSRF:** every new staff POST uses `require_post`; voice JSON uses an `X-CSRF-Token` header (patient session token, or a `SameSite=Strict` double-submit cookie on the demo).
- **Prompt injection:** the voice/receptionist path validates any model-chosen doctor and slot on the server, an unverified caller's context has no patient record, and draft replies are never sent without a person pressing Send.
- **AI Labs:** accept, dismiss, toggle and run are admin only and audited; owners can only read and ask for an explanation; AI explanations are rejected if they contain numbers not in the finding.
- **Secrets/config:** no new hard-coded secrets; OIDC client secrets come from the environment; SSO stays off until `TT_PUBLIC_URL` and both client id and secret are set; `Permissions-Policy` allows the microphone only for this site.

## Go-live checklist (Pro modules)

Must be done before real patient data enters the Pro modules:

- [ ] P-01: result entry and auto-verify limited to lab staff; test added.
- [ ] P-02: front desk removed from vitals and NEWS2 acknowledgement; emergency ack needs a doctor.
- [ ] P-03: NEWS2 thresholds can only be made stricter than RCP defaults; changes need doctor approval.
- [ ] P-04: Form F and radiology reporting restricted to sonologist/radiologist; Form F serial recorded; sex-disclosure word block on obstetric reports.
- [ ] P-06: role names fixed (`pharmacy`, `lab`), pharmacy can dispense, billing and front desk cannot, technicians cannot validate; a test checks every role name used in routes exists in `auth.ROLES`.
- [ ] P-09: `/voice/demo` off on every hospital install (explicit demo flag), `/voice/turn` rate-limited.
- [ ] AI stays off (`TT_AI` unset) until the hospital signs the data-flow approval and DPA (S-15, P-10).

Before Tec Tha staff get admin logins at the hospital:

- [ ] Two-step login required for `admin`, `owner` and `billing`, with in-person enrolment codes (P-08).
- [ ] Re-authentication for admin 2FA resets, policy changes and password resets (P-08).
- [ ] `TT_TOTP_KEY` set and TOTP secrets encrypted (P-12); database backups encrypted at rest.

Before turning on Google/Microsoft sign-in:

- [ ] `TT_PUBLIC_URL` is the HTTPS address; redirect URI registered exactly.
- [ ] `TT_OIDC_ALLOWED_DOMAINS` set to the hospital's domain; Microsoft tenant id set (not `organizations`) (P-16).

Configuration to confirm on the server:

- [ ] `TT_SESSION_SECRET` set (32+ characters) and backed up; note that changing it ends all sessions and invalidates recovery codes.
- [ ] `TT_STAFF_IDLE_MINUTES` left at 15 (or lower) on shared terminals; wall displays use a kiosk login (P-19).
- [ ] Retention periods agreed for `voice_turns`, `notifications`, `draft_replies` and `governance` logs (P-11).
- [ ] Re-run this review's scripts after fixes; QA sign-off per TEAM.md (Security and QA cannot be skipped).
