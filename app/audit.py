"""Audit log: every automated message and data change is recorded (DPDP / NABH)."""
import json

from app import db, util


def log(actor: str, action: str, entity: str, entity_id: int | None = None, detail: dict | str | None = None) -> None:
    if isinstance(detail, dict):
        detail = json.dumps(detail, ensure_ascii=False)
    db.execute(
        "INSERT INTO audit_log(actor, action, entity, entity_id, detail, created_at) VALUES (?,?,?,?,?,?)",
        (actor, action, entity, entity_id, detail, util.ts(util.now())),
    )
