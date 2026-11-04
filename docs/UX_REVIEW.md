# UX and accessibility review: staff app and patient app (/my)

Reviewed 4 Nov 2026 against the running app (seeded demo data, simulator mode), Chromium at 1440x900 and 390x844, light and dark. WCAG target: 2.1 AA. The design standard is the one in `.claude/agents/product-designer.md`: big tap targets, plain words, status shown by colour and shape, and every screen answers "what should I do next?".

Screenshots are in `/tmp/claude-0/-home-user/5f540028-1c92-5b5c-889b-342c486a270d/scratchpad/ux/`, named `<desk|phone>-<light|dark>_<staff|pt>_<screen>.png`. Phone viewport crops are in `vp-*.png`, and the side-by-side sets are in `m1`–`m3.png` (staff) and `p1`–`p5.png` (patient). The automated results (contrast, targets, labels, landmarks, focus walk) are in `.../scratchpad/audit.json`.

## Overall verdict: PASS WITH ISSUES. Fix the 3 blockers before the pilot.

The visual design is well made and doesn't look templated. On desktop the staff app has a clear "Needs attention" hierarchy. The pills use shape as well as colour, the dark theme holds AA, and there's a skip link, proper landmarks, one `h1` per page and visible focus rings. Dialogs move focus to the first field, close on Esc and give focus back. `prefers-reduced-motion` is honoured, and no screen scrolls sideways at 390px. The patient app is better still: the appointment "ticket", the 4-step booking flow, the 48px buttons and the plain, kind copy ("We are sorry your visit was not good. Our branch manager will call you within a day.") are very good.

The problems are in task flow more than in looks:

- The front desk has to re-type data. A typo wipes the whole booking form, and turning an enquiry into an appointment means typing the name and number again.
- The billing desk has no way to find the patient standing at the counter.
- Selects and the date field save data the moment they change.
- On phones, the staff tables turn into very tall label/value cards.
- The patient app is English only.

Counts: **Blocker 3 · Major 18 · Minor 17 · Polish 6**

Note: the product is now called **Tec Tha HP**, but many screens still say "Care Connect" (M18).

---

## Blocker (fix before the pilot)

### B1. Booking a walk-in: any error closes the form and loses everything typed
- **Screen:** Appointments → Book appointment (also New enquiry, Record payment, Add staff login).
- **What's wrong:** `POST /appointments/book` answers a bad mobile number with `back("/appointments", err=...)`. The page reloads, the dialog closes, and the name, doctor, time and consent are all lost. The toast shows a developer message: `Not a valid Indian mobile number: '12345'` (screenshot `desk-light_staff_book_error.png`). The phone field has no `pattern`, `maxlength` or `aria-describedby` hint, so the browser can't catch the mistake first.
- **Why it matters:** "No re-typing" is the front desk's stated need (PRODUCT_KNOWLEDGE section 5). With a queue at the counter, retyping five fields for one wrong digit is exactly what makes staff go back to paper.
- **Fix:**
  1. On a validation error, re-render `appointments.html` with status 400, the submitted values, and `open_dialog="book"`. Add `{% if open_dialog == 'book' %}open{% endif %}` to `<dialog id="book">`, or call `showModal()` from `app.js` when `[data-open-on-load]` is present.
  2. Show the error under the field: `<p class="field-err" id="a-phone-err">Enter a 10-digit mobile number, for example 98765 43210.</p>`, plus `aria-invalid="true" aria-describedby="a-phone-err"` on `#a-phone`. The patient app already does this in `patient/login.html`.
  3. Add `inputmode="numeric" pattern="[0-9 +]{10,15}" maxlength="15" autocomplete="tel-national"` to `#a-phone` and `#l-phone`.
  4. Rewrite the `ValueError` text from `patients.normalize_phone` as plain English with no quoted raw input. This is owned by the backend.

### B2. Billing desk can't find the patient at the counter
- **Screen:** Billing (role `billing`).
- **What's wrong:** `can_search` is `role in CLINICAL`, so billing users get no global search (`role_bill1.png`). `billing.html` has no search or filter either. To collect a due, the cashier has to scan every pending due by eye. The demo already has 19, and a real branch will have hundreds.
- **Why it matters:** "Billing desk collects a due" is a top task. The patient is standing there, and the cashier needs their balance in under 5 seconds.
- **Fix:** Add a search box at the top of `billing.html`, above "Pending dues": `<form class="inline-filter page-search" role="search"><label for="b-q" class="sr-only">Find a due</label><input id="b-q" name="q" type="search" placeholder="Name, mobile, TT- ID or bill no.">`. Filter `dues` and `unbilled` by name, last 5+ digits of the mobile, uid or bill_no in the `/billing` handler, as `patients_page` already does. Make an exact single match open its "Record payment" dialog straight away. Also show the global search to `BILLING` users (`can_search`), pointing them at `/billing?q=`.

### B3. Selects and the date field save the moment they change (WCAG 3.2.2 On Input, Level A)
- **Screens:** Enquiries status (`select.status-sel[data-autosubmit]`), the branch switcher (`#top-branch`), the source filter (`#f-source`) and the appointment date (`#a-day`).
- **What's wrong:** `app.js` submits the form on every `change`. In Chromium on Windows, pressing Up/Down on a focused, closed select changes its value and fires `change`, so a keyboard user moving through a lead's status saves "Contacted", then "Booked", then "Converted". Each one is written to the audit log. Typing a date into `#a-day` reloads the page part-way through the date.
- **Why it matters:** It changes data by accident for keyboard and switch users, and it makes the audit log wrong (a NABH/DPDP record).
- **Fix:** Keep auto-submit only for pointer-driven changes. In `app.js`, track the last input type: set `lastPointer = true` on `pointerdown`/`mousedown`, set it to `false` on `keydown`, and submit on `change` only when `lastPointer` is true. For keyboard users, always render the "Save"/"Show" button outside `<noscript>`, visually small, shown on `:focus-within`. For `#a-day`, submit on `blur` or Enter, not on `change`. Lead status changes should also show an "Undo" link in the toast.

---

## Major

### M1. Phone: the "Record payment" dialog is laid out inside a table cell
- **Screen:** Billing → Record payment at 390px (`m1.png`, 4th panel).
- **Wrong:** The `<dialog id="pay-…">` sits inside `td.actions`. Under `@media (max-width:767px)`, `.cards td{display:flex;justify-content:space-between;text-align:right}` cascades into the dialog. The labels "Amount received (₹)" and "Mode" end up right-aligned, the amount box is narrow, and "Save payment" isn't full width.
- **Why:** This is the money moment for the billing desk on a phone, and it looks broken.
- **Fix:** Move each payment dialog out of the table. Render one `<dialog id="pay">` after `</section>` and fill it from `data-*` attributes on the button, or render the dialogs in a second `{% for d in dues %}` loop after the table. A quick stopgap: `.cards td dialog, .cards td dialog *{text-align:left}` and `.cards td dialog .stack{align-items:stretch}`.

### M2. Appointment status: Booked, Confirmed and Visited look the same
- **Screen:** Appointments (`desk-light_staff_appointments.png`).
- **Wrong:** In `_macros.html` `status_pill`, `Booked`, `Confirmed` and `Visited` all map to `p-ok`, the green tick.
- **Why:** The way to stop no-shows is to phone the patients who haven't confirmed. Staff can't see who they are.
- **Fix:** Use `'Booked':'p-warn'` with the label "Not confirmed", `'Confirmed':'p-ok'` and `'Visited':'p-acc'` with the label "Seen". Add a filter chip row above the table (All · Not confirmed · Still to come · Seen) using `qs()`, as on Enquiries.

### M3. No-show and Cancel are one click, with no confirmation or undo (staff and patient)
- **Screens:** Appointments row actions; patient Home "Cancel visit"; My visits "Cancel".
- **Wrong:** Each is a plain POST button. The patient's "Cancel visit" sits 40px from "Change time".
- **Why:** A mis-tap cancels a real visit. For patients with low digital literacy this is a real risk, and they can't put it back.
- **Fix:** For staff, keep the one click but add an "Undo" button to the toast that posts the previous status back (within 30 seconds). For patients, make cancel go to a confirm screen first: `GET /my/appointments/{id}/cancel` shows "Cancel your visit with Dr. S. Menon on Thu 5 Nov?" with "Yes, cancel" and "Keep my visit" (primary). Rename My visits "Cancel" to "Cancel visit".

### M4. Phone: staff tables become very tall label/value cards
- **Screens:** Appointments, Enquiries, Billing, Patients at 390px (`phone-light_staff_appointments.png` is 20,588px tall for 29 visits; `m1.png`).
- **Wrong:** The generic `.cards td::before{content:attr(data-label)}` gives every field its own row. That's about 300px per appointment, so 2.5 visits fit on screen. `justify-content:space-between` also pushes the two reminder chips, and doctor name and specialty, to opposite edges. This is the one place that looks templated.
- **Why:** The doctor or front desk can't take in "who's next" at a glance.
- **Fix:** Write a phone layout per screen instead of the generic one. For `table.appt` on phone, use one line: token, time, patient name and uid. The second line holds doctor · branch with a status pill, and the actions go in a final row. Hide the reminders row on phone, or show it as a single ✓/– icon. In CSS: `.cards td{display:block}` for the doctor and reminder cells, and drop the `::before` labels where the content explains itself (time, doctor). Aim for 3 to 4 visits per screen.

### M5. Turning an enquiry into an appointment means typing it all again; enquiry rows have no actions
- **Screen:** Enquiries.
- **Wrong:** A row has only a status select. The name is a `<span class="name-link">`, not a link. To book, staff open Appointments → Book and type the name and mobile again.
- **Why:** This is the main flow for problem #2 (enquiries not followed up), and it breaks "no re-typing".
- **Fix:** Add a row action, `<a class="btn sm primary" href="/appointments?book=1&name=…&phone=…">Book</a>`, and make the appointments page open `#book` with those values filled in. Add `<a class="btn sm" href="tel:+{{ l.phone }}">Call</a>` and a "WhatsApp" link to `/messages?phone=`. Make the name link to the patient profile once `patient_id` is set.

### M6. Missed-call tasks can't be called from the phone
- **Screens:** Tasks; Dashboard "Call back".
- **Wrong:** The task title shows a raw `+918085874951`, not a link. The dashboard "Call back" goes to the generic `/tasks` list.
- **Why:** The 15-minute callback target depends on one tap from the front-desk phone.
- **Fix:** In `tasks.html`, when the task has a phone, render `<a class="btn sm primary" href="tel:+91…">{{ icon('phone') }} Call</a>` before "Done". Format the number as `+91 80858 74951`, the same format as the other screens. Point the dashboard links at `/tasks#missed-calls` and `#complaints` (add `id`s to the `section.sec` groups).

### M7. Staff can't reply to a patient from Messages
- **Screen:** Messages.
- **Wrong:** The only composer is "Simulate a patient message", and only in simulator mode. In live mode the screen is read-only.
- **Why:** "Fast replies" is the front desk's main need, and problem #2 in the product brief.
- **Fix:** Add a staff reply composer in both modes: `POST /messages/reply` with a consent and 24-hour-window check (backend). Add 3 to 4 quick replies as chips (the `.quick` CSS already exists): "Your appointment is confirmed", "Please share a convenient time", "Your report is ready". Keep the simulator as a separate, clearly labelled block under it.

### M8. Patient login codes are shown in staff Messages
- **Screen:** Messages list and thread (`desk-dark_staff_messages_phone_….png`): "You: 740091 is your Your Hospital login code".
- **Wrong:** Anyone who can read the thread can log in as that patient. The parallel backend change (`ADMIN_ONLY_TEMPLATES`) now limits this to admins, but admins still see working codes.
- **Fix:** Don't store or show the code. Save the message body as `"Login code sent (hidden)"`, or mask it when rendering: `{{ m.body|replace(code, '••••••') }}` for `template == 'patient_otp'`. Leave the patient app's demo hint as it is. This belongs to the backend engineer.

### M9. Claims past the IRDAI limit aren't marked, and the dashboard says 0
- **Screens:** Claims, Dashboard (`desk-light_staff_claims.png`).
- **Wrong:** Divya Singh has been at "Pre-auth requested" for 1 h 38 m against a 1 h limit, and Divya Bhat at "Final bill sent" for 4 h 33 m against 3 h. Neither card is red, and the dashboard reads "Insurance claims past the TPA time limit: 0". `stuck` is true only once the automation has created a `claim_stuck` task, so any scheduler gap hides it.
- **Why:** The owner's morning picture is wrong about money, and the page promises "Cards past those limits are marked". It also goes against rule 4, no silent failures.
- **Fix:** Work out `stuck` in the view from `stage_since` and the limit (`PreAuthRequested` 60 min, `FinalSent` 180 min), not from whether a task exists. Use the same rule in `metrics.attention`. Show "Over by 38 min" in `.bad-text` on the card.

### M10. Owner's dashboard buttons may lead to "no access"
- **Screen:** Dashboard as `owner` (role added in the parallel backend change; not run here because the seeded schema didn't allow it yet).
- **Wrong:** "Open tasks", "Call back" and "See complaints" link to `/tasks`, but `NAV` gives Tasks to `STAFF - {"doctor","owner"}`.
- **Fix:** Hide those buttons for the owner, `{% if user.role != 'owner' %}`, or swap them for read-only counts. Re-test once the schema migration lands.

### M11. Unknown staff URLs show a raw JSON page
- **Screen:** Any mistyped staff URL, for example `/nope`.
- **Wrong:** It returns a white page reading `{"detail":"Not Found"}`, with no navigation, no `lang` and no `main`. Patient 404s are handled well; staff ones aren't.
- **Fix:** Register a 404 `exception_handler` in `app/main.py` for non-API paths that renders `error.html` with "Page not found". Add "Check the address, or go back to your start screen."

### M12. Patient app is English only
- **Screens:** All `/my` screens.
- **Wrong:** `lang="en"`, no language switch, and no Hindi even on the key moments (login, confirm visit, pay).
- **Why:** These patients have low digital literacy, and rule 6 asks for "local languages where possible". The OTP login is the first screen they meet.
- **Fix:** Add a language toggle (English / हिन्दी) to `patient/login.html` and Profile, stored in a cookie. Move the strings into a dictionary, starting with the 25 or so key strings: "Get code on WhatsApp" → "WhatsApp पर कोड पाएं", "Yes, I'll be there" → "हाँ, मैं आऊँगा/आऊँगी", "Pay ₹X" → "₹X भुगतान करें", "Book a visit" → "डॉक्टर से मिलने का समय लें". Set `<html lang="hi">` when Hindi is chosen. Have a native speaker review the strings. Don't machine-translate.

### M13. Patient bills: the amount due isn't the headline
- **Screen:** `/my/bills` (`p3.png`, 2nd panel).
- **Wrong:** Each row leads with the bill total in large type. The amount due is a small pill, and because the list is newest first, the one unpaid bill sits at the bottom.
- **Fix:** Sort unpaid bills first. For an unpaid row, lead with `₹26,300 to pay` and put the total in the sub-line. Add a "Pay" button on the row so the patient doesn't need bill → pay → pay. Sort with `ORDER BY (total>paid) DESC, created_at DESC` in `_bills()`.

### M14. Patient help has nothing to tap
- **Screen:** Home footer: "Questions? Message Your Hospital on WhatsApp…".
- **Wrong:** It's plain text. There's no WhatsApp link and no phone number, here or on the "We could not find this number" login step.
- **Fix:** Make it `<a class="btn block" href="https://wa.me/{{ hospital_whatsapp }}">Message us on WhatsApp</a>` plus `<a href="tel:…">Call the front desk</a>`, using new settings values. Use the same on the login "unknown number" step and on the bill-unpaid notice.

### M15. Touch targets under 44px on phone (design standard; 2.5.8 needs at least 24px)
- **Screens:** Staff at 390px. Measured: the consent checkbox `#a-consent` is 13x18 (the DPDP consent control!), the import radios are 18x18, `a.crumb` "Patients" is 69x20, "Open conversation" on the patient profile is 116x20, "Chase dues" is 73x16, `select.status-sel` is 32 high, `.chip` and `#f-source` are 34, `.btn.sm` (Visited / No-show / Cancel / Withdraw consent) is 38, `.icon-btn` (dialog close, previous/next day, chat back) is 40, and `summary.avatar-btn` and `a.brand-compact` are 36. In the patient app, `button.switch` is 58x34 and `.btn.sm` "Rate visit" is 40.
- **Fix:** In the `@media (max-width:767px)` block of `style.css`:
  - `.btn.sm,.chip,.status-sel,.filterbar select,.row-form select{min-height:44px!important}`
  - `.icon-btn{width:44px;height:44px}`
  - `.avatar{width:44px;height:44px}`
  - `label.check{min-height:44px;align-items:center}`
  - `label.check input{width:22px;height:22px}`
  - `.crumb,.sec-head a{min-height:44px;display:inline-flex;align-items:center}`

  In `patient.css`: `.switch{height:44px;width:72px}` (move the knob 28px) and `.btn.sm{min-height:44px}`.

### M16. Enquiries loads 300 rows with no paging; tables scroll inside themselves
- **Screens:** Enquiries (300 rows, a 20,322px page on desktop); Appointments and Patients (`.tbl-wrap{max-height:70vh;overflow:auto}`).
- **Wrong:** Enquiries opens on "All", including Lost and Converted. On Appointments and Patients the table scrolls inside a box with the page footer right under it, so the page looks finished at row 9 of 28.
- **Fix:** Open Enquiries on "Needs action" (New + Contacted) by default and page at 50 rows with a "Show more" link. Remove `max-height:70vh` from `.tbl-wrap.cards` on desktop. The sticky `th` still works with page scroll if `.tbl-wrap{overflow:visible}` and `th{top:var(--top-h)}`.

### M17. Token numbers repeat in the "All branches" view, and don't follow time order
- **Screen:** Appointments, all branches.
- **Wrong:** Tokens are counted per branch per day, so the merged list shows token 2 twice and token 3 three times. They're given in booking order, so a 13:00 walk-in gets token 5 after a 13:15 token 3. Some booked visits show "—".
- **Fix:** In the all-branches view, show the token with its branch, as `A-2` / `B-2` (the `.branch-code` style is already in `style.css`). Label the column "Token (per branch)". Show "—" only for cancelled visits, and say "At check-in" otherwise, as the patient app does.

### M18. Screens still show the old product name "Care Connect" (product is now "Tec Tha HP")
- **Screens:** Every staff screen, the staff login, the patient app header, patient Profile, the offline page, and the installed app name.
- **Wrong:** These visible strings still say "Care Connect":
  - `templates/base.html` line 6 (`<title>` default "Tec Tha Care Connect"), line 31 (sidebar `<small>Care Connect</small>`), line 57 (top bar "Tec Tha Care Connect") and line 95 (footer "Tec Tha Care Connect · every message and change is recorded…").
  - `templates/login.html` line 6 (`aria-label="About Tec Tha Care Connect"`, which screen readers say aloud) and line 9 (brand `<small>Care Connect</small>`).
  - `templates/patient/base.html` line 25 (patient app bar `<small>Tec Tha Care Connect</small>`, on every patient screen).
  - `templates/patient/profile.html` line 28 (footer "· Tec Tha Care Connect").
  - `static/offline.html` lines 3 and 12 (title and body).
  - `static/manifest.webmanifest` `"name": "Tec Tha Care Connect"`. This is the name shown on the phone home screen and in the install prompt. Also check `short_name` and the patient manifest served by `patient_app.manifest()`.
  - `app/main.py` line 29 (`FastAPI(title=…)`, shown on `/docs`).
  - Not visible to users, but should also change: comment headers in `style.css`, `patient.css`, `app.js` and `sw.js`, and the docstring and `print` in `seed.py`.
  - The icons in `static/icons/` (`icon-192.png` with the "T." mark) don't contain the words, but check that they still match the brand.
- **Why:** A mixed name in the pilot looks unfinished to the hospital, and a patient sees the old name on every screen.
- **Fix:** Replace the visible strings with "Tec Tha HP": the sidebar `<small>HP</small>` (or one line, `<strong>Tec Tha HP</strong>`), the top bar and footer "Tec Tha HP", and the patient app bar `<small>Tec Tha HP</small>`. Better still, put the name in one place: `config.PRODUCT_NAME = "Tec Tha HP"` exposed as a Jinja global `product`, then use `{{ product }}` in the templates and manifests so it can't drift again. Bump the service-worker cache version so installed apps pick up the new manifest and offline page.

---

## Minor

1. **Colour contrast below 4.5:1 (1.4.3).**
   - Staff `--faint #7b8b84` on `--bg` is 3.26 (`footer.foot`), and 3.58 on white for `.rem` "24 h". Use `--faint:#5f716a` (about 4.9).
   - Patient `.status` "Please confirm" (`--saffron #c9780b` on white) is 3.40, and `.stub-note` "Given at check-in" on `--saffron-soft` is 3.06. Add `--saffron-ink:#8a5200` and use it for text, keeping `--saffron` for borders.
   - `.p-ok` "Visited" is 4.46 and the patient `.pill.ok` "Paid" is 4.28. Darken `--ok` to `#17703d` (staff) and `#176f3c` (patient).
   - Dark staff `.bubble.out .meta` and `.tpl` (`--muted` on `--bubble-out #1c4a37`) are 4.23. Use `.bubble.out .meta,.bubble.out .tpl{color:#b7cbc3}`.
2. **The reminder chips "24 h / 2 h" use strikethrough for "not sent yet"** (`.rem` without `.on`). That reads as failed or cancelled. Use `○ 24 h` for not yet and `✓ 24 h` for sent, with a `title` such as "Sent 03 Nov 12:00", and drop `text-decoration:line-through`.
3. **The account menu doesn't close on Esc, and `role="menu"`/`menuitem` sit on a `<details>` with no menu keyboard model (4.1.2).** Remove `role="menu"`/`role="menuitem"` (a plain disclosure is correct) and add an Esc handler in `app.js` that closes `details.menu[open]` and focuses its `summary`.
4. **The booking dialog's default time is "now + 1 h, rounded", and there's no clash warning.** A walk-in should default to "Now", and three patients at 13:15 with one doctor gives no warning. Add a "Now" quick button and show "Dr. A. Khan already has 2 patients at 13:15" under the time field (backend gives the count).
5. **The booking success toast doesn't mention WhatsApp.** When the consent box is left unticked, add "No WhatsApp sent: consent not given." In the patient app, the same rule is already worded well.
6. **The doctor select is one long string for every branch** ("Dr. A. Khan · Cardiology · Branch A · ₹900"). Group it with `<optgroup label="Branch A">` and default to the user's or the selected branch.
7. **The claims "Move" select cuts off its text** ("Pre-auth ap…", "Final bill sen…") and allows backward moves with no confirmation. Replace it with one primary button for the next stage (`Move to Pre-auth approved`) and put the other stages in a "More" `<details>`.
8. **On the patient profile at 390px, the appointment status pill is cut off at the right edge** (`m3.png`, 1st panel). Use `.timeline li{flex-wrap:wrap}` and `.timeline .pill{margin-left:auto}` and drop `min-width:120px` on `.when` on phone.
9. **The Messages chat header is cramped on phone.** The name is cut to "Lakshmi S…" and the phone, uid and count wrap over 4 lines (`m2.png`). On phone, hide the message count and move the uid below the name: `.chat-head .who .small{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}`. Shorten "Patient profile" to an icon button with `aria-label`.
10. **The staff phone header takes about 156px.** The brand row, then a row with only the branch switch and avatar, then search. Put the branch switch and avatar on the brand row (`.top-right{margin-left:auto}` with `flex-wrap:nowrap` on the first row) and shrink the select to `max-width:120px`.
11. **App-booked visits ask the patient to confirm what they just booked.** Home shows "Please confirm" and My visits shows "Booked" with a Confirm button. Insert app bookings as `Confirmed` in `book_submit`, and use one word for that state in both places: "Please confirm" on Home and "Booked" on My visits are the same state with two names.
12. **"Change time" promises self-service but only asks for a callback** ("Our team will call you to pick a new time"). Rename it "Ask to change time", or link it into the booking flow with the doctor already chosen.
13. **Payment success is only a toast.** After paying, show a full success state on the bill page: a large tick, "₹300 paid", the receipt number, "Receipt sent on WhatsApp", and a "Back to home" button. Patients want proof they paid.
14. **Fonts come from Google** in `base.html` and `patient/base.html`. This sends patient and staff IP addresses to Google, which contradicts "patient data stays on the hospital's own server", and fails on an offline LAN. Self-host Sora and Source Sans 3 woff2 files in `/static/fonts/` with `font-display:swap`.
15. **Toast text comes from `?msg=` and `?err=` in the URL**, so anyone can send a patient a link to `/my/?err=Your account is blocked, call 9xxxx` and it shows as a real alert. Pass flash messages in a signed short-lived cookie instead (backend).
16. **Some wording is technical.** "Possibly unbilled" can be "May not be on a bill". The toast "Token 2: NoShow." shows the raw status: use the label map ("No-show"). The patient "Code" field label can be "6-digit code from WhatsApp". There's no "Send the code again" link on the code step; add one after 30 seconds.
17. **Staff tasks offer no undo.** "Done" closes a task in one tap. Add "Undo" to the toast (same pattern as M3).

## Polish

1. **The patient Home shortcuts repeat the tab bar** (Book, Reports, Bills). Keep only "My visits" and "Reports", or make "My visits" a tab instead of Profile, and put Profile in the app bar.
2. **The pay page asks for a second "Pay ₹X" tap** with a single, already-chosen UPI option. When UPI is the only mode, show a one-line "Paying by UPI" and keep the single button.
3. **The booking date grid shows days the doctor may not work.** Grey out days with no slots (`aria-disabled="true"`, "No times") instead of showing an empty state after the tap.
4. **The `#a-day` date and booking time follow the browser locale** (mm/dd/yyyy on an en-US browser). Show the chosen day in words next to it ("Wednesday, 4 Nov", which the `h1` already does) so the format never confuses anyone.
5. **Uppercase micro-labels are everywhere** (`.label`, `th`, `.cards td::before`, `.section-title`). They're fine on desktop, but on phone cards they add noise. Use sentence case for the phone card labels.
6. **The login and patient copy both say "Your Hospital"** until Settings is filled in, giving "Your Your Hospital login code" in the OTP text. Make seed or setup ask for the hospital name first, or fall back to "the hospital" in message templates.

---

## Top tasks walkthrough

| Task | Steps today | Friction |
|---|---|---|
| Front desk books a walk-in | Appointments → Book → type name, mobile, choose doctor from all branches, edit time, tick consent → Book | Typos wipe the form (B1); time defaults to +1 h (Minor 4); no clash warning; booking from an enquiry means typing again (M5) |
| Billing desk collects a due | Billing → scan list by eye → Record payment → Save | No search (B2); phone dialog broken (M1). Saving itself is quick: the amount is pre-filled and the toast says "Payment of ₹26,300 recorded." |
| Owner reads the morning picture | Dashboard | Strong: "Needs attention" first, yesterday versus the day before, a 5-figure strip. But claims past limit show 0 when 2 are over (M9), and the owner's buttons may 403 (M10). |
| Patient books and pays | Login (phone → WhatsApp code) → Book (branch → doctor → day → time → confirm); Bills → bill → Pay → Pay | Booking is excellent (4 clear steps, 48px slots). Paying: the due amount isn't the headline (M13), it takes two Pay taps, the success is only a toast (Minor 13), English only (M12), and there's no one-tap help (M14). |

## Automated scan notes

- **Tool:** a Playwright script (`scratchpad/audit.js`). For every staff and patient screen at 4 configs, it computes WCAG contrast from computed styles (alpha-blended backgrounds), measures touch targets, checks labels, names, landmarks and headings, detects horizontal overflow and clipped text, and walks 30 Tab stops on desktop.
- **Results:**
  - Horizontal scroll at 390px: **none** on any screen.
  - Unlabelled form fields: **none**.
  - Unnamed buttons and links: none real (the flagged items were hidden-menu false positives).
  - Every page has `main`, `header`, `nav` and exactly one `h1`, except the staff JSON 404 (M11).
  - Focus is visible on every Tab stop (the patient phone input shows its ring on `.phone-field:focus-within`).
  - Contrast failures: the 6 pairs in Minor 1 (light), and 2 bubble-meta pairs plus the JSON 404 (dark).
- **Needs a manual check by a person:**
  - Screen-reader announcement of toasts. They're inside `aria-live="polite"` but rendered on load, so NVDA and TalkBack may not announce them. Test, and consider moving focus to the error toast after a failed submit.
  - TalkBack reading the patient star rating.
  - 200% zoom on the claims board.
  - Hindi rendering once added.
  - **A usability session with 3 front-desk staff and 3 patients aged 50+ before the pilot.**

## What works well (keep it)

- Status pills carry a shape as well as colour (✓ ◆ ▲ ● ○), so state never relies on colour alone (1.4.1).
- Skip link, sticky top bar, `aria-current="page"` on the nav and tabs, `aria-labelledby` on every section.
- Dialogs: focus goes to the first field, Esc closes, focus returns to the button that opened it. The phone bottom sheet is correct.
- `prefers-reduced-motion` turns off every animation in both apps.
- The dark theme is a real redesign of the tokens, not an inversion. Almost every pair passes AA.
- The patient app: the 48–54px controls, `autocomplete="one-time-code"`, the masked number, "4 tries left", the kind feedback wording, the "Demo · no real money is charged" flag, and the booking stepper with `aria-current="step"`.
- Empty states say what to do next ("Try the last 5 digits of the mobile number, or the TT- ID printed on the bill.").
- The consent checkbox is unticked by default and explains DPDP. Withdrawing consent is one clear button.
