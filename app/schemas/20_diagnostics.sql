-- Diagnostics & Pharmacy, Command Centre and Notifications (Tec Tha Vital Pro).
-- Loaded after app/schema.sql by db.init_db(). Times are IST 'YYYY-MM-DD HH:MM:SS'.

-- ---------- Laboratory
CREATE TABLE IF NOT EXISTS lab_tests (
  code       TEXT PRIMARY KEY,           -- e.g. K, TSH, PLT
  name       TEXT NOT NULL,
  specimen   TEXT NOT NULL,              -- Serum, EDTA blood, Urine ...
  unit       TEXT NOT NULL,
  crit_low   REAL,                       -- below = critical (call out)
  crit_high  REAL,                       -- above = critical (call out)
  delta_pct  REAL NOT NULL DEFAULT 50,   -- change vs previous result that needs a pathologist
  tat_hours  INTEGER NOT NULL DEFAULT 6,
  price      INTEGER NOT NULL            -- rupees
);

-- Reference ranges by sex and age band. sex 'A' = any.
CREATE TABLE IF NOT EXISTS lab_ranges (
  id        INTEGER PRIMARY KEY,
  test_code TEXT NOT NULL REFERENCES lab_tests(code),
  sex       TEXT NOT NULL DEFAULT 'A' CHECK (sex IN ('A','M','F')),
  age_min   INTEGER NOT NULL DEFAULT 0,
  age_max   INTEGER NOT NULL DEFAULT 120,
  low       REAL,
  high      REAL
);

CREATE TABLE IF NOT EXISTS lab_orders (
  id             INTEGER PRIMARY KEY,
  patient_id     INTEGER NOT NULL REFERENCES patients(id),
  branch_id      TEXT NOT NULL REFERENCES branches(id),
  doctor_id      INTEGER REFERENCES doctors(id),
  test_code      TEXT NOT NULL REFERENCES lab_tests(code),
  sample_id      TEXT UNIQUE,            -- barcode printed at collection
  status         TEXT NOT NULL DEFAULT 'Ordered'
                 CHECK (status IN ('Ordered','Collected','Received','Resulted','Validated','Cancelled')),
  result_value   REAL,
  flag           TEXT CHECK (flag IN ('N','L','H','LL','HH')),
  ref_low        REAL,
  ref_high       REAL,
  delta_flag     INTEGER NOT NULL DEFAULT 0,
  auto_validated INTEGER NOT NULL DEFAULT 0,
  reflex_of      INTEGER REFERENCES lab_orders(id),   -- added automatically by a reflex rule
  order_id       INTEGER REFERENCES orders(id),       -- billing line (unbilled until added to a bill)
  ordered_at     TEXT NOT NULL,
  collected_at   TEXT,
  received_at    TEXT,
  resulted_at    TEXT,
  validated_at   TEXT,
  validated_by   TEXT
);
CREATE INDEX IF NOT EXISTS idx_lab_orders_status ON lab_orders(branch_id, status);
CREATE INDEX IF NOT EXISTS idx_lab_orders_patient ON lab_orders(patient_id, test_code);

-- Reflex testing: when trigger_code comes back with this flag, add_code is ordered on the same sample.
CREATE TABLE IF NOT EXISTS lab_reflex_rules (
  id           INTEGER PRIMARY KEY,
  trigger_code TEXT NOT NULL REFERENCES lab_tests(code),
  on_flag      TEXT NOT NULL CHECK (on_flag IN ('L','H','LL','HH','ABN')),  -- ABN = any abnormal
  add_code     TEXT NOT NULL REFERENCES lab_tests(code),
  active       INTEGER NOT NULL DEFAULT 1
);

-- Critical value call-out: who told whom, when, with read-back.
CREATE TABLE IF NOT EXISTS lab_callouts (
  id           INTEGER PRIMARY KEY,
  lab_order_id INTEGER NOT NULL UNIQUE REFERENCES lab_orders(id),
  status       TEXT NOT NULL DEFAULT 'Open' CHECK (status IN ('Open','CalledOut')),
  created_at   TEXT NOT NULL,
  called_by    TEXT,
  called_to    TEXT,
  read_back    INTEGER NOT NULL DEFAULT 0,
  called_at    TEXT,
  escalated_at TEXT
);

-- ---------- Radiology
CREATE TABLE IF NOT EXISTS rad_orders (
  id              INTEGER PRIMARY KEY,
  patient_id      INTEGER NOT NULL REFERENCES patients(id),
  branch_id       TEXT NOT NULL REFERENCES branches(id),
  doctor_id       INTEGER REFERENCES doctors(id),
  modality        TEXT NOT NULL CHECK (modality IN ('X-ray','USG','CT','MRI')),
  study           TEXT NOT NULL,
  is_obstetric    INTEGER NOT NULL DEFAULT 0,   -- obstetric USG: PCPNDT Form F must be completed
  form_f_recorded INTEGER NOT NULL DEFAULT 0,   -- record only; no sex-determination field exists
  slot_at         TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'Scheduled' CHECK (status IN ('Scheduled','Performed','Reported','Cancelled')),
  report_text     TEXT,
  reported_by     TEXT,
  reported_at     TEXT,
  order_id        INTEGER REFERENCES orders(id),
  created_at      TEXT NOT NULL
);

-- ---------- Pharmacy counter
CREATE TABLE IF NOT EXISTS drugs (
  code       TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  schedule   TEXT NOT NULL DEFAULT '' CHECK (schedule IN ('','H','H1','X')),
  unit_price INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS drug_batches (
  id        INTEGER PRIMARY KEY,
  drug_code TEXT NOT NULL REFERENCES drugs(code),
  branch_id TEXT NOT NULL REFERENCES branches(id),
  batch_no  TEXT NOT NULL,
  expiry    TEXT NOT NULL,                 -- 'YYYY-MM-DD'
  qty       INTEGER NOT NULL CHECK (qty >= 0)
);

CREATE TABLE IF NOT EXISTS prescriptions (
  id           INTEGER PRIMARY KEY,
  patient_id   INTEGER NOT NULL REFERENCES patients(id),
  branch_id    TEXT NOT NULL REFERENCES branches(id),
  doctor_id    INTEGER REFERENCES doctors(id),
  status       TEXT NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending','Dispensed','Billed')),
  created_at   TEXT NOT NULL,
  dispensed_at TEXT,
  dispensed_by TEXT,
  bill_id      INTEGER REFERENCES bills(id)
);

CREATE TABLE IF NOT EXISTS prescription_items (
  id              INTEGER PRIMARY KEY,
  prescription_id INTEGER NOT NULL REFERENCES prescriptions(id),
  drug_code       TEXT NOT NULL REFERENCES drugs(code),
  qty             INTEGER NOT NULL CHECK (qty > 0),
  batch_id        INTEGER REFERENCES drug_batches(id),
  amount          INTEGER
);

-- Drugs and Cosmetics Rules: Schedule H / H1 / X register.
CREATE TABLE IF NOT EXISTS schedule_register (
  id           INTEGER PRIMARY KEY,
  item_id      INTEGER NOT NULL REFERENCES prescription_items(id),
  schedule     TEXT NOT NULL,
  drug_name    TEXT NOT NULL,
  patient_name TEXT NOT NULL,
  prescriber   TEXT,
  qty          INTEGER NOT NULL,
  batch_no     TEXT NOT NULL,
  branch_id    TEXT NOT NULL,
  dispensed_by TEXT NOT NULL,
  created_at   TEXT NOT NULL
);

-- ---------- Beds (Command Centre)
CREATE TABLE IF NOT EXISTS wards (
  id        INTEGER PRIMARY KEY,
  branch_id TEXT NOT NULL REFERENCES branches(id),
  name      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS beds (
  id         INTEGER PRIMARY KEY,
  ward_id    INTEGER NOT NULL REFERENCES wards(id),
  label      TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'Free' CHECK (status IN ('Free','Occupied','Cleaning','Blocked')),
  patient_id INTEGER REFERENCES patients(id)
);

-- ---------- Notifications (one row per person; role targets are expanded when created)
CREATE TABLE IF NOT EXISTS notifications (
  id         INTEGER PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id),
  branch_id  TEXT,
  title      TEXT NOT NULL,
  link       TEXT NOT NULL,
  severity   TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('info','warn','critical')),
  source_key TEXT,                        -- de-duplicates notifications made by sweeps
  created_at TEXT NOT NULL,
  read_at    TEXT,
  UNIQUE (user_id, source_key)
);
CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, read_at);
