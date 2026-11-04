from pathlib import Path

import pytest

from app import db
from app.integrations import csv_import

SAMPLES = Path(__file__).resolve().parent.parent / "docs" / "samples"


def test_sample_patients_import(fresh_db):
    r = csv_import.import_patients((SAMPLES / "patients.csv").read_text(), "user:test")
    assert r == {"created": 5, "updated": 0, "skipped": 0, "errors": []}
    assert db.scalar("SELECT consent_messages FROM patients WHERE name='Anita Desai'") == 0
    again = csv_import.import_patients((SAMPLES / "patients.csv").read_text(), "user:test")
    assert again["created"] == 0 and again["skipped"] == 5
    assert db.scalar("SELECT COUNT(*) FROM patients") == 5


def test_patient_bad_rows_are_reported(fresh_db):
    text = "name,phone,age,gender,consent\nGood One,9845012345,30,M,yes\n,9845012346,30,M,yes\nBad Phone,12345,30,M,yes\nBad Consent,9845012347,30,M,maybe\n"
    r = csv_import.import_patients(text, "user:test")
    assert r["created"] == 1
    assert [e["row"] for e in r["errors"]] == [3, 4, 5]


def test_patient_consent_update_counts_as_updated(fresh_db):
    csv_import.import_patients("name,phone,age,gender,consent\nA B,9845012345,30,M,no\n", "t")
    r = csv_import.import_patients("name,phone,age,gender,consent\nA B,9845012345,30,M,yes\n", "t")
    assert r["updated"] == 1


def test_missing_columns_raise(fresh_db):
    with pytest.raises(ValueError, match="missing columns"):
        csv_import.import_patients("name,mobile\nA,9845012345\n", "t")


def test_sample_bills_import_and_reimport(fresh_db):
    text = (SAMPLES / "bills.csv").read_text()
    r = csv_import.import_bills(text, "user:test")
    assert r == {"created": 3, "updated": 0, "skipped": 0, "errors": []}
    b = db.one("SELECT * FROM bills WHERE bill_no='HIS-24001'")
    assert b["total"] == 2650 and b["paid"] == 2050 and b["branch_id"] == "B" and b["external_ref"] == "INV-77001"
    assert db.scalar("SELECT paid FROM bills WHERE bill_no='HIS-24003'") == 0
    again = csv_import.import_bills(text, "user:test")
    assert again["created"] == 0 and again["skipped"] == 3
    assert db.scalar("SELECT COUNT(*) FROM bills") == 3
    assert db.scalar("SELECT COUNT(*) FROM payments") == 2


def test_bill_bad_rows_are_reported(fresh_db):
    text = ("bill_no,external_ref,phone,patient_name,branch_id,item,amount,paid,date\n"
            "X1,,9845012345,A B,Z,Consult,500,0,2026-11-01\n"
            "X2,,9845012345,A B,A,Consult,abc,0,2026-11-01\n"
            "X3,,9845012345,A B,A,Consult,500,900,2026-11-01\n"
            "X4,,9845012345,A B,A,Consult,500,0,01/13/2026\n"
            ",,9845012345,A B,A,Consult,500,0,2026-11-01\n"
            "X5,,9845012345,A B,A,Consult,500,500,03-11-2026\n")
    r = csv_import.import_bills(text, "t")
    assert r["created"] == 1
    assert len(r["errors"]) == 5
    assert db.scalar("SELECT COUNT(*) FROM bills") == 1
