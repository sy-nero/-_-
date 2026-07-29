"""
מקור לקמפיין מ״א (משאבי אנוש).

הערה חשובה: סריקת אתרי דרושים (דרושים/AllJobs/JobMaster) לאיתור מייל של
המעסיק אינה אפשרית באמינות — התוכן נטען ב-JavaScript, המיילים של המעסיק
מוסתרים בכוונה (מועמדים פונים דרך הפלטפורמה), והדבר נוגד את תנאי השימוש.

לכן המקור המעשי הוא:
  1. אותו סורק חנויות קמעונאיות (Google Places) — כל חנות היא לקוח פוטנציאלי
     לקורס גיוס עובדים. זו ברירת המחדל.
  2. ייבוא רשימה מקובץ CSV שהמשתמש מספק (שם, מייל) — import_csv.
"""
import csv
import logging

from config import Config
from egud_bot.filters import BusinessLead
from egud_bot.storage import Storage

logger = logging.getLogger(__name__)


def scan_jobs(cfg: Config, storage: Storage, target_emails: int | None = None) -> dict:
    """
    אוסף עסקים לקמפיין מ״א. מכיוון שאיסוף מיילים מאתרי דרושים אינו אפשרי,
    המקור הוא סורק החנויות הקמעונאיות (Google Places) — קהל יעד לקורס הגיוס.
    """
    from egud_bot.pipeline import scan_retail
    logger.info("קמפיין מ״א: איסוף מיילים מאתרי דרושים אינו אפשרי (מוסתרים/JS/ToS). "
                "משתמש בסורק החנויות הקמעונאיות כמקור לקהל היעד.")
    return scan_retail(cfg, storage, target_emails=target_emails)


def import_csv(storage: Storage, path: str, email_col: str = "email",
               name_col: str = "name") -> int:
    """
    מייבא רשימת עסקים מקובץ CSV (עמודות name,email) ל-DB של הקמפיין.
    שימושי אם אספת ידנית עסקים שמגייסים. מחזיר כמה נוספו.
    """
    added = 0
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            email = (row.get(email_col) or "").strip()
            name = (row.get(name_col) or "").strip()
            if not email:
                continue
            pid = f"csv_{i}_{email.lower()}"
            if storage.exists(pid):
                continue
            lead = BusinessLead(
                place_id=pid, name=name or email, address="", lat=0.0, lng=0.0,
                phone=(row.get("phone") or "").strip(), website="", rating=None,
                review_count=0, business_status="OPERATIONAL", primary_type="",
                neighborhood="", types=[],
            )
            storage.upsert_lead(lead, email, status="found")
            added += 1
    logger.info("יובאו %d עסקים מ-%s", added, path)
    return added
