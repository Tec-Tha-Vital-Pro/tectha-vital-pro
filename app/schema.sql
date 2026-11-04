-- Tec Tha Care Connect schema. Times are IST, stored as 'YYYY-MM-DD HH:MM:SS' text.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS branches (
  id   TEXT PRIMARY KEY,            -- 'A', 'B'
  name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patients (
  id               INTEGER PRIMARY KEY,
  uid              TEXT UNIQUE,                 -- one ID across all branches, e.g. TT-000042
  name             TEXT NOT NULL,
  phone            TEXT NOT NULL UNIQUE,        -- normalised: 91XXXXXXXXXX
  age              INTEGER,
  gender           TEXT,
  abha_id          TEXT,
  language         TEXT NOT NULL DEFAULT 'en',
  consent_messages INTEGER NOT NULL DEFAULT 0,  -- DPDP: no messages without consent
  consent_at       TEXT,
  created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS doctors (
  id        INTEGER PRIMARY KEY,
  name      TEXT NOT NULL,
  specialty TEXT NOT NULL,
  branch_id TEXT NOT NULL REFERENCES branches(id),
  fee       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS leads (
  id                   INTEGER PRIMARY KEY,
  name                 TEXT NOT NULL,
  phone                TEXT NOT NULL,
  need                 TEXT,
  source               TEXT NOT NULL,        -- WhatsApp, Phone call, Website form, Google, Facebook ad, Instagram ad, Practo, Walk-in, Referral
  branch_id            TEXT REFERENCES branches(id),
  status               TEXT NOT NULL DEFAULT 'New' CHECK (status IN ('New','Contacted','Booked','Converted','Lost')),
  first_reply_seconds  INTEGER,              -- NULL = not replied yet
  patient_id           INTEGER REFERENCES patients(id),
  created_at           TEXT NOT NULL,
  updated_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS appointments (
  id                   INTEGER PRIMARY KEY,
  patient_id           INTEGER NOT NULL REFERENCES patients(id),
  doctor_id            INTEGER NOT NULL REFERENCES doctors(id),
  branch_id            TEXT NOT NULL REFERENCES branches(id),
  starts_at            TEXT NOT NULL,
  status               TEXT NOT NULL DEFAULT 'Booked' CHECK (status IN ('Booked','Confirmed','Cancelled','Visited','NoShow')),
  token_no             INTEGER,
  source               TEXT,
  reminder_24h_sent_at TEXT,
  reminder_2h_sent_at  TEXT,
  feedback_sent_at     TEXT,
  created_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bills (
  id           INTEGER PRIMARY KEY,
  bill_no      TEXT NOT NULL UNIQUE,
  patient_id   INTEGER NOT NULL REFERENCES patients(id),
  branch_id    TEXT NOT NULL REFERENCES branches(id),
  total        INTEGER NOT NULL,        -- rupees
  paid         INTEGER NOT NULL DEFAULT 0,
  external_ref TEXT,                    -- id in the hospital's billing software
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bill_items (
  id          INTEGER PRIMARY KEY,
  bill_id     INTEGER NOT NULL REFERENCES bills(id),
  description TEXT NOT NULL,
  amount      INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
  id      INTEGER PRIMARY KEY,
  bill_id INTEGER NOT NULL REFERENCES bills(id),
  amount  INTEGER NOT NULL,
  mode    TEXT NOT NULL,                -- UPI, Card, Cash, Insurance
  paid_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dues_reminders (
  id      INTEGER PRIMARY KEY,
  bill_id INTEGER NOT NULL REFERENCES bills(id),
  stage   INTEGER NOT NULL,             -- 1, 2, 3 ... escalating
  sent_at TEXT NOT NULL
);

-- Services delivered (lab, pharmacy, ward) that must appear on a bill.
CREATE TABLE IF NOT EXISTS orders (
  id          INTEGER PRIMARY KEY,
  patient_id  INTEGER NOT NULL REFERENCES patients(id),
  branch_id   TEXT NOT NULL REFERENCES branches(id),
  dept        TEXT NOT NULL,
  description TEXT NOT NULL,
  amount      INTEGER NOT NULL,
  bill_id     INTEGER REFERENCES bills(id),   -- NULL = not billed yet
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS claims (
  id               INTEGER PRIMARY KEY,
  patient_id       INTEGER NOT NULL REFERENCES patients(id),
  branch_id        TEXT NOT NULL REFERENCES branches(id),
  insurer          TEXT NOT NULL,
  amount           INTEGER NOT NULL,
  stage            TEXT NOT NULL CHECK (stage IN ('PreAuthRequested','PreAuthApproved','FinalSent','Settled','Denied')),
  stage_changed_at TEXT NOT NULL,
  created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS followups (
  id          INTEGER PRIMARY KEY,
  patient_id  INTEGER NOT NULL REFERENCES patients(id),
  branch_id   TEXT NOT NULL REFERENCES branches(id),
  due_date    TEXT NOT NULL,            -- 'YYYY-MM-DD'
  reason      TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'Due' CHECK (status IN ('Due','Reminded','Booked','Done')),
  reminded_at TEXT,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedback (
  id             INTEGER PRIMARY KEY,
  patient_id     INTEGER NOT NULL REFERENCES patients(id),
  appointment_id INTEGER REFERENCES appointments(id),
  score          INTEGER NOT NULL CHECK (score BETWEEN 1 AND 5),
  comment        TEXT,
  escalated      INTEGER NOT NULL DEFAULT 0,
  created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
  id           INTEGER PRIMARY KEY,
  patient_id   INTEGER REFERENCES patients(id),
  to_phone     TEXT NOT NULL,
  direction    TEXT NOT NULL CHECK (direction IN ('out','in')),
  template     TEXT NOT NULL,           -- e.g. appt_reminder_24h, dues_reminder, inbound
  body         TEXT NOT NULL,
  status       TEXT NOT NULL CHECK (status IN ('simulated','sent','failed','blocked_no_consent','received')),
  error        TEXT,
  related_type TEXT,
  related_id   INTEGER,
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
  id           INTEGER PRIMARY KEY,
  kind         TEXT NOT NULL CHECK (kind IN ('missed_call','complaint','claim_stuck','unbilled','followup_call')),
  title        TEXT NOT NULL,
  branch_id    TEXT REFERENCES branches(id),
  related_type TEXT,
  related_id   INTEGER,
  status       TEXT NOT NULL DEFAULT 'Open' CHECK (status IN ('Open','Done')),
  due_at       TEXT,
  created_at   TEXT NOT NULL,
  UNIQUE (kind, related_type, related_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
  id         INTEGER PRIMARY KEY,
  actor      TEXT NOT NULL,             -- 'system', 'automation', 'user:<name>', 'webhook'
  action     TEXT NOT NULL,
  entity     TEXT NOT NULL,
  entity_id  INTEGER,
  detail     TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_appt_start ON appointments(starts_at);
CREATE INDEX IF NOT EXISTS idx_bills_patient ON bills(patient_id);
CREATE INDEX IF NOT EXISTS idx_msgs_created ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_leads_created ON leads(created_at);

-- Staff logins. Each person has their own account and role (no shared logins).
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,
  full_name     TEXT NOT NULL,
  password_hash TEXT NOT NULL,          -- pbkdf2_sha256$iterations$salt_hex$hash_hex
  role          TEXT NOT NULL CHECK (role IN ('admin','frontdesk','billing','doctor')),
  branch_id     TEXT REFERENCES branches(id),   -- NULL = all branches
  active        INTEGER NOT NULL DEFAULT 1,
  created_at    TEXT NOT NULL
);

-- Meta retries webhooks; each WhatsApp message id is handled once.
CREATE TABLE IF NOT EXISTS processed_webhooks (
  message_id  TEXT PRIMARY KEY,
  received_at TEXT NOT NULL
);
