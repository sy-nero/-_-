"""
אחסון לידים: מניעת כפילויות ומעקב אחר סטטוס שליחה.

עובד גם מול SQLite מקומי וגם מול Cloudflare D1 (ראו egud_bot/db.py). ב-D1
יש מסד אחד לכל הקמפיינים, ולכן שם הטבלה כולל את שם הקמפיין; מקומית נשמר
קובץ נפרד לכל קמפיין וטבלה בשם leads, כמו קודם.
"""
import os
import json
import glob
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager

from egud_bot import db
from egud_bot.filters import BusinessLead

def schema_for(leads: str, registrations: str, sent_log: str) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {leads} (
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
    types           TEXT,
    first_name      TEXT,
    intro_how       TEXT,
    intro_fact      TEXT,
    intro_why       TEXT,
    rec_json        TEXT,
    variant         TEXT,
    track_id        TEXT,
    opened_at       TEXT,
    open_count      INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'found',
    error           TEXT,
    found_at        TEXT,
    emailed_at      TEXT,
    replied_at      TEXT,
    reply_note      TEXT
);

CREATE TABLE IF NOT EXISTS {registrations} (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ref          TEXT,
    full_name    TEXT,
    business     TEXT,
    phone        TEXT,
    email        TEXT,
    message      TEXT,
    callback     INTEGER DEFAULT 0,
    created_at   TEXT
);

-- יומן שליחות: כתובת שקיבלה מייל לא תקבל שוב, גם אחרי מחיקת מאגר הלידים.
-- בעבר זה נשמר בקובץ טקסט; בענן קבצים נמחקים, ולכן זו טבלה.
CREATE TABLE IF NOT EXISTS {sent_log} (
    email      TEXT,
    campaign   TEXT,
    sent_at    TEXT,
    PRIMARY KEY (email, campaign)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _TableNames:
    """עוטף חיבור וממלא את שמות הטבלאות בשאילתות לפני הביצוע."""

    def __init__(self, conn, leads: str, registrations: str, sent_log: str):
        self._conn = conn
        self._names = {"leads": leads, "registrations": registrations,
                       "sent": sent_log}

    def _fill(self, sql: str) -> str:
        return sql.format(**self._names) if "{" in sql else sql

    def execute(self, sql, params=()):
        return self._conn.execute(self._fill(sql), params)

    def executescript(self, script):
        return self._conn.executescript(self._fill(script))

    def commit(self):
        return self._conn.commit()

    def close(self):
        return self._conn.close()


#: מאגרים שהסכימה שלהם כבר הוכנה בתהליך הזה. ריק בכל הפעלה מחדש, ולכן
#: מיגרציה חדשה עדיין רצה -- רק לא שוב ושוב באותה ריצה.
_PREPARED: set = set()


def _safe(name: str) -> str:
    """שם קמפיין -> סיומת חוקית לשם טבלה."""
    return "".join(c if c.isalnum() else "_" for c in (name or "x"))


class Storage:
    def __init__(self, db_path: str, campaign: str = "funding"):
        self.db_path = db_path
        self.campaign = campaign
        # ב-D1 כל הקמפיינים חולקים מסד אחד, ולכן שם הקמפיין נכנס לשם הטבלה
        suffix = f"_{_safe(campaign)}" if db.d1_configured() else ""
        self.leads = f"leads{suffix}"
        self.registrations = f"registrations{suffix}"
        self.sent_log = "sent_emails"

        # הכנת הסכימה היא 15 פקודות, וב-D1 כל אחת היא קריאת רשת. בלי הזיכרון
        # הזה כל יצירת Storage הייתה משלמת אותן שוב -- וטעינת הלוח, שיוצרת
        # Storage לכל קמפיין, הגיעה לעשרות שניות מול מסד בענן.
        key = (self.db_path, self.leads)
        if key not in _PREPARED:
            with self._conn() as conn:
                conn.executescript(schema_for(self.leads, self.registrations,
                                              self.sent_log))
                # מיגרציה: הוספת עמודות למאגר ישן (אם חסרות)
                for column in ("types", "first_name", "intro_how", "intro_fact",
                               "intro_why", "rec_json", "variant", "replied_at",
                               "reply_note", "track_id", "opened_at", "open_count"):
                    try:
                        conn.execute(
                            f"ALTER TABLE {self.leads} ADD COLUMN {column} TEXT")
                    except sqlite3.OperationalError:
                        pass  # העמודה כבר קיימת
            _PREPARED.add(key)

    @contextmanager
    def _conn(self):
        """
        מחזיר חיבור שממלא את שמות הטבלאות בשאילתה. שמות הטבלאות משתנים בין
        SQLite מקומי ל-D1 (שם יש מסד אחד לכל הקמפיינים), ולכן השאילתות
        בקוד כתובות עם {leads} / {registrations} והשם נכנס כאן.
        """
        conn = _TableNames(db.connect(self.db_path), self.leads,
                           self.registrations, self.sent_log)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------- לידים ----------
    def exists(self, place_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM {leads} WHERE place_id = ?", (place_id,)
            ).fetchone()
            return row is not None

    def upsert_lead(self, lead: BusinessLead, email: str | None, status: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO {leads} (place_id, name, address, neighborhood, lat, lng,
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
                "SELECT email FROM {leads} WHERE place_id=?", (place_id,)
            ).fetchone()
            email = row["email"] if row else None
            if email:
                conn.execute(
                    """UPDATE {leads} SET status=?, error=?, emailed_at=?
                       WHERE lower(email)=lower(?)""",
                    (status, error, _now(), email),
                )
            else:
                conn.execute(
                    """UPDATE {leads} SET status=?, error=?, emailed_at=?
                       WHERE place_id=?""",
                    (status, error, _now(), place_id),
                )

    def leads_to_email(self, limit: int) -> list[sqlite3.Row]:
        """
        לידים עם מייל שעדיין לא נשלח אליהם (ללא כפילויות מייל).
        מי שכבר שויך לנוסח כלשהו לא חוזר לרשימה — כך שתי הקבוצות נפרדות.
        """
        with self._conn() as conn:
            return conn.execute(
                """SELECT * FROM {leads}
                   WHERE email IS NOT NULL AND email != ''
                     AND status IN ('found', 'no_email')
                     AND (variant IS NULL OR variant = '')
                   GROUP BY lower(email)
                   ORDER BY found_at ASC LIMIT ?""",
                (limit,),
            ).fetchall()

    def pending_count(self) -> int:
        """
        כמה ממתינים לשליחה — ספירה ב-SQL ולא שליפה של השורות.

        הלוח קרא קודם את כל השורות רק כדי לספור אותן. מול D1 זו העברה של
        כל המאגר ברשת, לכל קמפיין בלוח בנפרד — ומשם הטעינה האיטית.
        """
        with self._conn() as conn:
            return conn.execute(
                """SELECT COUNT(DISTINCT lower(email)) FROM {leads}
                   WHERE email IS NOT NULL AND email != ''
                     AND status IN ('found', 'no_email')
                     AND (variant IS NULL OR variant = '')"""
            ).fetchone()[0]

    def leads_without_email(self, limit: int) -> list[sqlite3.Row]:
        """לידים שנסרקו אך לא נמצאה להם כתובת מייל — מועמדים להעשרה."""
        with self._conn() as conn:
            return conn.execute(
                """SELECT * FROM {leads}
                   WHERE (email IS NULL OR email = '')
                     AND status = 'no_email'
                   ORDER BY review_count DESC LIMIT ?""",
                (limit,),
            ).fetchall()

    def update_contact(self, place_id: str, email: str, website: str = "") -> None:
        """ממלא מייל (ואתר) לליד קיים ומחזיר אותו לרשימת השליחה."""
        with self._conn() as conn:
            conn.execute(
                """UPDATE {leads} SET email=?, website=COALESCE(NULLIF(?,''), website),
                   status='found' WHERE place_id=?""",
                (email, website, place_id))

    def set_variant(self, place_id: str, variant: str) -> None:
        """רושם איזה נוסח נשלח לליד — הבסיס להשוואה בין הקבוצות."""
        with self._conn() as conn:
            row = conn.execute("SELECT email FROM {leads} WHERE place_id=?",
                               (place_id,)).fetchone()
            email = row["email"] if row else None
            if email:   # אותה כתובת לא תקבל את הנוסח השני בטעות
                conn.execute("UPDATE {leads} SET variant=? WHERE lower(email)=lower(?)",
                             (variant, email))
            else:
                conn.execute("UPDATE {leads} SET variant=? WHERE place_id=?",
                             (variant, place_id))

    def set_track_id(self, place_id: str, track_id: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE {leads} SET track_id=? WHERE place_id=?",
                         (track_id, place_id))

    def mark_opened(self, track_id: str) -> bool:
        """רושם פתיחת מייל. מחזיר True אם זו הפתיחה הראשונה."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT place_id, opened_at FROM {leads} WHERE track_id=?",
                (track_id,)).fetchone()
            if not row:
                return False
            first = not row["opened_at"]
            conn.execute(
                """UPDATE {leads} SET opened_at=COALESCE(NULLIF(opened_at,''), ?),
                   open_count=COALESCE(open_count,0)+1 WHERE track_id=?""",
                (_now(), track_id))
            return first

    def variant_metrics(self, variant: str = "") -> dict:
        """נשלחו / נפתחו / השיבו — לנוסח מסוים או לקמפיין כולו."""
        where = "variant = ?" if variant else "variant IS NOT NULL AND variant != ''"
        params = (variant,) if variant else ()
        with self._conn() as conn:
            row = conn.execute(
                f"""SELECT COUNT(DISTINCT lower(email)) AS sent,
                       COUNT(DISTINCT CASE WHEN opened_at IS NOT NULL AND opened_at != ''
                             THEN lower(email) END) AS opened,
                       COUNT(DISTINCT CASE WHEN replied_at IS NOT NULL AND replied_at != ''
                             THEN lower(email) END) AS replied
                    FROM {self.leads} WHERE {where}""", params).fetchone()
            return {"sent": row["sent"], "opened": row["opened"],
                    "replied": row["replied"]}

    def lead_by_email(self, email: str):
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM {leads} WHERE lower(email)=lower(?) LIMIT 1",
                ((email or "").strip(),)).fetchone()

    def sent_leads(self, variant: str = "", limit: int = 500):
        """מי כבר קיבל מייל — לתצוגה באפליקציה."""
        where = "status='emailed'"
        params = []
        if variant:
            where += " AND variant=?"
            params.append(variant)
        params.append(limit)
        with self._conn() as conn:
            return conn.execute(
                f"""SELECT * FROM {self.leads} WHERE {where}
                    GROUP BY lower(email) ORDER BY emailed_at DESC LIMIT ?""",
                params).fetchall()

    #: מצבי הנמענים כפי שהם מוצגים באפליקציה, והתנאי שמגדיר כל אחד
    STATES = {
        "pending": ("ממתינים לשליחה",
                    "email IS NOT NULL AND email != '' "
                    "AND status IN ('found','no_email') "
                    "AND (variant IS NULL OR variant = '')"),
        "assigned": ("שויכו לנוסח וטרם נשלחו",
                     "email IS NOT NULL AND email != '' "
                     "AND status IN ('found','no_email') "
                     "AND variant IS NOT NULL AND variant != ''"),
        "emailed": ("כבר נשלח אליהם", "status = 'emailed'"),
        "failed": ("השליחה נכשלה", "status = 'failed'"),
        "no_email": ("בלי כתובת מייל", "email IS NULL OR email = ''"),
    }

    def leads_by_state(self, state: str, limit: int = 500):
        """הנמענים במצב מסוים — לתצוגת 'מי בדיוק' באפליקציה."""
        label_where = self.STATES.get(state)
        if not label_where:
            return []
        # אותו איחוד כתובות כמו בספירה, אחרת אורך הרשימה לא תואם למספר
        group = "place_id" if state == "no_email" else "lower(email)"
        with self._conn() as conn:
            return conn.execute(
                f"""SELECT * FROM {{leads}} WHERE {label_where[1]}
                    GROUP BY {group}
                    ORDER BY found_at DESC LIMIT ?""", (limit,)).fetchall()

    def state_counts(self) -> dict:
        """כמה נמענים בכל מצב — ההסבר למה 'ממתינים' קטן מ'עם מייל'."""
        out = {}
        with self._conn() as conn:
            for state, (label, where) in self.STATES.items():
                col = "DISTINCT lower(email)" if state != "no_email" else "*"
                out[state] = {
                    "label": label,
                    "count": conn.execute(
                        f"SELECT COUNT({col}) FROM {{leads}} WHERE {where}"
                    ).fetchone()[0],
                }
        return out

    def leads_with_phone(self, limit: int = 1000):
        """לידים שיש להם טלפון — לפנייה טלפונית. מי שאין לו מייל קודם."""
        with self._conn() as conn:
            return conn.execute(
                """SELECT * FROM {leads}
                   WHERE phone IS NOT NULL AND phone != ''
                   GROUP BY phone
                   ORDER BY CASE WHEN email IS NULL OR email = '' THEN 0 ELSE 1 END,
                            review_count DESC
                   LIMIT ?""", (limit,)).fetchall()

    def mark_replied(self, email: str, note: str = "") -> int:
        """רושם שהסוכן השיב (וטלפון/הערה אם יש). מחזיר כמה שורות עודכנו."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE {leads} SET replied_at=?, reply_note=? WHERE lower(email)=lower(?)",
                (_now(), note, (email or "").strip()))
            return cur.rowcount

    def funnel(self) -> dict:
        """מספרי המשפך הכלליים (לפני הפילוח לנוסחים)."""
        with self._conn() as conn:
            one = lambda q: conn.execute(q).fetchone()[0]  # noqa: E731
            return {
                "לידים ב-DB": one("SELECT COUNT(*) FROM {leads}"),
                "עם כתובת מייל": one(
                    "SELECT COUNT(*) FROM {leads} WHERE email IS NOT NULL AND email != ''"),
                "נמצאה עליהם המלצה": one(
                    "SELECT COUNT(*) FROM {leads} WHERE rec_json IS NOT NULL AND rec_json != ''"),
                "ממתינים לשליחה": one(
                    "SELECT COUNT(DISTINCT lower(email)) FROM {leads} "
                    "WHERE email IS NOT NULL AND email != '' "
                    "AND status IN ('found','no_email') "
                    "AND (variant IS NULL OR variant = '')"),
            }

    def variant_stats(self) -> list[sqlite3.Row]:
        """כמה נשלחו וכמה השיבו בכל נוסח — ההשוואה בין A ל-B."""
        with self._conn() as conn:
            return conn.execute(
                """SELECT variant,
                          COUNT(DISTINCT lower(email)) AS sent,
                          COUNT(DISTINCT CASE WHEN replied_at IS NOT NULL
                                AND replied_at != '' THEN lower(email) END) AS replied
                   FROM {leads}
                   WHERE variant IS NOT NULL AND variant != ''
                   GROUP BY variant ORDER BY variant""").fetchall()

    def replies(self) -> list[sqlite3.Row]:
        """מי השיב, מתי, ומה נרשם (טלפון/הערה)."""
        with self._conn() as conn:
            return conn.execute(
                """SELECT name, email, phone, variant, reply_note, replied_at FROM {leads}
                   WHERE replied_at IS NOT NULL AND replied_at != ''
                   GROUP BY lower(email) ORDER BY replied_at DESC""").fetchall()

    def purge_non_business(self) -> list[str]:
        """מסיר מה-DB כל מה שאינו חנות קמעונאית (מוסד/שירות/חברה/ערבי), בלי סריקה מחדש."""
        from egud_bot.filters import is_excluded_by_name, is_org_email, is_retail_shop
        removed = []
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT place_id, name, primary_type, types, email FROM {leads}"
            ).fetchall()
            for r in rows:
                types = (r["types"] or "").split(",") if r["types"] else []
                # שומרים רק חנות קמעונאית שאינה מוסד/ארגון
                if (not is_retail_shop(r["primary_type"], types)
                        or is_excluded_by_name(r["name"])
                        or is_org_email(r["email"])):
                    conn.execute("DELETE FROM {leads} WHERE place_id=?", (r["place_id"],))
                    removed.append(r["name"])
        return removed

    # ---------- יומן שליחות (שורד מחיקת מאגר הלידים) ----------
    # ההיסטוריה נשמרת בטבלה, כדי שתשרוד גם פריסה מחדש בענן. קובצי הטקסט
    # מהגרסה הקודמת ממשיכים להיקרא, כדי שלא נשלח שוב למי שכבר קיבל.
    def _legacy_log_path(self) -> str:
        name = ("sent_emails.txt" if self.campaign == "funding"
                else f"sent_{self.campaign}.txt")
        return os.path.join(os.path.dirname(self.db_path) or ".", name)

    @staticmethod
    def _read_log_file(path: str) -> set:
        if not os.path.exists(path):
            return set()
        with open(path, encoding="utf-8") as f:
            return {line.strip().lower() for line in f if line.strip()}

    def already_sent_emails(self) -> set:
        """כל כתובת שכבר קיבלה מייל בקמפיין הזה — מהטבלה ומהיומן הישן."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT email FROM {sent} WHERE campaign = ?",
                (self.campaign,)).fetchall()
        emails = {(r["email"] or "").lower() for r in rows}
        return emails | self._read_log_file(self._legacy_log_path())

    def contacted_any_campaign(self) -> set:
        """כל כתובת שקיבלה מייל באיזשהו קמפיין."""
        with self._conn() as conn:
            rows = conn.execute("SELECT email FROM {sent}").fetchall()
        emails = {(r["email"] or "").lower() for r in rows}
        base = os.path.dirname(self.db_path) or "."
        for path in glob.glob(os.path.join(base, "sent_*.txt")):
            emails |= self._read_log_file(path)
        return emails

    def record_sent(self, email: str) -> None:
        """רושם שכתובת קיבלה מייל, כדי שלא תקבל שוב לעולם."""
        email = (email or "").strip().lower()
        if not email:
            return
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO {sent} (email, campaign, sent_at) VALUES (?,?,?)
                   ON CONFLICT(email, campaign) DO UPDATE SET sent_at=excluded.sent_at""",
                (email, self.campaign, _now()))

    def stats(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) c FROM {leads} GROUP BY status"
            ).fetchall()
            return {r["status"]: r["c"] for r in rows}

    # ---------- הרשמות מדף הנחיתה ----------
    def add_registration(self, data: dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO {registrations}
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
