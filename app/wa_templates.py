"""WhatsApp message templates to submit to Meta for approval (category: Utility).

WhatsApp allows free text only within 24 hours of the patient's last message.
Outside that window, live mode sends these approved templates instead.
Submit each one in Meta Business Manager → WhatsApp Manager → Message templates
with exactly this name, language and body. {{n}} are the body parameters.
"""

TEMPLATES: dict[str, dict] = {
    "tt_appt_reminder": {
        "language": "en",
        "body": "Hello {{1}}, this is a reminder from {{2}}. Your appointment with {{3}} is on {{4}} at {{5}}. "
                "Booking ID {{6}}. Reply 1 to confirm, 2 to reschedule or 3 to cancel.",
        "params": ["patient name", "hospital name", "doctor", "date and time", "branch", "booking id"],
    },
    "tt_dues_reminder": {
        "language": "en",
        "body": "Dear {{1}}, your bill {{2}} at {{3}} has a balance due of {{4}}. You can pay securely here: {{5}}. "
                "Please ignore this message if you have already paid.",
        "params": ["patient name", "bill number", "hospital and branch", "balance", "payment link"],
    },
    "tt_followup_reminder": {
        "language": "en",
        "body": "Dear {{1}}, your {{2}} at {{3}} is due on {{4}}. Reply to this message and we will book a convenient time for you.",
        "params": ["patient name", "reason", "hospital and branch", "due date"],
    },
    "tt_feedback_request": {
        "language": "en",
        "body": "Thank you for visiting {{1}}, {{2}}. How was your visit with {{3}}? "
                "Please reply with a number from 1 (poor) to 5 (excellent).",
        "params": ["hospital name", "patient name", "doctor"],
    },
    "tt_owner_daily_report": {
        "language": "en",
        "body": "{{1}} report for {{2}}: OPD patients {{3}}, billed {{4}}, collected {{5}}, outstanding dues {{6}}. "
                "Needs attention: {{7}}. Open the dashboard for details.",
        "params": ["hospital name", "date", "OPD count", "billed", "collected", "dues", "attention summary"],
    },
}


def params(name: str, values: list) -> tuple[str, list[str]]:
    """Validate and clean template parameters. Raises ValueError on a mismatch."""
    t = TEMPLATES.get(name)
    if t is None:
        raise ValueError(f"Unknown WhatsApp template {name!r}")
    if len(values) != len(t["params"]):
        raise ValueError(f"Template {name} needs {len(t['params'])} parameters, got {len(values)}")
    # Meta rejects newlines, tabs and 4+ consecutive spaces inside parameters.
    clean = [" ".join(str(v).split()) for v in values]
    if any(not v for v in clean):
        raise ValueError(f"Template {name} has an empty parameter")
    return name, clean


def preview(name: str, values: list[str]) -> str:
    body = TEMPLATES[name]["body"]
    for i, v in enumerate(values, 1):
        body = body.replace("{{%d}}" % i, v)
    return body
