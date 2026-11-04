"""Patient identity: one record and one ID per phone number, across all branches."""
from app import audit, db, util


def find_or_create(name: str, phone: str, *, age: int | None = None, gender: str | None = None,
                   consent: bool | None = None, actor: str = "system") -> dict:
    """Match on normalised phone. Creates the patient if new; updates consent when given."""
    phone = util.normalize_phone(phone)
    p = db.one("SELECT * FROM patients WHERE phone = ?", (phone,))
    now = util.ts(util.now())
    if p is None:
        pid = db.execute(
            "INSERT INTO patients(name, phone, age, gender, consent_messages, consent_at, created_at) VALUES (?,?,?,?,?,?,?)",
            (name.strip(), phone, age, gender, 1 if consent else 0, now if consent else None, now),
        )
        db.execute("UPDATE patients SET uid = ? WHERE id = ?", (util.patient_uid(pid), pid))
        audit.log(actor, "create", "patient", pid, {"phone": phone, "consent": bool(consent)})
        return db.one("SELECT * FROM patients WHERE id = ?", (pid,))
    if consent is not None and bool(p["consent_messages"]) != consent:
        set_consent(p["id"], consent, actor=actor)
        p = db.one("SELECT * FROM patients WHERE id = ?", (p["id"],))
    return p


def set_consent(patient_id: int, consent: bool, actor: str = "system") -> None:
    db.execute(
        "UPDATE patients SET consent_messages = ?, consent_at = ? WHERE id = ?",
        (1 if consent else 0, util.ts(util.now()) if consent else None, patient_id),
    )
    audit.log(actor, "consent_given" if consent else "consent_withdrawn", "patient", patient_id)


def get(patient_id: int) -> dict:
    p = db.one("SELECT * FROM patients WHERE id = ?", (patient_id,))
    if p is None:
        raise LookupError(f"Patient {patient_id} not found")
    return p
