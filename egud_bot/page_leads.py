"""
פניות מעמודי נחיתה של הלוח (למשל /xray).

מי שלוחץ על הסרטון במייל מגיע לעמוד עם המזהה של המייל שלו (t=...), וכך
הפנייה נרשמת יחד עם העסק והקמפיין שממנו הגיעה. בלי המזהה (מי שנכנס
לעמוד ישירות) הפנייה נשמרת בלי שיוך.
"""
from contextlib import contextmanager
from datetime import datetime, timezone

from egud_bot import db
from egud_bot.campaigns import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS page_leads (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    page         TEXT,
    campaign_id  TEXT,
    track_id     TEXT,
    business     TEXT,
    email        TEXT,
    name         TEXT,
    phone        TEXT,
    topic        TEXT,
    created_at   TEXT
);
"""


class PageLeadStore:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        conn = db.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def add(self, **f) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO page_leads (page, campaign_id, track_id, business, email, "
                "name, phone, topic, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (f.get("page", ""), f.get("campaign_id", ""), f.get("track_id", ""),
                 f.get("business", ""), f.get("email", ""), f.get("name", ""),
                 f.get("phone", ""), f.get("topic", ""),
                 datetime.now(timezone.utc).isoformat()))

    def all(self) -> list:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM page_leads ORDER BY id DESC").fetchall()

    def tracks_for(self, campaign_id) -> set:
        """המזהים של מי שהשאיר פרטים מתוך קמפיין מסוים."""
        with self._conn() as conn:
            rows = conn.execute("SELECT track_id FROM page_leads WHERE campaign_id=? "
                                "AND track_id != ''", (str(campaign_id),)).fetchall()
        return {r["track_id"] for r in rows}
