"""AI governance: a registry of every model or rule set in use, and a log of every human decision on its output."""
import json

from app import db, util

DECISIONS = ("suggested", "accepted", "edited", "rejected", "sent", "acknowledged", "escalated")

# key: (feature, kind, model_name, model_version, prompt_version, description)
MODELS = {
    "noshow_rules": ("no_show_risk", "rules", "Tec Tha no-show rules", "1.0", None,
                     "Rule-based no-show risk from past no-shows, lead time, distance, slot, reminder reply and dues."),
    "explainer_templates": ("report_explainer", "template", "Doctor-approved explainer templates", "1.0", None,
                            "Plain-language text about what a test measures; never interprets a patient's result."),
    "draft_reply_templates": ("draft_reply", "template", "Tec Tha reply templates", "1.0", None,
                              "Deterministic draft replies chosen from the patient's last message."),
    "draft_reply_claude": ("draft_reply", "llm", "Claude", "see TT_AI_MODEL", "DRAFT_REPLY_V1",
                           "Claude drafts a reply with the receptionist's safety rules; staff edit and send."),
    "coding_rules": ("coding_assistant", "rules", "Tec Tha coding map", "1.0", None,
                     "Keyword map from notes and orders to ICD-10 and PM-JAY package suggestions."),
    "coding_claude": ("coding_assistant", "llm", "Claude", "see TT_AI_MODEL", "CODING_V1",
                      "Claude suggests ICD-10 / PM-JAY codes with the quoted evidence sentence; a coder decides."),
    "news2_rcp": ("news2", "rules", "NEWS2 (Royal College of Physicians, 2017)", "SpO2 scale 1", None,
                  "Published National Early Warning Score 2 computed as rules. Not a diagnosis."),
}


def ensure_registered() -> None:
    """Insert or refresh every registry row (idempotent; called at start-up)."""
    from app.ai import client as ai
    now = util.ts(util.now())
    for key, (feature, kind, name, version, prompt_v, desc) in MODELS.items():
        if version == "see TT_AI_MODEL":
            version = ai.model()
        db.execute(
            "INSERT INTO model_registry(key, feature, kind, model_name, model_version, prompt_version, description, registered_at)"
            " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET model_version = excluded.model_version,"
            " prompt_version = excluded.prompt_version, description = excluded.description",
            (key, feature, kind, name, version, prompt_v, desc, now))


def log_decision(feature: str, model_key: str, decision: str, actor: str, *, output, subject_type: str | None = None,
                 subject_id: int | None = None, input_summary: str | None = None) -> int:
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    if model_key not in MODELS:
        raise KeyError(f"Model {model_key!r} is not in the registry")
    if not db.scalar("SELECT 1 FROM model_registry WHERE key = ?", (model_key,)):
        ensure_registered()
    out = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, default=str)
    return db.execute(
        "INSERT INTO ai_decisions(feature, model_key, subject_type, subject_id, input_summary, output, decision, actor, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (feature, model_key, subject_type, subject_id, (input_summary or "")[:500], out[:4000], decision, actor,
         util.ts(util.now())))
