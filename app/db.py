"""SQLite access. One connection per call site; rows come back as dicts."""
import re
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


# Feature modules add their own tables in app/schemas/*.sql (CREATE ... IF NOT EXISTS),
# loaded after the core schema in file-name order.
MODULE_SCHEMAS = Path(__file__).with_name("schemas")


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA.read_text())
        for extra in sorted(MODULE_SCHEMAS.glob("*.sql")):
            conn.executescript(extra.read_text())
    migrate()


# ---------------------------------------------------------------- migrations
# schema.sql only uses CREATE ... IF NOT EXISTS, so a database created by an older
# version keeps its old tables. These steps bring it up to date. Each one checks
# first, so running init_db() again changes nothing.

def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _table_sql(conn: sqlite3.Connection, table: str) -> str:
    r = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return r[0] if r else ""


def _schema_create(table: str) -> str:
    m = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", SCHEMA.read_text(), re.S)
    if not m:
        raise RuntimeError(f"schema.sql has no CREATE TABLE for {table}")
    return m.group(1)


def _add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _rebuild_users(conn: sqlite3.Connection) -> None:
    """The role CHECK can't be altered in SQLite: copy users into a table with the new CHECK.

    Runs in one transaction, and only when the stored definition doesn't allow the newest roles yet.
    """
    if "'pharmacy'" in _table_sql(conn, "users"):
        return
    old_cols = _columns(conn, "users")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(f"CREATE TABLE users_new ({_schema_create('users')}\n)")
        keep = [c for c in _columns(conn, "users_new") if c in old_cols]
        cols = ", ".join(keep)
        conn.execute(f"INSERT INTO users_new ({cols}) SELECT {cols} FROM users")
        conn.execute("DROP TABLE users")
        conn.execute("ALTER TABLE users_new RENAME TO users")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def migrate() -> None:
    conn = sqlite3.connect(_db_path, timeout=10, isolation_level=None)
    try:
        _rebuild_users(conn)
        _add_column(conn, "users", "session_version", "INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "patients", "session_version", "INTEGER NOT NULL DEFAULT 0")
        # Pro: two-step login (TOTP). The secret is set when enrolment starts; enabled only after a code checks out.
        _add_column(conn, "users", "totp_secret", "TEXT")
        _add_column(conn, "users", "totp_enabled", "INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "users", "totp_last_step", "INTEGER NOT NULL DEFAULT 0")
    finally:
        conn.close()


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
