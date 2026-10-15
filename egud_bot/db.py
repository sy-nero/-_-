"""
שכבת חיבור למסד הנתונים: SQLite מקומי או Cloudflare D1.

למה בכלל: בענן (Render בתוכנית החינמית) מערכת הקבצים נמחקת בכל פריסה, ולכן
קובץ SQLite מקומי לא שורד. D1 היא SQLite מנוהלת של Cloudflare — אותו דיאלקט
SQL בדיוק, ולכן כל השאילתות בקוד עובדות בשתי הסביבות בלי שינוי.

איך זה עובד: אם מוגדרים D1_ACCOUNT_ID, D1_DATABASE_ID ו-D1_API_TOKEN, כל
שאילתה נשלחת ל-API של Cloudflare. אחרת נפתח קובץ SQLite מקומי כמו קודם.
כך פיתוח מקומי נשאר פשוט, ואותו קוד רץ בענן.

מגבלה שכדאי להכיר: כל שאילתה ב-D1 היא קריאת רשת. הקוד עושה הרבה שאילתות
קטנות, ולכן סריקה מול D1 איטית יותר מסריקה מול קובץ מקומי.
"""
import os
import re
import json
import sqlite3
import logging
import time
from contextlib import contextmanager

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://api.cloudflare.com/client/v4"
# (חיבור, קריאה). קצר בכוונה: הגדרת D1 שגויה חייבת להיכשל מהר ולא
# להשאיר בקשת HTTP תלויה עשרות שניות -- אחרת העמוד פשוט לא נטען.
TIMEOUT = (10, 30)
#: ניסיונות חוזרים כשהרשת מגמגמת (חיבור איטי מהבית, Wi-Fi שנרדם)
RETRIES = 4


def d1_configured() -> bool:
    return all(os.getenv(k) for k in
               ("D1_ACCOUNT_ID", "D1_DATABASE_ID", "D1_API_TOKEN"))


class Row(dict):
    """
    שורת תוצאה שמתנהגת גם כמילון וגם לפי מיקום, כמו sqlite3.Row —
    כדי שקוד קיים כמו row["name"] ו-fetchone()[0] ימשיך לעבוד.
    """

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class D1Cursor:
    def __init__(self, rows, meta):
        self._rows = [Row(r) for r in (rows or [])]
        self._i = 0
        self.lastrowid = (meta or {}).get("last_row_id")
        self.rowcount = (meta or {}).get("changes", -1)

    def fetchone(self):
        if self._i >= len(self._rows):
            return None
        row = self._rows[self._i]
        self._i += 1
        return row

    def fetchall(self):
        rows = self._rows[self._i:]
        self._i = len(self._rows)
        return rows

    def __iter__(self):
        return iter(self.fetchall())


def _idempotent(sql: str) -> bool:
    head = sql.lstrip()[:7].upper()
    if head.startswith(("SELECT", "PRAGMA")):
        return True
    if re.search(r"(\w+)\s*=\s*\1\s*\+", sql):      # open_count = open_count + 1
        return False
    if head.startswith("UPDATE") or head.startswith("DELETE"):
        return True
    upper = sql.upper()
    return head.startswith("INSERT") and ("ON CONFLICT" in upper or "OR IGNORE" in upper
                                          or "OR REPLACE" in upper)


class D1Connection:
    """מדמה את ממשק sqlite3.Connection שהקוד שלנו משתמש בו, מול D1 API."""

    def __init__(self, account_id: str, database_id: str, token: str,
                 session: requests.Session | None = None,
                 api_base: str = API_BASE):
        self.url = (f"{api_base}/accounts/{account_id}"
                    f"/d1/database/{database_id}/query")
        self.headers = {"Authorization": f"Bearer {token}",
                        "Content-Type": "application/json"}
        self.session = session or requests.Session()
        self.row_factory = None      # תמיד מחזירים Row; קיים לתאימות

    # ---------- ביצוע ----------
    def execute(self, sql: str, params=()) -> D1Cursor:
        payload = {"sql": sql, "params": [_bind(p) for p in (params or [])]}
        # בקשה שלא הגיעה לשרת (חיבור שנכשל) בטוח לשלוח שוב. בקשה שנתקעה
        # באמצע שולחים שוב רק כשהרצה כפולה לא משנה דבר: קריאה, או כתיבה
        # שקובעת ערך (UPDATE ... SET status=?, INSERT ... ON CONFLICT).
        # INSERT רגיל או ספירה (x = x + 1) עלולים להיכפל, ולכן לא חוזרים עליהם.
        safe = _idempotent(sql)
        for attempt in range(RETRIES):
            last = attempt + 1 == RETRIES
            try:
                resp = self.session.post(self.url, headers=self.headers,
                                         json=payload, timeout=TIMEOUT)
            except (requests.ConnectionError, requests.Timeout) as exc:
                sent = isinstance(exc, requests.ReadTimeout) or "aborted" in str(exc)
                if not last and (safe or not sent):
                    time.sleep(2 ** attempt)
                    continue
                raise sqlite3.OperationalError(f"D1 לא נגיש: {exc}") from exc
            except requests.RequestException as exc:
                raise sqlite3.OperationalError(f"D1 לא נגיש: {exc}") from exc
            # 429 = יותר מדי בקשות לחשבון Cloudflare בבת אחת; 5xx = תקלה רגעית.
            # הבקשה לא בוצעה, ולכן בטוח לנסות שוב אחרי המתנה.
            if (resp.status_code == 429 or resp.status_code >= 500) and not last:
                time.sleep(2 ** attempt + (3 if resp.status_code == 429 else 0))
                continue
            break

        try:
            data = resp.json()
        except ValueError as exc:
            raise sqlite3.OperationalError(
                f"D1 החזיר תשובה לא תקינה (קוד {resp.status_code})") from exc

        if not data.get("success"):
            message = "; ".join(e.get("message", "") for e in data.get("errors", []))
            # שגיאות סכימה (עמודה קיימת וכו') מגיעות כ-OperationalError,
            # כדי שהמיגרציות בקוד יתפסו אותן כמו ב-SQLite מקומי.
            raise sqlite3.OperationalError(message or f"שגיאת D1 (קוד {resp.status_code})")

        results = data.get("result") or []
        first = results[0] if results else {}
        return D1Cursor(first.get("results"), first.get("meta"))

    def executescript(self, script: str) -> None:
        """D1 מקבלת פקודה אחת בכל קריאה, ולכן מפצלים את הסקריפט."""
        for statement in _split_statements(script):
            self.execute(statement)

    def commit(self) -> None:
        return None       # ב-D1 כל שאילתה מבוצעת מיד

    def close(self) -> None:
        return None


def _bind(value):
    """D1 מקבלת רק טיפוסים בסיסיים ב-JSON."""
    if isinstance(value, bool):
        return 1 if value else 0
    if value is None or isinstance(value, (int, float, str)):
        return value
    return str(value)


def _split_statements(script: str) -> list:
    """מפצל סקריפט SQL לפקודות, בהתעלמות מהערות ומשורות ריקות."""
    out, current = [], []
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        if stripped.endswith(";"):
            out.append("\n".join(current).rstrip(";").strip())
            current = []
    if current:
        tail = "\n".join(current).strip()
        if tail:
            out.append(tail)
    return [s for s in out if s]


def connect(db_path: str):
    """
    מחזיר חיבור: D1 אם מוגדרת, אחרת קובץ SQLite מקומי.
    db_path נשמר לצורך המקומי; ב-D1 יש מסד אחד ולכן הנתיב אינו בשימוש.
    """
    if d1_configured():
        return D1Connection(os.environ["D1_ACCOUNT_ID"],
                            os.environ["D1_DATABASE_ID"],
                            os.environ["D1_API_TOKEN"])
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def connection(db_path: str):
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
