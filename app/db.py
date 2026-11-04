"""SQLite access. One connection per call site; rows come back as dicts."""
import sqlite3
from pathlib import Path

from app import config

SCHEMA = Path(__file__).with_name("schema.sql")
_db_path = config.settings.db_path


def set_path(path: str) -> None:
    """Point the app at another database file (tests use a temp file)."""
    global _db_path
    _db_path = path


def connect() -> sqlite3.Connection:
    Path(_db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA.read_text())


def query(sql: str, params: tuple | dict = ()) -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(sql: str, params: tuple | dict = ()) -> dict | None:
    with connect() as conn:
        r = conn.execute(sql, params).fetchone()
        return dict(r) if r else None


def scalar(sql: str, params: tuple | dict = ()):
    with connect() as conn:
        r = conn.execute(sql, params).fetchone()
        return r[0] if r else None


def execute(sql: str, params: tuple | dict = ()) -> int:
    """Run a write. Returns lastrowid."""
    with connect() as conn:
        cur = conn.execute(sql, params)
        return cur.lastrowid


def get_setting(key: str, default: str) -> str:
    v = scalar("SELECT value FROM settings WHERE key = ?", (key,))
    return default if v is None else v


def set_setting(key: str, value: str) -> None:
    execute("INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
