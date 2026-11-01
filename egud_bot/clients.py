"""
לקוחות, ארנק ומחירון.

כל לקוח הוא תיקייה נפרדת: הקמפיינים שלו, הנמענים שלו, והבדיקה מי כבר קיבל
מייל נעשית רק בתוך הקמפיינים שלו. כך אפשר לשלוח עבורו גם לכתובות ששלחנו
אליהן בקמפיינים שלנו.

הארנק נספר במיילים:
    יתרה = מיילים שנרכשו - מיילים שנשלחו + מיילים שחזרו
מייל שחזר (הכתובת לא קיימת) לא נגבה, ולכן הוא מחזיר מקום בארנק. השליחה
עוצרת כשהיתרה נגמרת.

הכסף שהלקוח שילם נרשם לצד המיילים שקיבל, כדי שיהיה תיעוד מלא.
"""
import json
import os
import secrets
from contextlib import contextmanager
from datetime import datetime, timezone

from egud_bot import db
from egud_bot.campaigns import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    contact     TEXT,
    email       TEXT,
    phone       TEXT,
    notes       TEXT,
    archived    INTEGER DEFAULT 0,
    created_at  TEXT
);

-- תנועות בארנק: רכישת חבילה, תוספת ידנית, תיקון. השליחות עצמן לא נרשמות
-- כאן: הן נספרות מהקמפיינים, כדי שהיתרה תהיה תמיד נכונה גם אחרי מייל שחזר.
CREATE TABLE IF NOT EXISTS wallet_tx (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id   INTEGER NOT NULL,
    kind        TEXT,
    emails      INTEGER DEFAULT 0,
    amount      REAL DEFAULT 0,
    note        TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT
);
"""

#: חבילות ברירת מחדל: (מיילים, מחיר בש"ח). נערכות בעמוד המחירון.
DEFAULT_PACKAGES = [(100, 90), (200, 160), (500, 350), (1000, 600)]
DEFAULT_PER_EMAIL = 1.0

TX_KINDS = {"package": "רכישת חבילה", "custom": "רכישה לפי מחיר מייל",
            "bonus": "מתנה / תיקון", "refund": "החזר כספי"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClientStore:
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

    # ---------- לקוחות ----------
    def all(self, include_archived: bool = False) -> list:
        where = "" if include_archived else "WHERE archived = 0"
        with self._conn() as conn:
            return conn.execute(f"SELECT * FROM clients {where} ORDER BY name").fetchall()

    def get(self, client_id):
        if not str(client_id or "").strip().isdigit():
            return None
        with self._conn() as conn:
            return conn.execute("SELECT * FROM clients WHERE id=?",
                                (int(client_id),)).fetchone()

    def create(self, name: str, **f) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO clients (name, contact, email, phone, notes, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (name.strip(), f.get("contact", ""), f.get("email", ""),
                 f.get("phone", ""), f.get("notes", ""), _now()))
            return cur.lastrowid

    def update(self, client_id: int, **f) -> None:
        allowed = {"name", "contact", "email", "phone", "notes", "archived"}
        sets = {k: v for k, v in f.items() if k in allowed}
        if not sets:
            return
        with self._conn() as conn:
            conn.execute(f"UPDATE clients SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
                         (*sets.values(), int(client_id)))

    # ---------- ארנק ----------
    def add_tx(self, client_id: int, kind: str, emails: int, amount: float, note: str = "") -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO wallet_tx (client_id, kind, emails, amount, note, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (int(client_id), kind, int(emails), float(amount), note.strip(), _now()))

    def delete_tx(self, tx_id: int) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM wallet_tx WHERE id=?", (int(tx_id),))

    def transactions(self, client_id: int) -> list:
        with self._conn() as conn:
            return conn.execute("SELECT * FROM wallet_tx WHERE client_id=? ORDER BY id DESC",
                                (int(client_id),)).fetchall()

    def purchased(self, client_id: int) -> dict:
        """{"emails": כמה מיילים נרכשו, "paid": כמה ש"ח שולמו}."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(emails),0) AS e, COALESCE(SUM(amount),0) AS a "
                "FROM wallet_tx WHERE client_id=?", (int(client_id),)).fetchone()
        return {"emails": int(row["e"] or 0), "paid": float(row["a"] or 0)}

    # ---------- הגדרות: מחירון ומפתח חיבור ----------
    def setting(self, key: str, default: str = "") -> str:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._conn() as conn:
            conn.execute("INSERT INTO settings (key, value) VALUES (?,?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def packages(self) -> list:
        try:
            data = json.loads(self.setting("packages") or "null")
            if data:
                return [(int(e), float(p)) for e, p in data]
        except (ValueError, TypeError):
            pass
        return list(DEFAULT_PACKAGES)

    def set_packages(self, packages: list) -> None:
        self.set_setting("packages", json.dumps(sorted(packages)))

    def per_email_price(self) -> float:
        try:
            return float(self.setting("per_email_price") or DEFAULT_PER_EMAIL)
        except ValueError:
            return DEFAULT_PER_EMAIL

    def api_token(self, create: bool = True) -> str:
        """המפתח שאיתו שיחת החיפוש שולחת רשימות ללוח. נוצר בפעם הראשונה."""
        token = self.setting("api_token") or os.getenv("IMPORT_TOKEN", "")
        if not token and create:
            token = self.new_api_token()
        return token

    def new_api_token(self) -> str:
        token = secrets.token_urlsafe(24)
        self.set_setting("api_token", token)
        return token
