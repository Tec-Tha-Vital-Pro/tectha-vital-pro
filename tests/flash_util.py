"""Read the signed toast text out of a redirect Location (toasts are signed, never plain ?msg= text)."""
from urllib.parse import parse_qs, urlparse


def flash(location: str, kind: str = "msg", app: str = "staff") -> str:
    token = parse_qs(urlparse(location).query).get(kind, [""])[0]
    if app == "patient":
        from app.routes import patient_app
        return patient_app.read_flash(token) or ""
    from app.routes import ui
    data = ui.read_flash(token)
    return data["t"] if data else ""
