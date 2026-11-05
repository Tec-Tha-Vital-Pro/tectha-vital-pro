-- Tec Tha Vital Pro: next AI features (no-show risk, report explainers, draft replies,
-- coding assistant, NEWS2) and the AI governance log shared by every AI feature.

-- One row per model or rule set in use (ICMR 2023: know what is running).
CREATE TABLE IF NOT EXISTS model_registry (
  key            TEXT PRIMARY KEY,          -- e.g. noshow_rules, news2_rcp, draft_reply_claude
  feature        TEXT NOT NULL,
  kind           TEXT NOT NULL CHECK (kind IN ('rules','llm','ml','template')),
  model_name     TEXT NOT NULL,
  model_version  TEXT NOT NULL,
  prompt_version TEXT,
  description    TEXT NOT NULL,
  registered_at  TEXT NOT NULL
);

-- Every AI or rules output that a person acted on, and what they decided.
CREATE TABLE IF NOT EXISTS ai_decisions (
  id            INTEGER PRIMARY KEY,
  feature       TEXT NOT NULL,
  model_key     TEXT NOT NULL REFERENCES model_registry(key),
  subject_type  TEXT,
  subject_id    INTEGER,
  input_summary TEXT,
  output        TEXT NOT NULL,
  decision      TEXT NOT NULL CHECK (decision IN ('suggested','accepted','edited','rejected','sent','acknowledged','escalated')),
  actor         TEXT NOT NULL,
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ai_decisions_feature ON ai_decisions(feature, created_at);

-- Patient-facing explainer text per lab test: what the test measures, never the patient's own result.
CREATE TABLE IF NOT EXISTS report_explainers (
  id          INTEGER PRIMARY KEY,
  test_code   TEXT NOT NULL,
  lang        TEXT NOT NULL CHECK (lang IN ('en','hi')),
  body        TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft','Approved')),
  edited_by   TEXT NOT NULL,
  edited_at   TEXT NOT NULL,
  approved_by TEXT,
  approved_at TEXT,
  UNIQUE (test_code, lang)
);

-- Draft replies proposed to staff on the Messages screen. Never sent by themselves.
CREATE TABLE IF NOT EXISTS draft_replies (
  id         INTEGER PRIMARY KEY,
  phone      TEXT NOT NULL,
  draft      TEXT NOT NULL,
  model_key  TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'Proposed' CHECK (status IN ('Proposed','Sent','Discarded')),
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  final_text TEXT,
  decided_at TEXT
);

-- Clinical coding suggestions for a claim. The coder accepts or edits; nothing is submitted automatically.
CREATE TABLE IF NOT EXISTS coding_suggestions (
  id             INTEGER PRIMARY KEY,
  claim_id       INTEGER NOT NULL REFERENCES claims(id),
  suggestions    TEXT NOT NULL,             -- JSON list of {system, code, label, evidence}
  model_key      TEXT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'Proposed' CHECK (status IN ('Proposed','Accepted','Rejected')),
  accepted_codes TEXT,                      -- JSON list chosen or edited by the coder
  created_at     TEXT NOT NULL,
  decided_by     TEXT,
  decided_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_coding_claim ON coding_suggestions(claim_id);

-- Nursing vitals and the NEWS2 score worked out from them (RCP NEWS2, SpO2 scale 1).
CREATE TABLE IF NOT EXISTS vitals (
  id            INTEGER PRIMARY KEY,
  patient_id    INTEGER NOT NULL REFERENCES patients(id),
  bed_id        INTEGER REFERENCES beds(id),
  branch_id     TEXT NOT NULL REFERENCES branches(id),
  resp_rate     INTEGER NOT NULL,
  spo2          INTEGER NOT NULL,
  on_oxygen     INTEGER NOT NULL DEFAULT 0,
  systolic_bp   INTEGER NOT NULL,
  pulse         INTEGER NOT NULL,
  consciousness TEXT NOT NULL CHECK (consciousness IN ('A','C','V','P','U')),
  temperature   REAL NOT NULL,
  news2         INTEGER NOT NULL,
  any_three     INTEGER NOT NULL DEFAULT 0,  -- a single parameter scored 3
  recorded_by   TEXT NOT NULL,
  recorded_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vitals_patient ON vitals(patient_id, recorded_at);

CREATE TABLE IF NOT EXISTS news2_alerts (
  id              INTEGER PRIMARY KEY,
  vitals_id       INTEGER NOT NULL REFERENCES vitals(id),
  patient_id      INTEGER NOT NULL REFERENCES patients(id),
  branch_id       TEXT NOT NULL,
  level           TEXT NOT NULL CHECK (level IN ('rise','urgent','emergency')),
  score           INTEGER NOT NULL,
  reason          TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'Open' CHECK (status IN ('Open','Acknowledged')),
  created_at      TEXT NOT NULL,
  acknowledged_by TEXT,
  acknowledged_at TEXT,
  escalated_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_news2_open ON news2_alerts(status, created_at);
