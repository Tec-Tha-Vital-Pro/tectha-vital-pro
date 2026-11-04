# Tec Tha Vital — Security & Privacy Review

Reviewer: Security & Privacy Engineer · Date: 2026-11-04 · Scope: everything under `app/` at the time of review.

**Method.** I read every module in `app/` and ran the test suite: 94 passed and 5 failed. The 5 failures are in `test_patient_app.py` and `test_ui.py`, which teammates are changing now. I confirmed each finding marked **Verified** with a script against a throwaway SQLite database (`TT_DB_PATH` pointed at a scratch file; the demo DB was not touched). Findings not marked Verified come straight from reading the code.

**In flux.** `app/routes/patient_app.py`, `app/routes/ui.py`, `app/templates/`, `app/static/` and `app/ai/` were being edited during the review. Line numbers in those files may already have moved. Search by function name if a line doesn't match.

**Plain-English summary for the hospital.** The basics are sound. Passwords are hashed properly, every staff form has CSRF protection, all database queries use parameters (no SQL injection found), pages escape their output, and the service workers never cache patient pages. Five problems must be fixed before any real patient data goes in:

1. Anyone can forge an admin login if the server runs with the default secret.
2. Staff at one branch can change the other branch's bills, claims, enquiries and tasks.
3. The patient app's "Pay" button marks a bill as paid without collecting any money.
4. Patient login codes can be read by staff on the patient screen.
5. The demo WhatsApp endpoints let anyone pretend to be any patient.

## Findings table

Severity counts: **Critical 1 · High 5 · Medium 9 · Low 7** (22 findings).

| ID | Sev | Status | Location | Scenario | Fix |
|---|---|---|---|---|---|
| S-01 | Critical | Fixed | `app/config.py:38`, `:49` | `TT_SESSION_SECRET` defaults to `dev-only-change-me`, and that is only refused in live mode. A pilot run in simulator mode (the default) lets anyone sign `{"u":1}` and become admin. It also lets anyone forge patient sessions and work out OTP hashes. **Verified**: a forged cookie opened `/settings` (200). | Refuse to start whenever the secret is the default or shorter than 32 bytes, in every mode except an explicit `TT_ENV=dev`. |
| S-02 | High | Fixed | `app/routes/ui.py:446` `billing_payment`, `:434` `billing_remind`, `:459` `billing_add_order`, `:491` `claim_stage` | A billing user bound to branch A posts the id of a branch-B bill or claim. **Verified**: A-user recorded ₹5,000 on a B bill and moved a B claim to *Denied*. | Load the row and refuse unless `user.branch_id` is empty or matches `row.branch_id`. Put this check in one helper and use it on every route that takes an id. |
| S-03 | High | Fixed | `app/routes/ui.py:289` `lead_status`, `:522` `task_done` | The same branch-isolation gap for enquiries and tasks. **Verified**: an A front-desk user set a B lead to *Lost* and closed a B complaint task, which hides it from B's manager. | Same branch check as S-02. Tasks with `branch_id NULL` need a rule: admin only, or visible to everyone. |
| S-04 | High | Fixed | `app/routes/patient_app.py:481-490` `pay_submit` | A logged-in patient clicks **Pay** and the full balance is recorded as a UPI payment. No gateway is called. Dues disappear from billing, the dashboard and reminders. **Verified**: bill 800/0 became 800/800, mode UPI. The page says "DEMO", but the route is live in every mode. | Remove it, or allow it only when `TT_WHATSAPP_MODE=simulator`. Real payments should be recorded only from a signed payment-gateway webhook (e.g. Razorpay `X-Razorpay-Signature`). |
| S-05 | High | Fixed | `app/messaging.py:43-46` (stores the full body), `app/routes/patient_app.py:222` (OTP send), `app/templates/patient.html:48-49`, `app/routes/ui.py:535` | OTP text such as "882523 is your … login code" is stored in plain text in `messages.body` and shown on the staff patient screen. Any CLINICAL user (including doctors, at any branch) can open it within 5 minutes and log in as the patient. **Verified** on `/patients/{id}`. The `/messages` thread is built from the same rows; its template is being changed. | Store a redacted body for `patient_otp` (e.g. `"[login code sent]"`) and never render it. Pass the real code only to the send call. |
| S-06 | High | Fixed | `app/routes/webhooks.py:141` (`if secret:`), `:170` `simulate-inbound` | In simulator mode (the default), `/webhooks/whatsapp` takes unsigned posts and `/webhooks/simulate-inbound` needs no login or CSRF. Anyone can send "STOP" to withdraw a patient's consent, "3" to cancel their appointment, or fake feedback. Any website can also do this through a visiting staff browser (cross-site form post). **Verified**: both endpoints withdrew consent (consent became 0). | Require a staff login and CSRF on `simulate-inbound`. Always require the signature on `/webhooks/whatsapp`, with an explicit `TT_ENV=dev` escape hatch only. |
| S-07 | Medium | Fixed | `app/auth.py:79` `authenticate`, `app/routes/ui.py:166` | No throttling or lockout on staff login. **Verified**: 30 wrong passwords in a row all returned 401, with no delay. Failures are audited but nothing acts on them. | Lock the account or IP after 5 failures for 15 min, with exponential backoff. Alert the admin on repeated failures. |
| S-08 | Medium | Fixed | `app/routes/patient_app.py:200-222` `login_phone` | Patient enumeration: an unregistered number gets "We could not find this number", so anyone can test whether a person is a patient (itself health information). The OTP limit is per phone only (3 per 10 min), so one attacker can trigger paid WhatsApp OTPs to every registered patient. **Verified** enumeration. | Show the same "If this number is registered, we sent a code" page in both cases. Add per-IP and global send limits. |
| S-09 | Medium | Fixed | `app/auth.py:97`, `app/routes/patient_app.py:187`, `:258` | `secure=` follows `request.url.scheme`. Behind a TLS-terminating proxy (nginx, Caddy, Cloudflare) the app sees `http`, so the session cookies go out without `Secure`. **Verified**: `Set-Cookie` had no `Secure`. | Always set `Secure` outside dev, or run uvicorn with `--proxy-headers --forwarded-allow-ips`. Use the `__Host-` cookie prefix. |
| S-10 | Medium | Fixed | `app/routes/ui.py` logout, `app/auth.py:90-110` | Sessions are stateless. Logout only deletes the cookie in that browser; a copied cookie keeps working for up to 8 h (30 days for patients, `patient_app.py:26`). Password reset and role change don't end sessions either. **Verified**: a replay after logout returned 200. | Add `session_version` (or a sessions table) to users and patients, checked in `current_user` and bumped on logout, password change and deactivation. Cut the patient lifetime to 7 days or less. |
| S-11 | Medium | Fixed | `app/main.py:26` (no middleware) | No security headers at all: no CSP, no X-Frame-Options/`frame-ancestors`, no HSTS, no `nosniff`, no Referrer-Policy. **Verified** on the `/login` response. Staff screens can be framed, which enables clickjacking of "record payment" and "consent" buttons. | Add a middleware with `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'` (move the one inline `<script>` in `base.html:21` into `app.js`). Also add HSTS, `X-Content-Type-Options: nosniff` and `Referrer-Policy: same-origin`. |
| S-12 | Medium | Fixed | `app/routes/ui.py:393` `patient_page`, `:378` `patients_page`, `:408` `patient_consent` | Patient search and profile ignore branch. A branch-A doctor or front-desk user sees branch-B bills, messages and feedback. One ID across branches is by design, but rule 5 says staff see only what their branch allows. **Verified**: an A front-desk user saw a B bill. | Show demographics across branches, but filter bills, appointments, messages and feedback to the user's branch unless the user is unbound. Log every view of a patient record. |
| S-13 | Medium | Fixed | `app/routes/ui.py:535` `messages_page` | The messages inbox loads the last 500 messages from all branches for any FRONT user, whatever their branch, including the owner's daily revenue report to `TT_OWNER_PHONE`. | Scope by patient branch, or by `leads.branch_id`. Hide `owner_daily_report` and `patient_otp` from non-admins. |
| S-14 | Medium | Fixed | `app/routes/ui.py:626-629` `import_run` | No upload size limit: `await file.read()` loads the whole file into memory. **Verified**: a 2.4 MB, 200k-row CSV was accepted. A branch-bound admin can also import bills for any branch. | Cap size (e.g. 5 MB) and rows (e.g. 20k). Read in chunks and return 413 above the cap. Enforce the branch on imported bills. |
| S-15 | Medium | Open | `app/ai/receptionist.py:203-212`, `app/ai/insights.py:61-69` | When `TT_AI=on`, patient first name, TT-ID, open balance, upcoming appointment and the last 10 WhatsApp messages go to the Anthropic API, outside India. That conflicts with "India hosting" (problem 12) and needs DPDP notice and processor terms. | Keep AI off for the pilot until the hospital has signed off on the data flow and a DPA is in place. Send the minimum (no balance, no TT-ID). Record the decision in the compliance checklist. |
| S-16 | Low | Fixed | `app/routes/webhooks.py:120`, `app/config.py:35` | The webhook verify token defaults to the public value `tectha-verify` and is compared with `==`. **Verified**: the default token echoed the challenge. The impact is small: it only proves ownership to Meta. | Require `TT_WHATSAPP_VERIFY_TOKEN` in live mode and compare with `hmac.compare_digest`. |
| S-17 | Low | Open (500 fixed) | `app/routes/api.py:20`, `app/routes/webhooks.py:195` | `hmac.compare_digest` on `str` raises `TypeError` for non-ASCII input, so a crafted `X-API-Key` gives a 500 instead of 401. **Verified** (500). The compare itself is timing-safe. Separately, one shared key has full write access to all branches, with no rate limit and no per-integration identity. | Compare `.encode()` bytes. Issue one key per integration, with a branch scope, stored hashed, and audit as `api:<name>`. |
| S-18 | Low | Fixed | `app/main.py:26` | `/docs`, `/redoc` and `/openapi.json` are public. **Verified** (200). They list every endpoint and field. | `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)` outside dev. |
| S-19 | Low | Fixed | `app/routes/ui.py` `render`, `patient_app.py` `_page` | No `Cache-Control` on pages with patient data. **Verified**: none set. On shared front-desk PCs and family phones, the browser's back/forward cache and disk cache can show PHI after logout. The service workers are fine: they cache only `/static/`. | Send `Cache-Control: no-store` on every HTML response except `/static`. |
| S-20 | Low | Accepted | `app/integrations/csv_import.py:37-46`, bill items | Imported names and items are stored as-is. **Verified**: `=HYPERLINK("http://x")` was stored as a patient name. Not exploitable today because there is no CSV export, but any future export or spreadsheet sync will carry formula injection. | On any export, prefix cells that start with `= + - @ \t \r` with `'`. Optionally reject them on import. |
| S-21 | Low | Fixed | `app/auth.py:79-84` | User enumeration by timing: PBKDF2 (200k iterations) runs only when the username exists, so unknown usernames answer noticeably faster. | Verify against a dummy hash when the user is missing. |
| S-22 | Low | Open | `requirements.txt` | All dependencies are `>=` and unpinned, so a new release (or a hijacked package) installs on the next deploy. `pytest` sits in runtime requirements. There is no `pip-audit` step. | Pin exact versions with hashes (`pip-compile --generate-hashes`), split out dev requirements, and run `pip-audit` in CI. |

### Checked and found OK

- **SQL injection.** Every value is bound with `?`. The f-strings in `metrics.py`, `ui.py`, `automations.py`, `receptionist.py` and `patient_app.py` only add fixed column names or fixed clauses.
- **XSS.** Jinja2 autoescape is on for `.html`. The only `|safe` is the constant icon-path map in `_macros.html:35`. The SVG chart takes only numbers, plus branch names that are escaped. `?msg`/`?err` are escaped, so the worst case is phishing-style text in a toast (see the checklist).
- **Open redirect on `/login?next=`.** `//evil.com` is rejected. `/\evil.com` is percent-encoded by Starlette into `/%5Cevil.com` (verified), so it stays on the site. `_go` and `back` only use hard-coded paths, and `back=` in `appointment_action` is allow-listed.
- **CSRF.** Every staff POST goes through `auth.require_post`, and patient POSTs go through `_me_post`/`_check_pre`. The exception is `/webhooks/simulate-inbound` (S-06). Staff `/login` has no CSRF token (login CSRF, minor; SameSite=Lax helps).
- **Password hashing.** PBKDF2-SHA256 with 200k iterations, a 16-byte salt and constant-time compare. Minimum length is 8 characters; raise it to 12 for admins.
- **OTP.** 6 digits from `secrets`, HMAC-hashed, 5-minute expiry, 5 tries per code, single use. That allows about 15 guesses per number per 10 minutes, so the brute-force risk is low (S-08 covers the remaining gaps).
- **Service workers** (`static/sw.js`, `static/patient-sw.js`) cache `/static/` only.
- **Error pages.** No debug mode, and an unhandled error returns a plain "Internal Server Error". A few paths do return a 500 instead of a friendly message: an unknown bill on `/billing/{id}/remind`, or a non-numeric `doctor_id` on `/my/book`.
- **Audit log** holds full phone numbers in some details (`patients.py` create, `missed_call`). That is acceptable for an access-controlled audit trail. The OTP code itself is not written to the audit log.

## Fix status (04 Nov 2026, Backend & Integration Engineer)

**Fixed 18 · Open 3 · Accepted 1.** Each fix has a regression test, mostly in `tests/test_security.py`. Full suite: 149 passed. E2E on port 8030: 22 of 23 passed (see `docs/BUGS.md`). A Playwright run on `/`, `/messages`, `/billing`, `/claims`, `/settings`, `/appointments` and the patient app `/my/` found no CSP violations.

| ID | What changed |
|---|---|
| S-01, S-05, S-06, S-04 | Fixed earlier by the architect, and checked again for this review. `TT_SESSION_SECRET` is a random per-install secret of 32+ characters. OTP text is not stored in live mode. `/webhooks/whatsapp` always needs a signature. `simulate-inbound` needs a login and CSRF. Patient "Pay" works in simulator mode only. |
| S-02, S-03 | All id routes in `app/routes/ui.py` load their record through one helper, `_own()`. It returns 404 when the record is missing and when it belongs to another branch, so the two cases look the same. This covers leads, appointments, bills (payment and reminder), orders, claims and tasks. Tasks with no branch, such as emergency alerts and unrouted WhatsApp replies, form a shared queue that every branch sees. **Head of Product to confirm.** |
| S-07, S-21 | Staff login allows 5 failures per username and IP in 15 minutes. After that it returns 429 with a friendly message and writes `login_throttled` to the audit log. When the username doesn't exist, the app still checks a dummy hash, so the response time doesn't reveal which usernames exist. |
| S-08 | Known and unknown numbers get the same "If this number is registered…" page. Both also get the same limits and the same "wrong code" replies; for an unknown number the app stores a code that nobody knows and sends nothing. OTP sends are capped at 10 per hour per IP and 300 per hour in total. |
| S-09 | Staff and patient cookies get `Secure` when the request is HTTPS. `X-Forwarded-Proto` and `X-Forwarded-For` are trusted only when `TT_BEHIND_PROXY=1`. |
| S-10 | New `session_version` column on users and patients, added by an idempotent migration in `db.init_db`. The version goes in the cookie. Staff logout, password reset and deactivation increase it, and so does patient logout. Patient sessions now last 7 days instead of 30. |
| S-11, S-18, S-19 | `app/security.py` middleware adds: CSP (`script-src 'self'`, Google Fonts allowed, `frame-ancestors 'none'`), `nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, a Permissions-Policy, HSTS on HTTPS only, and `Cache-Control: no-store` on HTML pages. The inline sidebar script moved to `/static/side-init.js`. `style-src` keeps `'unsafe-inline'` because of two `style=""` attributes on the dashboard and the `<style>` block in `offline.html`. `/docs`, `/redoc` and `/openapi.json` are served only when `TT_ENV=dev`. |
| S-12 | On the patient profile, branch-bound staff see only their own branch's visits, bills, feedback and messages. Name, TT-ID and phone stay shared across branches. Every profile view is audited (`view`). |
| S-13 | On Messages, branch-bound staff see only conversations of patients with activity in their branch, plus their branch's enquiries. Only admins see `owner_daily_report` and `patient_otp` messages. |
| S-14 | Uploads are limited to 5 MB (HTTP 413, checked against Content-Length before parsing) and 20,000 rows. A file with missing columns now shows an error instead of a 500. A branch-bound admin can import bills for their own branch only. |
| S-16 | The verify token is compared with `compare_digest`. Live mode refuses to start with the default token. |
| S-17 | All key, CSRF and signature checks compare bytes, so non-ASCII input returns 401 or 403 instead of 500. **Still open:** one key per integration, with a branch scope. |
| S-20 | Accepted for now: no CSV or Excel export exists. Any new export must escape cells that start with `= + - @ \t \r`. |
| S-15 | Open (policy). AI stays off by default (`TT_AI=off`). Turning it on needs a DPA and the hospital's sign-off. Sending less data (no balance, no TT-ID) is for the AI Engineer to decide, because the receptionist prompt uses the balance. |
| S-22 | Open (DevOps): pin dependencies with hashes, split out dev requirements, run `pip-audit`. |

New Lows found while fixing, left for later:
- In live mode, sending the OTP adds a call to Meta for known numbers only, so response time could still show whether a number is registered. Fix: send the OTP from a background task.
- WhatsApp enquiries arrive with no branch, so branch-bound front desk staff don't see them on Enquiries or Messages until someone assigns a branch. This was already true of the Enquiries list. It needs a routing rule: a product decision.
- The login rate limit is per username and IP. A spread-out guessing attack from many IPs isn't covered by an account lockout yet. Admins are not yet alerted about repeated failures.

## Details

**S-01 Default session secret.** One secret signs staff cookies (`salt="tt-session"`), patient cookies and the OTP HMAC. `config.load()` rejects the default only when `whatsapp_mode == "live"`, but the pilot plan (PRODUCT_KNOWLEDGE §8) can easily start in simulator mode on a VPS. Exploit: `URLSafeTimedSerializer("dev-only-change-me", salt="tt-session").dumps({"u": 1, "c": "x"})` gives a cookie that is user 1 (the first admin) with CSRF token `x`, so the attacker can also make state-changing POSTs. Fix: fail closed. Also use separate derived keys for the staff session, patient session and OTP.

**S-02 / S-03 Branch IDOR.** List pages are scoped correctly with `_scope()`. Action routes take a raw id and never compare branches. Only `appointment_book` and `appointment_status` do it. Add `_own_branch(user, table, id)`, which loads the row and raises `Forbidden` on a mismatch. Use it in `billing_payment`, `billing_remind`, `billing_add_order`, `claim_stage`, `lead_status` and `task_done`. Add a test per route: an A-user tries a B-id and must get 403.

**S-04 Self-payment.** `pay_submit` calls `billing.record_payment(bill_id, bal, "UPI")` with no proof that money moved. A patient, or anyone holding their session, can wipe their dues. Collections figures in the owner report would then be false, which breaks rule 7 (never invent numbers).

**S-05 OTP shown to staff.** `messaging.send` always stores `body`, and the login code is the first 6 characters. A doctor at either branch can open `/patients/{id}`, read the code and log into the patient's app within 5 minutes. From there they can see bills and reports, cancel appointments, switch consent and "pay" bills (S-04). The simulator hint ("your code is on the staff Messages screen") shows this is intended for demos. Gate it on simulator mode and redact in live mode.

**S-06 Unsigned inbound in simulator mode.** `receive()` checks the signature only `if secret:`, and `config` requires the secret only in live mode. `simulate_inbound` accepts a form post with no session. Because it accepts `application/x-www-form-urlencoded`, any web page can post to it cross-site (SameSite doesn't apply because no cookie is needed). Effects include consent withdrawn (`STOP`), appointments cancelled (`3` after a reminder), feedback faked and leads created.

**S-07 / S-21 Staff login.** No limiter exists. With 8-character passwords and an internet-facing VPS, online guessing is practical. Use a simple SQLite table keyed by username and IP.

**S-08 Patient enumeration and OTP cost.** The `unknown` step tells an attacker that a number is not a patient, and the `code` step tells them it is. Sending OTP to every registered number costs the hospital per message (WhatsApp authentication template pricing) and spams patients.

**S-09 / S-10 / S-11 / S-19 Transport and session hygiene.** These are standard hardening steps, all missing today. The inline script in `base.html:21` (sidebar state) is the only thing blocking a strict CSP.

**S-12 / S-13 Cross-branch PHI.** `patient_page` returns every appointment, bill, message and feedback item. `messages_page` returns the newest 500 messages from all branches. Decide with the Domain Lead which fields are shared across branches (name, TT-ID, phone) and which are branch-private (bills, messages). Then enforce that in SQL.

**S-15 AI data transfer.** AI is off by default (`TT_AI=off`). It is good that `patient_otp` and `owner_daily_report` are excluded from model history (`EXCLUDED_TEMPLATES`). Inbound patient text is passed to the model inside `<patient_message>`. Prompt injection there is contained, because bookings are validated in code against real free slots and replies go through `safe_reply`. The remaining issue is the data leaving India, which is a policy decision.

## Go-live hardening checklist

**Must fix before real patient data (blockers)**
- [x] S-01: refuse to start with the default or a short `TT_SESSION_SECRET` in any non-dev mode. Generate it with `python -c "import secrets;print(secrets.token_urlsafe(48))"`.
- [x] S-02/S-03: branch check on every id-taking POST, with tests.
- [x] S-04: remove or simulator-gate `/my/bills/{id}/pay`.
- [x] S-05: redact OTP bodies in storage and on screen.
- [x] S-06: login and CSRF on `simulate-inbound`; signature always required on `/webhooks/whatsapp`; set `TT_WHATSAPP_APP_SECRET` and `TT_WHATSAPP_VERIFY_TOKEN`.

**Before the pilot opens to staff**
- [x] Login rate limit and lockout for staff (S-07) and per-IP OTP limits plus a uniform response (S-08).
- [ ] Run behind HTTPS (Caddy or nginx), with `--proxy-headers`, `Secure` cookies (S-09) and HSTS.
- [x] Security-header middleware: CSP, frame-ancestors, nosniff, Referrer-Policy (S-11). Add `Cache-Control: no-store` on HTML pages (S-19).
- [x] Server-side session revocation; patient session 7 days or less (S-10).
- [x] Branch scoping on the patient profile and messages (S-12, S-13).
- [x] Upload cap of 5 MB / 20k rows (S-14).
- [x] Disable `/docs` and `/openapi.json` (S-18).
- [ ] Pin dependencies with hashes, run `pip-audit` (S-22), and separate dev dependencies.
- [ ] Per-integration API keys with branch scope; bytes-safe compare (S-17).

**Operations and privacy**
- [ ] Unique login per staff member (rule 5). Admin passwords at least 12 characters. Remove unused accounts.
- [ ] Audit log: also record *views* of patient profiles. Keep the log append-only (no UI delete). Back it up with the database.
- [ ] Encrypted nightly backups of `data/tectha.db` to storage in India, with a tested restore. File permissions `600`, owned by the service user.
- [ ] `TT_AI` stays `off` until a DPA and the hospital's sign-off on cross-border processing are recorded (S-15).
- [ ] Before any CSV or Excel export is added, escape formula cells (S-20).
- [ ] Ask for a short-text check on `?msg=`/`?err=`, or switch to server-side flash messages, so crafted links can't show fake notices on the hospital's own domain.
- [ ] Re-run this review after the patient-app, UI and AI changes now in progress are merged.
