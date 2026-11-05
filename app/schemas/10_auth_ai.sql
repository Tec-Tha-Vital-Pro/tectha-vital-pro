-- Tec Tha Vital Pro: staff two-step login, single sign-on, voice assistant and AI Labs agents.
-- Loaded after app/schema.sql by db.init_db(). Times are IST 'YYYY-MM-DD HH:MM:SS'.
-- Rows that point at clinical or billing records (patients, claims, orders) keep the id without a
-- foreign key, so reseeding the demo data never fails on these tables.

-- One-time recovery codes for two-step login (only the hash is stored).
CREATE TABLE IF NOT EXISTS user_recovery_codes (
  id         INTEGER PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id),
  code_hash  TEXT NOT NULL,
  used_at    TEXT,
  created_at TEXT NOT NULL
);

-- Google / Microsoft accounts a staff member linked to their own login (never auto-created).
CREATE TABLE IF NOT EXISTS user_identities (
  id         INTEGER PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id),
  provider   TEXT NOT NULL CHECK (provider IN ('google','microsoft')),
  subject    TEXT NOT NULL,           -- the provider's stable user id ("sub")
  email      TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (provider, subject)
);

-- Voice assistant: a conversation, with consent. Audio is never stored, only text.
CREATE TABLE IF NOT EXISTS voice_sessions (
  id         INTEGER PRIMARY KEY,
  token      TEXT NOT NULL UNIQUE,
  patient_id INTEGER,                 -- logged-in patient (patient app), else NULL
  phone      TEXT,                    -- 91XXXXXXXXXX
  lang       TEXT NOT NULL DEFAULT 'en-IN',
  consent_at TEXT,                    -- when the person agreed to voice processing
  state      TEXT NOT NULL DEFAULT '{}',   -- deterministic menu state (JSON)
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS voice_turns (
  id         INTEGER PRIMARY KEY,
  session_id INTEGER NOT NULL REFERENCES voice_sessions(id),
  direction  TEXT NOT NULL CHECK (direction IN ('in','out')),
  text       TEXT NOT NULL,
  lang       TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- AI Labs: when each agent last ran.
CREATE TABLE IF NOT EXISTS agent_runs (
  agent       TEXT PRIMARY KEY,
  last_run_at TEXT NOT NULL,
  last_result TEXT NOT NULL
);

-- What the agents found. A person accepts (the safe action runs) or dismisses each one.
CREATE TABLE IF NOT EXISTS findings (
  id               INTEGER PRIMARY KEY,
  agent            TEXT NOT NULL,
  dedupe_key       TEXT NOT NULL,
  severity         TEXT NOT NULL CHECK (severity IN ('info','low','medium','high')),
  title            TEXT NOT NULL,
  evidence         TEXT NOT NULL,     -- JSON
  suggested_action TEXT NOT NULL,     -- plain words for the person deciding
  action           TEXT,              -- JSON {"type": ..., ...} run on Accept; NULL = review only
  amount           INTEGER,           -- rupees at stake, when there are any
  branch_id        TEXT,
  status           TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','accepted','dismissed')),
  decided_by       TEXT,
  decided_at       TEXT,
  decision_note    TEXT,
  ai_summary       TEXT,
  created_at       TEXT NOT NULL,
  UNIQUE (agent, dedupe_key)
);
CREATE INDEX IF NOT EXISTS idx_findings_status ON findings(status, agent);

-- Standard prices: the revenue-loss agent flags bill lines charged below them.
CREATE TABLE IF NOT EXISTS tariffs (
  id          INTEGER PRIMARY KEY,
  description TEXT NOT NULL UNIQUE,
  amount      INTEGER NOT NULL
);

-- Documents each insurer or TPA needs, and what each claim file has.
CREATE TABLE IF NOT EXISTS payer_checklists (
  id       INTEGER PRIMARY KEY,
  insurer  TEXT NOT NULL,
  document TEXT NOT NULL,
  UNIQUE (insurer, document)
);

CREATE TABLE IF NOT EXISTS claim_documents (
  id          INTEGER PRIMARY KEY,
  claim_id    INTEGER NOT NULL,
  document    TEXT NOT NULL,
  received_at TEXT NOT NULL,
  UNIQUE (claim_id, document)
);

-- Minimal pharmacy stock for the stock and expiry agent.
CREATE TABLE IF NOT EXISTS stock_items (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL,
  branch_id     TEXT NOT NULL REFERENCES branches(id),
  unit          TEXT NOT NULL DEFAULT 'unit',
  reorder_level INTEGER NOT NULL DEFAULT 0,
  daily_usage   REAL NOT NULL DEFAULT 0,      -- average units used per day
  UNIQUE (name, branch_id)
);

CREATE TABLE IF NOT EXISTS stock_batches (
  id          INTEGER PRIMARY KEY,
  item_id     INTEGER NOT NULL REFERENCES stock_items(id),
  batch_no    TEXT NOT NULL,
  expiry_date TEXT NOT NULL,                  -- 'YYYY-MM-DD'
  qty         INTEGER NOT NULL CHECK (qty >= 0),
  unit_cost   INTEGER NOT NULL DEFAULT 0      -- rupees
);

CREATE TABLE IF NOT EXISTS stock_moves (
  id          INTEGER PRIMARY KEY,
  batch_id    INTEGER NOT NULL REFERENCES stock_batches(id),
  to_batch_id INTEGER REFERENCES stock_batches(id),
  qty         INTEGER NOT NULL,
  reason      TEXT NOT NULL,
  actor       TEXT NOT NULL,
  created_at  TEXT NOT NULL
);
