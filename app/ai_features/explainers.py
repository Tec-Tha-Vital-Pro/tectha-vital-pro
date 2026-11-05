"""Lab report explainers for patients.

Each text says what a test measures and why doctors order it. It never mentions or interprets the
patient's own value, and always ends by sending the patient back to their doctor. A doctor or admin
writes or edits the text; a doctor or admin must approve it before any patient sees it.
"""
from app import audit, db, util
from app.ai_features import governance

DISCUSS = {"en": "Please discuss your result with your doctor.",
           "hi": "कृपया अपनी रिपोर्ट के बारे में अपने डॉक्टर से बात करें।"}

# Starter drafts (Draft until approved). Plain language; nothing about whether a value is good or bad.
STARTERS = {
    "K": ("Potassium is a mineral in the blood that helps the heart, nerves and muscles work.",
          "पोटैशियम खून में मौजूद एक खनिज है जो दिल, नसों और मांसपेशियों के काम में मदद करता है।"),
    "NA": ("Sodium is a salt in the blood that helps control the body's water balance and nerves.",
           "सोडियम खून में मौजूद नमक है जो शरीर में पानी के संतुलन और नसों को नियंत्रित करने में मदद करता है।"),
    "PLT": ("Platelets are tiny blood cells that help blood clot and stop bleeding.",
            "प्लेटलेट्स खून की छोटी कोशिकाएँ हैं जो खून को जमने और बहने से रोकने में मदद करती हैं।"),
    "HCT": ("Haematocrit shows how much of the blood is made of red blood cells, which carry oxygen.",
            "हीमैटोक्रिट बताता है कि खून का कितना हिस्सा लाल रक्त कोशिकाओं का है, जो ऑक्सीजन ले जाती हैं।"),
    "TSH": ("TSH is a hormone from the brain that tells the thyroid gland how much hormone to make.",
            "TSH दिमाग से आने वाला एक हार्मोन है जो थायरॉइड ग्रंथि को बताता है कि कितना हार्मोन बनाना है।"),
    "FT4": ("Free T4 is a thyroid hormone that controls how the body uses energy.",
            "फ्री T4 थायरॉइड का एक हार्मोन है जो नियंत्रित करता है कि शरीर ऊर्जा का उपयोग कैसे करता है।"),
    "HBA1C": ("HbA1c shows the average blood sugar over the past two to three months.",
              "HbA1c पिछले दो से तीन महीनों की औसत ब्लड शुगर दिखाता है।"),
    "CREAT": ("Creatinine is a waste product that the kidneys filter out of the blood.",
              "क्रिएटिनिन एक अपशिष्ट पदार्थ है जिसे गुर्दे खून से छानकर बाहर निकालते हैं।"),
    "INR": ("INR shows how long the blood takes to clot. It is often checked for people on blood thinners.",
            "INR बताता है कि खून को जमने में कितना समय लगता है। खून पतला करने वाली दवा लेने वालों में यह अक्सर जाँचा जाता है।"),
}

# Words that would interpret a patient's own result; an explainer containing them is refused.
FORBIDDEN = ("your result is", "your value", "you have", "is normal", "is high", "is low", "abnormal", "आपकी रिपोर्ट सामान्य",
             "आपका परिणाम")


def check_text(body: str) -> None:
    b = body.strip().lower()
    if not b:
        raise ValueError("Write the explainer text first.")
    if len(b) > 600:
        raise ValueError("Keep the explainer under 600 characters.")
    if any(w in b for w in FORBIDDEN):
        raise ValueError("An explainer may say what the test measures, but must not talk about the patient's own result.")


def save(test_code: str, lang: str, body: str, actor: str) -> None:
    if lang not in DISCUSS:
        raise ValueError("Language must be English or Hindi.")
    check_text(body)
    now = util.ts(util.now())
    db.execute(
        "INSERT INTO report_explainers(test_code, lang, body, status, edited_by, edited_at) VALUES (?,?,?,'Draft',?,?)"
        " ON CONFLICT(test_code, lang) DO UPDATE SET body = excluded.body, status = 'Draft', edited_by = excluded.edited_by,"
        " edited_at = excluded.edited_at, approved_by = NULL, approved_at = NULL",
        (test_code, lang, body.strip(), actor, now))
    audit.log(actor, "explainer_edited", "report_explainer", None, {"test": test_code, "lang": lang})


def approve(test_code: str, lang: str, actor: str) -> None:
    row = db.one("SELECT * FROM report_explainers WHERE test_code = ? AND lang = ?", (test_code, lang))
    if row is None:
        raise LookupError("No explainer to approve.")
    db.execute("UPDATE report_explainers SET status='Approved', approved_by=?, approved_at=? WHERE id=?",
               (actor, util.ts(util.now()), row["id"]))
    governance.log_decision("report_explainer", "explainer_templates", "accepted", actor, output=row["body"],
                            subject_type="report_explainer", subject_id=row["id"], input_summary=f"{test_code}/{lang}")
    audit.log(actor, "explainer_approved", "report_explainer", row["id"], {"test": test_code, "lang": lang})


def for_patient(test_code: str, lang: str) -> str | None:
    """Approved text in the patient's language (falls back to approved English), or None."""
    for lg in (lang, "en"):
        row = db.one("SELECT body FROM report_explainers WHERE test_code = ? AND lang = ? AND status = 'Approved'",
                     (test_code, lg))
        if row:
            return f"{row['body']} {DISCUSS[lg]}"
    return None


def seed_starters(actor: str = "seed", approve_codes: tuple[str, ...] = ("K", "TSH", "HBA1C", "PLT", "NA", "CREAT")) -> int:
    n = 0
    for code, (en, hi) in STARTERS.items():
        for lang, body in (("en", en), ("hi", hi)):
            if not db.scalar("SELECT 1 FROM report_explainers WHERE test_code = ? AND lang = ?", (code, lang)):
                save(code, lang, body, actor)
                n += 1
        if code in approve_codes:
            for lang in ("en", "hi"):
                approve(code, lang, "user:Dr. Demo (seed)")
    return n
