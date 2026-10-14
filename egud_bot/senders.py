"""
תיבות שליחה שמנוהלות מהדפדפן.

במקום להוסיף שורות ל-.env לכל תיבה (cto@, office@, וכו'), מגדירים אותן
פעם אחת בעמוד "תיבות שליחה", ובכל שליחה בוחרים מאיזו תיבה היא יוצאת.
הטבלה יושבת באותו מסד של הקמפיינים, ולכן היא זמינה מכל מחשב.

הסיסמה היא סיסמת אפליקציה של Google (לא הסיסמה הרגילה של התיבה). היא
נשמרת במסד ולא מוצגת שוב בדפדפן אחרי השמירה.
"""
from contextlib import contextmanager
from datetime import datetime, timezone

from egud_bot import db
from egud_bot.campaigns import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS senders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    label         TEXT,                      -- איך היא מופיעה ברשימה
    from_email    TEXT NOT NULL,             -- הכתובת שהנמען רואה
    from_name     TEXT,                      -- השם שהנמען רואה
    smtp_user     TEXT,                      -- ריק = כמו from_email
    smtp_password TEXT,                      -- סיסמת אפליקציה
    smtp_host     TEXT DEFAULT 'smtp.gmail.com',
    smtp_port     INTEGER DEFAULT 587,
    use_ssl       INTEGER DEFAULT 0,
    created_at    TEXT
);
"""


class SenderStore:
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

    def all(self) -> list:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM senders ORDER BY id").fetchall()

    def get(self, sender_id):
        if not str(sender_id or "").strip().isdigit():
            return None
        with self._conn() as conn:
            return conn.execute("SELECT * FROM senders WHERE id=?",
                                (int(sender_id),)).fetchone()

    def save(self, sender_id=None, **f) -> int:
        """יוצר או מעדכן. סיסמה ריקה בעדכון = להשאיר את הקיימת."""
        values = {
            "label": (f.get("label") or "").strip(),
            "from_email": (f.get("from_email") or "").strip(),
            "from_name": (f.get("from_name") or "").strip(),
            "smtp_user": (f.get("smtp_user") or "").strip(),
            "smtp_host": (f.get("smtp_host") or "").strip() or "smtp.gmail.com",
            "smtp_port": int(str(f.get("smtp_port") or "587").strip() or 587),
            "use_ssl": 1 if f.get("use_ssl") else 0,
        }
        # Google מציג את הסיסמה בקבוצות של ארבע עם רווחים
        password = (f.get("smtp_password") or "").replace(" ", "").strip()
        with self._conn() as conn:
            if self.get(sender_id):
                if password:
                    values["smtp_password"] = password
                clause = ", ".join(f"{k}=?" for k in values)
                conn.execute(f"UPDATE senders SET {clause} WHERE id=?",
                             (*values.values(), int(sender_id)))
                return int(sender_id)
            values["smtp_password"] = password
            values["created_at"] = datetime.now(timezone.utc).isoformat()
            cols = ", ".join(values)
            marks = ", ".join("?" for _ in values)
            cur = conn.execute(f"INSERT INTO senders ({cols}) VALUES ({marks})",
                               tuple(values.values()))
            return cur.lastrowid

    def delete(self, sender_id) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM senders WHERE id=?", (int(sender_id),))


def as_smtp(row) -> dict | None:
    """שורת תיבה -> ההגדרות שהשליחה צריכה. None אם אין שורה."""
    if not row:
        return None
    return {
        "from_email": row["from_email"],
        "from_name": row["from_name"] or "",
        "smtp_user": row["smtp_user"] or row["from_email"],
        "smtp_password": row["smtp_password"] or "",
        "smtp_host": row["smtp_host"] or "smtp.gmail.com",
        "smtp_port": int(row["smtp_port"] or 587),
        "use_ssl": bool(row["use_ssl"]),
    }


def missing(sender: dict) -> list[str]:
    """מה חסר כדי לשלוח מהתיבה."""
    errors = []
    if not sender.get("from_email"):
        errors.append("כתובת")
    if not sender.get("smtp_password"):
        errors.append("סיסמת אפליקציה")
    return errors
