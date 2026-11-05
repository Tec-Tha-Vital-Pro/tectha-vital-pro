"""Voice assistant pages and API.

/my/voice      for logged-in patients (patient app); bookings and bills use their own record.
/voice/demo    public demo page, only in demo (simulator) mode; the typed number is not trusted.
/voice/start   begin a conversation (consent required)        JSON, header X-CSRF-Token
/voice/turn    send one transcript, get the reply to speak    JSON, header X-CSRF-Token
"""
import hmac
import secrets
from datetime import timedelta

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app import config, security, util
from app.ai import voice
from app.routes import patient_app, ui

router = APIRouter()
patient_pages = APIRouter(route_class=patient_app.PatientRoute)
DEMO_COOKIE = "tt_vcsrf"


def _demo_mode() -> bool:
    return config.settings.whatsapp_mode == "simulator"


def _caller(request: Request, mode: str) -> dict | None:
    """Check the CSRF token for this kind of caller. Returns the logged-in patient, or None for the demo."""
    token = request.headers.get("X-CSRF-Token", "")
    if mode == "patient":
        p = patient_app.current_patient(request)
        if p is None:
            raise PermissionError("Please log in to the patient app again.")
        if not hmac.compare_digest(token.encode(), p["csrf"].encode()):
            raise PermissionError("This page expired. Reload it and try again.")
        return p
    if mode == "demo" and _demo_mode():
        cookie = request.cookies.get(DEMO_COOKIE, "")
        if not cookie or not hmac.compare_digest(token.encode(), cookie.encode()):
            raise PermissionError("This page expired. Reload it and try again.")
        return None
    raise PermissionError("The voice demo is only available in demo mode.")


async def _json(request: Request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise voice.VoiceError("Send the request as JSON.")
    return data


def _fail(status: int, text: str) -> JSONResponse:
    return JSONResponse({"error": text}, status_code=status)


@router.post("/voice/start")
async def start(request: Request):
    try:
        data = await _json(request)
        mode = str(data.get("mode", ""))
        p = _caller(request, mode)
        key = f"voice|{security.client_ip(request)}"
        if security.hits("voice_start", key, timedelta(hours=1)) >= 30:
            return _fail(429, "Too many conversations from this device. Please wait a while.")
        security.record("voice_start", key)
        out = voice.start(patient=p, phone=str(data.get("phone", "")) or None, lang=str(data.get("lang", "en-IN")),
                          consent=data.get("consent") is True,
                          actor=f"patient:{p['uid']}" if p else "voice-demo")
    except PermissionError as e:
        return _fail(403, str(e))
    except voice.VoiceError as e:
        return _fail(400, str(e))
    return JSONResponse(out)


@router.post("/voice/turn")
async def turn(request: Request):
    try:
        data = await _json(request)
        p = _caller(request, str(data.get("mode", "")))
        s = voice.session(str(data.get("token", "")), p)
        out = voice.turn(s, str(data.get("text", "")), str(data.get("lang", s["lang"])), util.now())
    except PermissionError as e:
        return _fail(403, str(e))
    except voice.VoiceError as e:
        return _fail(400, str(e))
    return JSONResponse({"reply": out["reply"], "action": out["action"]})


@patient_pages.get("/my/voice", response_class=HTMLResponse)
def patient_voice(request: Request):
    p = patient_app._me(request)
    return patient_app._page(request, "voice_patient.html", p, langs=voice.LANGS, consent_text=voice.CONSENT_TEXT)


@router.get("/voice/demo", response_class=HTMLResponse)
def demo_voice(request: Request):
    if not _demo_mode():
        return ui.not_found_page(request)
    token = request.cookies.get(DEMO_COOKIE) or secrets.token_urlsafe(24)
    resp = ui.render(request, "voice_demo.html", None, langs=voice.LANGS, consent_text=voice.CONSENT_TEXT, voice_csrf=token)
    resp.set_cookie(DEMO_COOKIE, token, max_age=3600, httponly=True, samesite="strict", secure=security.is_https(request),
                    path="/")
    return resp


router.include_router(patient_pages)
