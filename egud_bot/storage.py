"""
אחסון לידים ב-SQLite: מניעת כפילויות ומעקב אחר סטטוס שליחה.
"""
import os
import json
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager

from egud_bot.filters import BusinessLead

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    place_id        TEXT PRIMARY KEY,
    name            TEXT,
    address         TEXT,
    neighborhood    TEXT,
    lat             REAL,
    lng             REAL,
    phone           TEXT,
    website         TEXT,
    email           TEXT,
    rating          REAL,
    review_count    INTEGER,
    business_status TEXT,
    primary_type    TEXT,
    types           TEXT,                   -- כל סוגי Google, מופרדים בפסיק
    first_name      TEXT,                   -- שם פרטי לפנייה אישית (קמפיין agent)
    intro_how       TEXT,                   -- {{איך_הגעתי_אליו}} (קמפיין agent)
    intro_fact      TEXT,                   -- {{עובדה_קונקרטית_עליו}} (קמפיין agent)
    intro_why       TEXT,                   -- {{למה_דווקא_הוא}} (קמפיין agent)
    rec_json        TEXT,                   -- ההמלצה שנמצאה עליו + קישור לאימות
    status          TEXT DEFAULT 'found',   -- found | emailed | no_email | failed | skipped
    error           TEXT,
    found_at        TEXT,
    emailed_at      TEXT
);

CREATE TABLE IF NOT EXISTS registrations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ref          TEXT,          -- place_id שהגיע מהמייל (למי שייכת ההרשמה)
    full_name    TEXT,
    business     TEXT,
    phone        TEXT,
    email        TEXT,
    message      TEXT,
    callback     INTEGER DEFAULT 0,
    created_at   TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, db_path: str, campaign: str = "funding"):
        self.db_path = db_path
        self.campaign = campaign
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            # מיגרציה: הוספת עמודות ל-DB ישן (אם חסרות)
            for column in ("types", "first_name", "intro_how", "intro_fact",
                           "intro_why", "rec_json"):
                try:
                    conn.execute(f"ALTER TABLE leads ADD COLUMN {column} TEXT")
                except sqlite3.OperationalError:
                    pass  # העמודה כבר קיימת

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------- לידים ----------
    def exists(self, place_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM leads WHERE place_id = ?", (place_id,)
            ).fetchone()
            return row is not None

    def upsert_lead(self, lead: BusinessLead, email: str | None, status: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO leads (place_id, name, address, neighborhood, lat, lng,
                    phone, website, email, rating, review_count, business_status,
                    primary_type, types, first_name, intro_how, intro_fact,
                    intro_why, rec_json, status, found_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(place_id) DO UPDATE SET
                    email=excluded.email,
                    status=excluded.status
                """,
                (
                    lead.place_id, lead.name, lead.address, lead.neighborhood,
                    lead.lat, lead.lng, lead.phone, lead.website, email,
                    lead.rating, lead.review_count, lead.business_status,
                    lead.primary_type, ",".join(lead.types or []),
                    lead.first_name, lead.intro_how, lead.intro_fact,
                    lead.intro_why,
                    json.dumps(lead.rec, ensure_ascii=False) if lead.rec else "",
                    status, _now(),
                ),
            )

    def mark_emailed(self, place_id: str, success: bool, error: str = "") -> None:
        status = "emailed" if success else "failed"
        with self._conn() as conn:
            # מסמנים את כל הלידים עם אותה כתובת מייל, כדי לא לשלוח פעמיים לאותו אדם
            row = conn.execute(
                "SELECT email FROM leads WHERE place_id=?", (place_id,)
            ).fetchone()
            email = row["email"] if row else None
            if email:
                conn.execute(
                    """UPDATE leads SET status=?, error=?, emailed_at=?
                       WHERE lower(email)=lower(?)""",
                    (status, error, _now(), email),
                )
            else:
                conn.execute(
                    """UPDATE leads SET status=?, error=?, emailed_at=?
                       WHERE place_id=?""",
                    (status, error, _now(), place_id),
                )

    def leads_to_email(self, limit: int) -> list[sqlite3.Row]:
        """לידים עם מייל שעדיין לא נשלח אליהם (ללא כפילויות מייל)."""
        with self._conn() as conn:
            return conn.execute(
                """SELECT * FROM leads
                   WHERE email IS NOT NULL AND email != ''
                     AND status IN ('found', 'no_email')
                   GROUP BY lower(email)
                   ORDER BY found_at ASC LIMIT ?""",
                (limit,),
            ).fetchall()

    def purge_non_business(self) -> list[str]:
        """מסיר מה-DB כל מה שאינו חנות קמעונאית (מוסד/שירות/חברה/ערבי), בלי סריקה מחדש."""
        from egud_bot.filters import is_excluded_by_name, is_org_email, is_retail_shop
        removed = []
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT place_id, name, primary_type, types, email FROM leads"
            ).fetchall()
            for r in rows:
                types = (r["types"] or "").split(",") if r["types"] else []
                # שומרים רק חנות קמעונאית שאינה מוסד/ארגון
                if (not is_retail_shop(r["primary_type"], types)
                        or is_excluded_by_name(r["name"])
                        or is_org_email(r["email"])):
                    conn.execute("DELETE FROM leads WHERE place_id=?", (r["place_id"],))
                    removed.append(r["name"])
        return removed

    # ---------- יומן שליחות קבוע (שורד מחיקת DB) ----------
    def _sent_log_path(self) -> str:
        # יומן נפרד לכל קמפיין (funding שומר על השם ההיסטורי)
        name = "sent_emails.txt" if self.campaign == "funding" else f"sent_{self.campaign}.txt"
        return os.path.join(os.path.dirname(self.db_path) or ".", name)

    def already_sent_emails(self) -> set:
        """מחזיר את כל כתובות המייל שכבר נשלח אליהן אי־פעם (מיומן קבוע)."""
        path = self._sent_log_path()
        if not os.path.exists(path):
            return set()
        with open(path, encoding="utf-8") as f:
            return {line.strip().lower() for line in f if line.strip()}

    def contacted_any_campaign(self) -> set:
        """כל כתובת שקיבלה מייל באיזשהו קמפיין (איחוד כל קובצי sent_*.txt)."""
        import glob
        base = os.path.dirname(self.db_path) or "."
        emails = set()
        for path in glob.glob(os.path.join(base, "sent_*.txt")):
            with open(path, encoding="utf-8") as f:
                emails |= {line.strip().lower() for line in f if line.strip()}
        return emails

    def record_sent(self, email: str) -> None:
        """רושם כתובת ביומן הקבוע כדי שלעולם לא תקבל מייל פעמיים."""
        email = (email or "").strip().lower()
        if not email:
            return
        with open(self._sent_log_path(), "a", encoding="utf-8") as f:
            f.write(email + "\n")

    def stats(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) c FROM leads GROUP BY status"
            ).fetchall()
            return {r["status"]: r["c"] for r in rows}

    # ---------- הרשמות מדף הנחיתה ----------
    def add_registration(self, data: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO registrations
                   (ref, full_name, business, phone, email, message, callback, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    data.get("ref", ""),
                    data.get("full_name", ""),
                    data.get("business", ""),
                    data.get("phone", ""),
                    data.get("email", ""),
                    data.get("message", ""),
                    1 if data.get("callback") else 0,
                    _now(),
                ),
            )
