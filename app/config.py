"""Configuration from environment variables. Missing required values fail loudly."""
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    db_path: str
    whatsapp_mode: str          # 'simulator' or 'live'
    whatsapp_token: str
    whatsapp_phone_id: str
    whatsapp_verify_token: str
    whatsapp_app_secret: str    # verifies Meta webhook signatures (required in live mode)
    api_key: str                # X-API-Key for /api (billing software, website forms)
    session_secret: str         # signs staff login cookies
    owner_phone: str            # receives the 9 am report
    payment_link_base: str      # e.g. a Razorpay/UPI payment page base URL
    review_link: str            # Google review link
    scheduler_enabled: bool
    scheduler_interval_seconds: int


def _local_secret() -> str:
    """No TT_SESSION_SECRET set: use a random secret created once and kept in data/.session_secret.

    Never a fixed default, so nobody can forge a login cookie on a fresh install.
    """
    path = ROOT / "data" / ".session_secret"
    if path.exists():
        return path.read_text().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(48)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value)
    return value


def load() -> Settings:
    mode = os.environ.get("TT_WHATSAPP_MODE", "simulator")
    if mode not in ("simulator", "live"):
        raise RuntimeError(f"TT_WHATSAPP_MODE must be 'simulator' or 'live', got {mode!r}")
    s = Settings(
        db_path=os.environ.get("TT_DB_PATH", str(ROOT / "data" / "tectha.db")),
        whatsapp_mode=mode,
        whatsapp_token=os.environ.get("TT_WHATSAPP_TOKEN", ""),
        whatsapp_phone_id=os.environ.get("TT_WHATSAPP_PHONE_ID", ""),
        whatsapp_verify_token=os.environ.get("TT_WHATSAPP_VERIFY_TOKEN", "tectha-verify"),
        whatsapp_app_secret=os.environ.get("TT_WHATSAPP_APP_SECRET", ""),
        api_key=os.environ.get("TT_API_KEY", ""),
        session_secret=os.environ.get("TT_SESSION_SECRET") or _local_secret(),
        owner_phone=os.environ.get("TT_OWNER_PHONE", ""),
        payment_link_base=os.environ.get("TT_PAYMENT_LINK_BASE", "https://pay.example.in/tectha"),
        review_link=os.environ.get("TT_REVIEW_LINK", "https://g.page/r/your-hospital/review"),
        scheduler_enabled=os.environ.get("TT_SCHEDULER", "on") == "on",
        scheduler_interval_seconds=int(os.environ.get("TT_SCHEDULER_INTERVAL", "60")),
    )
    if s.whatsapp_mode == "live" and not (s.whatsapp_token and s.whatsapp_phone_id):
        raise RuntimeError("Live WhatsApp mode needs TT_WHATSAPP_TOKEN and TT_WHATSAPP_PHONE_ID")
    if s.whatsapp_mode == "live" and not s.whatsapp_app_secret:
        raise RuntimeError("Live WhatsApp mode needs TT_WHATSAPP_APP_SECRET to verify incoming webhooks")
    if len(s.session_secret) < 32:
        raise RuntimeError("TT_SESSION_SECRET must be at least 32 characters")
    return s


settings = load()
