"""
מטא-דאטה של קמפיינים — הלוח שמחליף את הגיליון.

כל קמפיין הוא עמודה בגיליון, וכל שורה בו ("נוסח", "קהל יעד", "כאב"...) היא
שדה עם שלושה ערכים: פרטים, הערות, והמלצות לשיפור. השדות נשמרים בטבלה
"ארוכה" (שורה לכל שדה) כדי שאפשר יהיה להוסיף שורות לגיליון בלי לשנות סכימה.

המספרים מחולקים לשניים:
  * נמדדים אוטומטית — כמות פניות, כמות פתיחות, הודעה חוזרת. נשלפים מ-DB
    הלידים לפי הקמפיין והנוסח, ולא ניתנים לעריכה ידנית.
  * ידניים — התאמה, פגישת מו"מ, הסכמה עקרונית, חתימה, הפניות בפועל. אלה
    שלבים שקורים בשיחה ולא במייל, ולכן מוזנים ביד.
"""
import os
from datetime import datetime, timezone
from contextlib import contextmanager

from egud_bot import db

DB_PATH = os.path.join(os.getenv("DATA_DIR", "data"), "campaigns.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    kind            TEXT DEFAULT 'email',   -- email | phone
    started_on      TEXT,                   -- שורת "תאריך"
    source_campaign TEXT,                   -- מאיזה DB לידים נמדד (agent/crm/...)
    variant         TEXT,                   -- איזה נוסח (a/b). ריק = הכול
    search_query    TEXT,                   -- תחום לחיפוש חופשי ("יועצים עסקיים")
    subject_tpl     TEXT,                   -- נושא המייל, עם מציני מקום
    body_tpl        TEXT,                   -- גוף המייל, עם מציני מקום
    position        INTEGER DEFAULT 0,
    archived        INTEGER DEFAULT 0,
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS campaign_fields (
    campaign_id INTEGER NOT NULL,
    field       TEXT NOT NULL,              -- שם השורה בגיליון
    value       TEXT DEFAULT '',            -- פרטים
    note        TEXT DEFAULT '',            -- הערות
    improve     TEXT DEFAULT '',            -- המלצות לשיפור
    PRIMARY KEY (campaign_id, field)
);
"""

# שורות התיאור (טקסט חופשי), לפי הסדר בגיליון
TEXT_FIELDS = [
    "נוסח",
    "קהל יעד",
    "מקום חיפוש",
    "מאפיין",
    "כאב",
    "הנעה לפעולה",
]

# שורות שנמדדות אוטומטית מהמיילים שנשלחו
AUTO_FIELDS = ["כמות פניות", "כמות פתיחות", "הודעה חוזרת"]

# שורות המשפך שממלאים ביד (קורות בשיחה, לא במייל)
MANUAL_FIELDS = ["התאמה", "פגישת מו\"מ", "הסכמה עקרונית", "חתימה", "הפניות בפועל"]

ALL_FIELDS = TEXT_FIELDS + AUTO_FIELDS + MANUAL_FIELDS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CampaignStore:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            # מיגרציה למאגר שנוצר לפני שהשדות האלה נוספו
            for column in ("search_query", "subject_tpl", "body_tpl"):
                try:
                    conn.execute(f"ALTER TABLE campaigns ADD COLUMN {column} TEXT")
                except Exception:  # noqa: BLE001 — העמודה כבר קיימת
                    pass

    @contextmanager
    def _conn(self):
        conn = db.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------- קמפיינים ----------
    def create(self, title: str, kind: str = "email", source_campaign: str = "",
               variant: str = "", started_on: str = "") -> int:
        with self._conn() as conn:
            position = conn.execute(
                "SELECT COALESCE(MAX(position), 0) + 1 FROM campaigns").fetchone()[0]
            cur = conn.execute(
                """INSERT INTO campaigns (title, kind, started_on, source_campaign,
                       variant, position, created_at) VALUES (?,?,?,?,?,?,?)""",
                (title.strip(), kind, started_on or datetime.now().strftime("%Y-%m-%d"),
                 source_campaign, variant, position, _now()))
            return cur.lastrowid

    def update(self, campaign_id: int, **fields) -> None:
        allowed = {"title", "kind", "started_on", "source_campaign", "variant",
                   "archived", "position", "search_query", "subject_tpl",
                   "body_tpl"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        clause = ", ".join(f"{k}=?" for k in sets)
        with self._conn() as conn:
            conn.execute(f"UPDATE campaigns SET {clause} WHERE id=?",
                         (*sets.values(), campaign_id))

    def delete(self, campaign_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM campaign_fields WHERE campaign_id=?", (campaign_id,))
            conn.execute("DELETE FROM campaigns WHERE id=?", (campaign_id,))

    def get(self, campaign_id: int):
        with self._conn() as conn:
            return conn.execute("SELECT * FROM campaigns WHERE id=?",
                                (campaign_id,)).fetchone()

    def all(self, include_archived: bool = False) -> list:
        where = "" if include_archived else "WHERE archived = 0"
        with self._conn() as conn:
            return conn.execute(
                f"SELECT * FROM campaigns {where} ORDER BY position, id").fetchall()

    # ---------- שדות ----------
    def fields(self, campaign_id: int) -> dict:
        """מחזיר {שם השורה: {'value':..,'note':..,'improve':..}} לכל השורות."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM campaign_fields WHERE campaign_id=?",
                (campaign_id,)).fetchall()
        stored = {r["field"]: dict(r) for r in rows}
        return {name: {"value": stored.get(name, {}).get("value", ""),
                       "note": stored.get(name, {}).get("note", ""),
                       "improve": stored.get(name, {}).get("improve", "")}
                for name in ALL_FIELDS}

    def set_field(self, campaign_id: int, field: str, value: str = "",
                  note: str = "", improve: str = "") -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO campaign_fields (campaign_id, field, value, note, improve)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(campaign_id, field) DO UPDATE SET
                       value=excluded.value, note=excluded.note,
                       improve=excluded.improve""",
                (campaign_id, field, value.strip(), note.strip(), improve.strip()))
