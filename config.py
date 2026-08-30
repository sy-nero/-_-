"""
טעינת הגדרות המערכת מקובץ .env
"""
import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


def _bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "y", "on", "כן")


@dataclass
class Config:
    # Google Places
    google_api_key: str = os.getenv("GOOGLE_MAPS_API_KEY", "")
    # מצב API: auto (ברירת מחדל) / new / legacy
    places_api_mode: str = os.getenv("PLACES_API_MODE", "auto")
    # כמה עמודי תוצאות למשוך לכל סוג עסק (רק ב-legacy; כל עמוד = עד 20 תוצאות)
    max_pages_per_type: int = int(os.getenv("MAX_PAGES_PER_TYPE", "1"))

    # Filtering
    max_review_count: int = int(os.getenv("MAX_REVIEW_COUNT", "0"))
    search_radius_meters: float = float(os.getenv("SEARCH_RADIUS_METERS", "700"))
    require_operational: bool = _bool(os.getenv("REQUIRE_OPERATIONAL"), True)

    # SMTP
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_use_ssl: bool = _bool(os.getenv("SMTP_USE_SSL"), False)
    from_email: str = os.getenv("FROM_EMAIL", "")
    from_name: str = os.getenv("FROM_NAME", "האיגוד")
    reply_to: str = os.getenv("REPLY_TO", "")

    # Email content
    association_name: str = os.getenv("ASSOCIATION_NAME", "איגוד העסקים החרדיים")
    # הכתובת שאליה יופנו הפניות
    contact_email: str = os.getenv("CONTACT_EMAIL", "cto@egud.org.il")
    # שם ותפקיד השולח (למייל אישי חתום)
    sender_name: str = os.getenv("SENDER_NAME", "יוסף חיים וייס")
    sender_title: str = os.getenv("SENDER_TITLE", "מנהל קשרי לקוחות")
    # קמפיין מ״א (משאבי אנוש): קישור הקורס
    course_url: str = os.getenv("COURSE_URL", "https://egud.org.il/content/courses")
    # Google Custom Search (לחיפוש אתר החברה בקמפיין מ״א) — אמין, לא נחסם
    google_search_key: str = os.getenv("GOOGLE_SEARCH_KEY", "")
    google_search_cx: str = os.getenv("GOOGLE_SEARCH_CX", "")
    # קמפיין מענק (grant): שולח נפרד (המייל האישי של מירי) — SMTP של Gmail
    grant_from_email: str = os.getenv("GRANT_FROM_EMAIL", "")
    grant_from_name: str = os.getenv("GRANT_FROM_NAME", "מירי בר לב")
    grant_smtp_user: str = os.getenv("GRANT_SMTP_USER", "")
    # סיסמת אפליקציה של Gmail (רווחים מוסרים אוטומטית)
    grant_smtp_password: str = os.getenv("GRANT_SMTP_PASSWORD", "").replace(" ", "")
    # קמפיין גיוס סוכנים (agent): נשלח אישית בשם מירי מסינרו — ראו docs/agents.md
    agent_from_email: str = os.getenv("AGENT_FROM_EMAIL", "cto@sy-nero.com")
    agent_from_name: str = os.getenv("AGENT_FROM_NAME", "מירי בר לב")
    agent_sender_title: str = os.getenv("AGENT_SENDER_TITLE", "מנהלת מחלקת הטכנולוגיה")
    agent_company: str = os.getenv("AGENT_COMPANY", "סינרו")
    agent_sender_phone: str = os.getenv("AGENT_SENDER_PHONE", "053419438")
    agent_smtp_user: str = os.getenv("AGENT_SMTP_USER", "")
    agent_smtp_password: str = os.getenv("AGENT_SMTP_PASSWORD", "").replace(" ", "")
    # ותק מינימלי לסוכן (מספר ביקורות — פרוקסי לוותק, ל-Places אין שנת ייסוד)
    agent_min_reviews: int = int(os.getenv("AGENT_MIN_REVIEWS", "3"))
    landing_page_url: str = os.getenv("LANDING_PAGE_URL", "https://example.co.il/register")
    unsubscribe_url: str = os.getenv("UNSUBSCRIBE_URL", "https://example.co.il/unsubscribe")
    # נתיב לקובץ הלוגו של האיגוד (PNG/JPG) שיוטמע במייל
    logo_path: str = os.getenv("LOGO_PATH", "assets/logo_white.png")

    # יעד איסוף: כמות מיילים שהסריקה תנסה לאסוף לפני עצירה
    target_emails: int = int(os.getenv("TARGET_EMAILS", "50"))

    # Safety / rate
    max_emails_per_run: int = int(os.getenv("MAX_EMAILS_PER_RUN", "50"))
    request_delay_seconds: float = float(os.getenv("REQUEST_DELAY_SECONDS", "1.0"))

    # Storage
    db_path: str = os.getenv("DB_PATH", "data/leads.db")

    # Landing
    flask_secret_key: str = os.getenv("FLASK_SECRET_KEY", "change-me")
    landing_port: int = int(os.getenv("LANDING_PORT", "5000"))

    def sender_for(self, campaign: str) -> tuple[str, str, str, str]:
        """מחזיר (from_email, from_name, smtp_user, smtp_password) לפי הקמפיין.
        agent נשלח בשם מירי מסינרו; שאר הקמפיינים (כולל grant) מכתובת האיגוד."""
        if campaign == "agent" and self.agent_from_email:
            return (self.agent_from_email, self.agent_from_name,
                    self.agent_smtp_user or self.smtp_user,
                    self.agent_smtp_password or self.smtp_password)
        return (self.from_email, self.sender_name, self.smtp_user, self.smtp_password)

    def validate_for_scan(self) -> list[str]:
        """מחזיר רשימת שגיאות קונפיגורציה עבור סריקה."""
        errors = []
        if not self.google_api_key:
            errors.append("חסר GOOGLE_MAPS_API_KEY")
        return errors

    def validate_for_email(self, campaign: str = "funding") -> list[str]:
        """מחזיר רשימת שגיאות קונפיגורציה עבור שליחת מייל (לפי שולח הקמפיין)."""
        from_email, _, smtp_user, smtp_password = self.sender_for(campaign)
        errors = []
        if not self.smtp_host:
            errors.append("חסר ערך SMTP: smtp_host")
        if not smtp_user:
            errors.append("חסר ערך SMTP: smtp_user (GRANT_/AGENT_SMTP_USER בקמפיינים ייעודיים)")
        if not smtp_password:
            errors.append("חסר ערך SMTP: smtp_password (GRANT_/AGENT_SMTP_PASSWORD בקמפיינים ייעודיים)")
        if not from_email:
            errors.append("חסר ערך SMTP: from_email (GRANT_/AGENT_FROM_EMAIL בקמפיינים ייעודיים)")
        return errors


config = Config()
