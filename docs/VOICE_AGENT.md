# Voice agent

The voice agent lets a patient talk to the clinic receptionist in their own
language. It is decision support for the front desk, not a clinician: it books,
answers timings/fees/bill questions, and hands everything else to a person.

## What ships today (browser)

| Piece | Where |
|---|---|
| Patient page (signed-in patient app) | `GET /my/voice` |
| Public demo (simulator mode only, never books, never shows records) | `GET /voice/demo` |
| Start a conversation (records consent) | `POST /voice/start` |
| One turn (text in, text out) | `POST /voice/turn` |
| Browser code | `app/static/voice.js` |
| Logic | `app/ai/voice.py`, `app/ai/receptionist.py` |

- **Speech** uses the browser's Web Speech API: `SpeechRecognition` for
  speech-to-text and `speechSynthesis` for the reply. Languages: en-IN, hi-IN,
  ta-IN, te-IN, kn-IN, ml-IN, mr-IN. A typing box is always there as the
  fallback (Firefox/Safari, no mic, noisy room).
- **Audio is never stored or sent to Tec Tha.** Only the recognised text is
  POSTed. Chrome and Edge run recognition on Google's / Microsoft's speech
  service; the consent text says so before the first turn.
- **Consent** is recorded in `voice_sessions.consent_at`; a turn without consent
  is refused. Turns are saved as text in `voice_turns` and every start is audited.
- **CSRF**: JSON calls send `X-CSRF-Token`. The patient page uses the patient
  session's token; the demo uses a double-submit cookie (`tt_vcsrf`, SameSite
  strict). `/voice/start` is rate limited to 30 per hour per IP.
- **Emergency words** ("chest pain", "unconscious", ...) always get the fixed
  "call 108 / come to casualty" reply first, with or without AI.
- **AI off** (`TT_AI` not `on`): a deterministic menu — book (doctor → slot →
  confirm), timings, fees, bill. **AI on**: the receptionist pipeline with
  `channel="voice"`; its numbers come from the database, not the model.
- **Unverified callers** (demo, unknown phone): no record, no balance, no
  booking — a booking request becomes a callback task for the front desk.

## Telephony (next step — not built)

There are deliberately **no** telephony endpoints in the code yet. A stub that
accepts calls without signature checks would be an open door. When the clinic
picks a provider, build it like this:

1. **Provider**: Exotel (India numbers, DLT-friendly) or Twilio. The founder
   buys a number and gives us the account SID/token and the webhook secret.
2. **Inbound call webhook** `POST /telephony/{provider}/call`:
   verify the provider signature (Exotel: basic auth + IP allow-list; Twilio:
   `X-Twilio-Signature` HMAC), look up the caller phone, play the consent line
   (recorded IVR prompt, "press 1 to continue"), then create a
   `voice_sessions` row with `consent_at` set only after the keypress.
3. **Speech**: use the provider's built-in speech-to-text (`<Gather input="speech">`
   / Exotel Voicebot stream) so we still receive **text only**. Do not enable
   call recording. Map the caller language from the IVR choice.
4. **Turn webhook** `POST /telephony/{provider}/turn`: call
   `app.ai.voice.turn(session, text)` — the same function the browser uses —
   and return the reply as TwiML `<Say>` / Exotel response.
5. **Verification**: a phone number matching a patient is *not* proof of
   identity. Keep `verified=False` until an OTP sent by SMS/WhatsApp is read
   back, same as the browser demo.
6. **Hand-off**: "talk to a person" or two failed turns → `<Dial>` the front desk
   number and create a task.
7. Tests: signature rejection, consent-before-turn, no recording flag, OTP gate.

Env vars that build will need: `TT_TELEPHONY_PROVIDER`, `TT_EXOTEL_SID`,
`TT_EXOTEL_TOKEN`, `TT_TWILIO_AUTH_TOKEN`, `TT_FRONTDESK_PHONE`.
