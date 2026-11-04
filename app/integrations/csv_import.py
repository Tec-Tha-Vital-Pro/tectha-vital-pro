"""CSV import from the hospital's existing billing software. Bad rows are reported, never dropped silently."""
import csv
import io
from datetime import datetime

from app import billing, db, patients, util

PATIENT_COLS = ["name", "phone", "age", "gender", "consent"]
BILL_COLS = ["bill_no", "external_ref", "phone", "patient_name", "branch_id", "item", "amount", "paid", "date"]


def _reader(csv_text: str, required: list[str]) -> csv.DictReader:
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("﻿")))
    cols = [c.strip().lower() for c in (reader.fieldnames or [])]
    missing = [c for c in required if c not in cols]
    if missing:
        raise ValueError(f"CSV is missing columns: {', '.join(missing)}. Expected: {', '.join(required)}")
    reader.fieldnames = cols
    return reader


def _consent(v: str) -> bool | None:
    v = (v or "").strip().lower()
    if v in ("yes", "y", "true", "1"):
        return True
    if v in ("no", "n", "false", "0"):
        return False
    if v == "":
        return None
    raise ValueError(f"consent must be yes or no, got {v!r}")


def import_patients(csv_text: str, actor: str) -> dict:
    result = {"created": 0, "updated": 0, "skipped": 0, "errors": []}
    for i, row in enumerate(_reader(csv_text, PATIENT_COLS), start=2):  # row 1 = header
        try:
            name = (row.get("name") or "").strip()
            if not name:
                raise ValueError("name is empty")
            phone = util.normalize_phone(row.get("phone") or "")
            age_raw = (row.get("age") or "").strip()
            age = int(age_raw) if age_raw else None
            gender = (row.get("gender") or "").strip() or None
            consent = _consent(row.get("consent"))
            existed = db.one("SELECT * FROM patients WHERE phone = ?", (phone,))
            p = patients.find_or_create(name, phone, age=age, gender=gender, consent=consent, actor=actor)
            if existed is None:
                result["created"] += 1
            elif dict(existed) != dict(p):
                result["updated"] += 1
            else:
                result["skipped"] += 1
        except (ValueError, LookupError) as e:
            result["errors"].append({"row": i, "error": str(e)})
    return result


def _parse_date(v: str) -> str:
    v = (v or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return util.ts(datetime.strptime(v, fmt).replace(hour=12))
        except ValueError:
            pass
    raise ValueError(f"date must be YYYY-MM-DD or DD-MM-YYYY, got {v!r}")


def import_bills(csv_text: str, actor: str) -> dict:
    result = {"created": 0, "updated": 0, "skipped": 0, "errors": []}
    groups: dict[str, list[tuple[int, dict]]] = {}
    for i, row in enumerate(_reader(csv_text, BILL_COLS), start=2):
        bill_no = (row.get("bill_no") or "").strip()
        if not bill_no:
            result["errors"].append({"row": i, "error": "bill_no is empty"})
            continue
        groups.setdefault(bill_no, []).append((i, row))

    for bill_no, rows in groups.items():
        first_row_no, first = rows[0]
        try:
            if db.one("SELECT id FROM bills WHERE bill_no = ?", (bill_no,)):
                result["skipped"] += 1
                continue
            branch = (first.get("branch_id") or "").strip()
            if not db.one("SELECT id FROM branches WHERE id = ?", (branch,)):
                raise ValueError(f"unknown branch_id {branch!r}")
            name = (first.get("patient_name") or "").strip()
            if not name:
                raise ValueError("patient_name is empty")
            created = _parse_date(first.get("date"))
            items = []
            for row_no, r in rows:
                desc = (r.get("item") or "").strip()
                if not desc:
                    raise ValueError(f"row {row_no}: item is empty")
                try:
                    amount = int(float((r.get("amount") or "").replace(",", "")))
                except ValueError:
                    raise ValueError(f"row {row_no}: amount {r.get('amount')!r} is not a number")
                items.append((desc, amount))
            paid_raw = (first.get("paid") or "0").replace(",", "").strip() or "0"
            try:
                paid = int(float(paid_raw))
            except ValueError:
                raise ValueError(f"paid {first.get('paid')!r} is not a number")
            if paid < 0 or paid > sum(a for _, a in items):
                raise ValueError(f"paid {paid} must be between 0 and the bill total {sum(a for _, a in items)}")
            p =patients.find_or_create(name, first.get("phone") or "", actor=actor)
            ext = (first.get("external_ref") or "").strip() or None
            bid = billing.create_bill(p["id"], branch, items, bill_no=bill_no, external_ref=ext, created_at=created, actor=actor)
            if paid > 0:
                billing.record_payment(bid, paid, "Imported", paid_at=created, actor=actor)
            result["created"] += 1
        except (ValueError, LookupError) as e:
            result["errors"].append({"row": first_row_no, "error": f"bill {bill_no}: {e}"})
    return result
