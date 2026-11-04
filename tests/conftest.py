"""Shared test fixtures. Each test gets its own empty database with two branches and two doctors."""
import os

os.environ.setdefault("TT_SCHEDULER", "off")
os.environ.setdefault("TT_API_KEY", "test-key")

import pytest

from app import db


@pytest.fixture()
def fresh_db(tmp_path):
    db.set_path(str(tmp_path / "test.db"))
    db.init_db()
    db.execute("INSERT INTO branches(id, name) VALUES ('A','Branch A'), ('B','Branch B')")
    db.execute("INSERT INTO doctors(name, specialty, branch_id, fee) VALUES ('Dr. S. Menon','Orthopaedics','B',600), ('Dr. R. Iyer','General Medicine','A',500)")
    return db
