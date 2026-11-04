"""In-app notifications (the bell in the top bar).

Any module calls notify(...). A role target is expanded to one row per active user with that role
who can see the branch (users with no branch see every branch), so each person reads and clears
their own copy. source_key de-duplicates notifications created by repeated sweeps.
"""
from app import db, util

SEVERITIES = ("info", "warn", "critical")


def notify(*, title: str, link: str, user_ids: list[int] | None = None, role: str | list[str] | None = None,
           branch: str | None = None, severity: str = "info", source_key: str | None = None) -> int:
    """Create notifications. Returns how many rows were created (0 if all were duplicates)."""
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {SEVERITIES}")
    if not title.strip() or not link.startswith("/"):
        raise ValueError("A notification needs a title and an in-app link starting with /")
    targets: set[int] = set(user_ids or [])
    roles = [role] if isinstance(role, str) else list(role or [])
    for r in roles:
        rows = db.query("SELECT id FROM users WHERE role = ? AND active = 1 AND (branch_id IS NULL OR ? IS NULL OR branch_id = ?)",
                        (r, branch, branch))
        targets.update(row["id"] for row in rows)
    if not targets and not user_ids and not roles:
        raise ValueError("notify() needs user_ids or role")
    created = 0
    now = util.ts(util.now())
    with db.connect() as conn:
        for uid in sorted(targets):
            cur = conn.execute(
                "INSERT OR IGNORE INTO notifications(user_id, branch_id, title, link, severity, source_key, created_at)"
                " VALUES (?,?,?,?,?,?,?)", (uid, branch, title[:200], link, severity, source_key, now))
            created += cur.rowcount
    return created


def unread_count(user_id: int) -> int:
    return db.scalar("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read_at IS NULL", (user_id,)) or 0


def recent(user_id: int, limit: int = 8) -> list[dict]:
    return db.query("SELECT * FROM notifications WHERE user_id = ? ORDER BY read_at IS NOT NULL, id DESC LIMIT ?",
                    (user_id, limit))


def mark_read(user_id: int, notification_id: int | None = None) -> int:
    """Mark one (or, with no id, all) of this user's notifications read. Returns rows changed."""
    now = util.ts(util.now())
    with db.connect() as conn:
        if notification_id is None:
            cur = conn.execute("UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL", (now, user_id))
        else:
            cur = conn.execute("UPDATE notifications SET read_at = ? WHERE user_id = ? AND id = ? AND read_at IS NULL",
                               (now, user_id, notification_id))
        return cur.rowcount
