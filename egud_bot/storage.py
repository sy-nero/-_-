"""
אחסון לידים ב-SQLite: מניעת כפילויות ומעקב אחר סטטוס שליחה.
"""
import os
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
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

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
                    primary_type, status, found_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(place_id) DO UPDATE SET
                    email=excluded.email,
                    status=excluded.status
                """,
                (
                    lead.place_id, lead.name, lead.address, lead.neighborhood,
                    lead.lat, lead.lng, lead.phone, lead.website, email,
                    lead.rating, lead.review_count, lead.business_status,
                    lead.primary_type, status, _now(),
                ),
            )

    def mark_emailed(self, place_id: str, success: bool, error: str = "") -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE leads SET status=?, error=?, emailed_at=?
                   WHERE place_id=?""",
                ("emailed" if success else "failed", error, _now(), place_id),
            )

    def leads_to_email(self, limit: int) -> list[sqlite3.Row]:
        """לידים עם מייל שעדיין לא נשלח אליהם."""
        with self._conn() as conn:
            return conn.execute(
                """SELECT * FROM leads
                   WHERE email IS NOT NULL AND email != ''
                     AND status IN ('found', 'no_email')
                   ORDER BY found_at ASC LIMIT ?""",
                (limit,),
            ).fetchall()

    def purge_non_business(self) -> list[str]:
        """מסיר מה-DB לידים שהם מוסדות (לפי שם או סוג), בלי סריקה מחדש."""
        from egud_bot.filters import is_excluded_by_name, EXCLUDED_TYPES
        removed = []
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT place_id, name, primary_type FROM leads"
            ).fetchall()
            for r in rows:
                if is_excluded_by_name(r["name"]) or r["primary_type"] in EXCLUDED_TYPES:
                    conn.execute("DELETE FROM leads WHERE place_id=?", (r["place_id"],))
                    removed.append(r["name"])
        return removed

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
