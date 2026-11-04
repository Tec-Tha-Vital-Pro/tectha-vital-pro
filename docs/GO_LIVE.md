# Going live

Follow these steps after the hospital signs the pilot. Every account is created **in the hospital's name**, with Tec Tha as admin. That way the hospital owns its data and is never locked in.

## 1. Before anything touches patient data

- [ ] Mutual NDA signed.
- [ ] Data processing agreement signed (what data, why, where it is stored, who can access it, how long it is kept). Have a lawyer review it.
- [ ] Patient consent line added to the registration form: "I agree to receive appointment, report and billing messages on WhatsApp. Reply STOP to opt out."

## 2. Server (low cost)

Any small Linux server in an Indian region works, for example a 1–2 GB VPS in Mumbai or Bengaluru.

- [ ] Install Python 3.11+, then `pip install -r requirements.txt`.
- [ ] Put the app behind HTTPS (Caddy or Nginx with Let's Encrypt). Meta's webhooks need HTTPS.
- [ ] Set environment variables (see README): a long random `TT_SESSION_SECRET` and `TT_API_KEY`.
- [ ] Run with a process manager, for example systemd running `uvicorn app.main:app --host 127.0.0.1 --port 8000`.
- [ ] Back up `data/tectha.db` every night to a second location, and test a restore once.
- [ ] Create one login per staff member with the right role. No shared logins.

## 3. WhatsApp Cloud API

1. Create a Meta Business account for the hospital and verify the business.
2. In Meta for Developers, create an app and add the **WhatsApp** product.
3. For the demo, use the free test number; it can message up to 5 numbers you verify.
4. For live use, add the hospital's own number. It cannot be in use on the normal WhatsApp app at the same time.
5. Copy the **phone number ID** and create a **permanent access token** (System User).
6. Set `TT_WHATSAPP_MODE=live`, `TT_WHATSAPP_TOKEN`, `TT_WHATSAPP_PHONE_ID`, `TT_WHATSAPP_APP_SECRET` (App settings → Basic).
7. Webhook: callback URL `https://<your-domain>/webhooks/whatsapp`, verify token = `TT_WHATSAPP_VERIFY_TOKEN`, subscribe to `messages`.

**Templates:** WhatsApp only allows free text within 24 hours of the patient's last message. Reminders, dues and reports sent outside that window need **message templates approved by Meta**. Submit templates for: appointment reminder, dues reminder, report ready, follow-up reminder, feedback request and the owner report. Until a template is approved, those sends are stored as `failed` with Meta's error on the Messages screen. They are never dropped silently.

Meta charges per conversation by category (utility, marketing). Pass these costs to the hospital at actual cost.

## 4. Connect the hospital's software

- Ask the billing vendor for an API or a scheduled export (CSV or Excel).
- Start with a daily CSV import (Settings → Import). Move to the API (`/api/bills`, `/api/payments`) once the vendor agrees.
- Website forms and ad leads → `/api/leads` (through n8n or Zapier, header `X-API-Key`).
- Missed calls → `/webhooks/missed-call` from Exotel or Knowlarity.

## 5. Pilot checklist

- [ ] Measure the starting numbers first: no-show rate, dues outstanding, reply time to enquiries.
- [ ] Turn on one automation at a time and watch the Messages screen for the first day.
- [ ] Send the owner a results report every month.
