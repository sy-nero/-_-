"""
העלאת רשימת נמענים מקובץ, עם כל הבדיקות שנעשו עד היום ביד.

לפני שכתובת נכנסת לקמפיין בודקים:
  1. שהכתובת תקינה (ומתקנים טעויות הקלדה נפוצות: gmial.com וכו').
  2. שהיא לא מופיעה פעמיים בקובץ.
  3. שלא שלחנו אליה אף פעם, באף קמפיין.
  4. שהיא לא ממתינה כבר בקמפיין אחר (אחרת תקבל שני מיילים שונים).
  5. שהיא לא חזרה אלינו בעבר, ולא ביקשה להסיר אותה.
  6. שהיא לא תיבת גיוס/מערכת (jobs@, cv@, noreply@).
  7. שהדומיין מקבל מיילים ואינו ספק ישן שרוב התיבות בו נסגרו.

מה שלא עבר נרשם עם הסיבה, כדי שיהיה אפשר לראות בדיוק למה.
"""
import csv
import glob
import io
import logging
import os
import re
from datetime import datetime, timezone

from egud_bot import db, emailcheck

logger = logging.getLogger(__name__)

#: שמות עמודות אפשריים בקובץ (באותיות קטנות, בלי רווחים מסביב)
COLUMNS = {
    "name": ("שם העסק", "שם", "עסק", "name", "business", "business name", "company"),
    "email": ("מייל", "אימייל", "דוא\"ל", "דואל", "email", "e-mail", "mail"),
    "phone": ("טלפון", "נייד", "phone", "mobile", "tel"),
    "first_name": ("שם_פרטי", "שם פרטי", "first_name", "first name", "איש קשר"),
    "city": ("עיר", "city", "יישוב", "ישוב"),
    "group": ("קבוצה", "תחום", "סוג", "קטגוריה", "group", "category", "field"),
    "website": ("אתר", "website", "site", "url"),
    # איפה מצאנו את העסק ("אינדקס העסקים של מודיעין עילית"), ל-{{מקור}} בנוסח
    "found_where": ("איפה מצאנו", "איפה_מצאנו", "מקור_פנייה", "מקור הפנייה", "נמצא ב",
                    "found_where", "found at"),
}

#: תיבות שלא מגיעות למי שמחליט בעסק
ROLE_BOXES = ("jobs", "job", "cv", "careers", "career", "hr", "noreply", "no-reply",
              "donotreply", "mailer-daemon", "postmaster")

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


# ---------------------------- קריאת הקובץ ----------------------------
def read_table(filename: str, data: bytes) -> list[dict]:
    """שורות מקובץ CSV או Excel (xlsx), כמילונים לפי שורת הכותרות."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm")):
        try:
            import openpyxl
        except ImportError as exc:
            raise ValueError("קובצי Excel עוד לא נתמכים במחשב הזה. "
                             "באקסל: קובץ, שמירה בשם, CSV UTF-8") from exc
        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sheet = book.worksheets[0]
        rows = [["" if v is None else str(v).strip() for v in r]
                for r in sheet.iter_rows(values_only=True)]
        rows = [r for r in rows if any(r)]
        if not rows:
            return []
        head = rows[0]
        return [dict(zip(head, r)) for r in rows[1:]]
    if not name.endswith((".csv", ".txt")):
        raise ValueError("אפשר להעלות קובץ CSV או Excel (xlsx)")
    for enc in ("utf-8-sig", "cp1255"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("utf-8", "replace")
    sample = text[:4000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return list(csv.DictReader(io.StringIO(text), dialect=dialect))


def map_columns(headers) -> dict:
    """{שדה: שם העמודה בקובץ}. עמודה שלא זוהתה פשוט לא נכנסת."""
    norm = {(h or "").strip().lower(): h for h in headers if h}
    out = {}
    for field, names in COLUMNS.items():
        for n in names:
            if n in norm and norm[n] not in out.values():
                out[field] = norm[n]
                break
    if "email" not in out:
        # עמודה בלי כותרת מוכרת שרוב הערכים בה נראים כמו מייל
        for h in headers:
            if h and "@" in h:
                out["email"] = h
    return out


def clean_name(name: str) -> str:
    """
    שם עסק כמו שהוא נשמע בפנייה: בלי בע"מ, בלי מספרי טלפון, ובלי תיאור
    אחרי מקף ("רהיטי ברזילי - חדרי ילדים ונוער" -> "רהיטי ברזילי").
    """
    n = re.sub(r'\s*בע"?מ\s*', " ", name or "")
    n = re.sub(r"\s*\([^)]*\)", "", n)
    n = re.sub(r"\s*[–-]?\s*\b[A-Za-z]?\d{6,}\b", "", n)
    parts = [p.strip() for p in re.split(r"\s+[-–|]\s+|\s*\|\s*", n) if p.strip()]
    if parts:
        n = parts[0] if len(parts[0]) >= 3 else " ".join(parts[:2])
    return re.sub(r"\s+", " ", n).strip(' "-–')


# ---------------------------- מה כבר ידוע ----------------------------
def _lead_connections(data_dir: str):
    """
    (חיבור, טבלה, מזהה) לכל מאגר לידים. ב-D1 יש מסד אחד וטבלה לכל קמפיין,
    ומקומית קובץ לכל קמפיין עם טבלה בשם leads, ולכן המזהה הוא שם הטבלה
    או נתיב הקובץ.
    """
    if db.d1_configured():
        conn = db.connect("x")
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                              "AND name LIKE 'leads_%'").fetchall():
            yield conn, r["name"], r["name"]
        return
    for path in glob.glob(os.path.join(data_dir, "*.db")):
        conn = db.connect(path)
        try:
            ok = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                              "AND name='leads'").fetchone()
        except Exception:  # noqa: BLE001
            ok = None
        if ok:
            yield conn, "leads", os.path.abspath(path)


def own_key(storage) -> str:
    """המזהה של מאגר הקמפיין שאליו מעלים, באותה צורה של _lead_connections."""
    return storage.leads if db.d1_configured() else os.path.abspath(storage.db_path)


def known_addresses(data_dir: str, own: str = "", scope=None, sent_keys=None) -> dict:
    """
    {"sent": מי שקיבל מייל, "pending": {מייל: טבלה}, "own": מי שכבר ברשימה
    של הקמפיין הזה, "bounced", "unsubscribed"}.

    own: המזהה של מאגר הקמפיין שאליו מעלים (own_key).
    scope: אילו מאגרים נחשבים (סט של מזהים). לקוח בודק כפילויות רק מול
    הקמפיינים שלו, ולכן אפשר לשלוח עבורו גם למי שקיבל מאיתנו מייל. None = הכל.
    sent_keys: שמות הקמפיינים ביומן השליחות (sent_emails) ששייכים לאותו תחום.
    כתובת שחזרה נחשבת בכל מקרה: היא לא קיימת, אצל אף אחד.
    """
    sent, bounced, pending, unsub, mine = set(), set(), {}, set(), set()
    log_done = False
    for conn, table, key in _lead_connections(data_dir):
        in_scope = scope is None or key in scope or key == own
        try:
            rows = conn.execute(
                f"SELECT lower(email) AS e, status, bounced_at FROM {table} "
                "WHERE email IS NOT NULL AND email != ''").fetchall()
        except Exception as exc:  # noqa: BLE001
            logger.warning("לא הצלחתי לקרוא את %s: %s", table, exc)
            continue
        for r in rows:
            if r["bounced_at"]:
                bounced.add(r["e"])
            if not in_scope:
                continue
            if r["status"] == "emailed":
                sent.add(r["e"])
            elif r["status"] in ("found", "no_email"):
                if key == own:
                    mine.add(r["e"])
                else:
                    pending.setdefault(r["e"], table)
        if log_done and db.d1_configured():
            continue   # ב-D1 יומן השליחות ורשימת ההסרה משותפים: קוראים פעם אחת
        log_done = True
        try:
            for x in conn.execute("SELECT email, campaign FROM sent_emails").fetchall():
                if x["email"] and (sent_keys is None or x["campaign"] in sent_keys):
                    sent.add(x["email"].lower())
        except Exception:  # noqa: BLE001 — מאגר ישן בלי הטבלה
            pass
        try:
            unsub.update(x["email"].lower() for x in
                         conn.execute("SELECT email FROM unsubscribed").fetchall() if x["email"])
        except Exception:  # noqa: BLE001
            pass
    return {"sent": sent, "pending": pending, "own": mine, "bounced": bounced,
            "unsubscribed": unsub}


def key_for(source: str, path: str) -> str:
    """המזהה של מאגר הלידים של קמפיין (כמו ב-_lead_connections)."""
    if db.d1_configured():
        return "leads_" + "".join(c if c.isalnum() else "_" for c in (source or "x"))
    return os.path.abspath(path)


def campaign_titles(store) -> dict:
    """{טבלת לידים: שם הקמפיין}, כדי לכתוב "ממתין בקמפיין X" ולא שם טבלה."""
    out = {}
    for c in store.all():
        src = c["source_campaign"] or ""
        if src:
            out[f"leads_{src}"] = f"{c['id']}. {c['title']}"
            out.setdefault("leads", c["title"])
    return out


# ---------------------------- הייבוא ----------------------------
def check_address(email: str, known: dict, seen: set) -> tuple[str, str]:
    """(הכתובת אחרי תיקון, סיבה לא להכניס או "")."""
    email = emailcheck.fix_typo(re.sub(r"[^\w.@+-]", "", (email or "").lower()))
    if not email:
        return email, "אין כתובת מייל"
    if not _EMAIL_RE.match(email):
        return email, "כתובת לא תקינה"
    if email in seen:
        return email, "מופיע פעמיים בקובץ"
    if email.split("@")[0] in ROLE_BOXES:
        return email, "תיבת גיוס או מערכת, לא של מי שמחליט"
    if email in known["unsubscribed"]:
        return email, "ביקש להסיר אותו"
    if email in known.get("own", ()):
        return email, "כבר ברשימה של הקמפיין הזה"
    if email in known["sent"]:
        return email, "כבר קיבל מאיתנו מייל"
    if email in known["pending"]:
        return email, "pending:" + known["pending"][email]
    reason = emailcheck.check(email, known["bounced"])
    if reason:
        return email, reason
    return email, ""


def import_contacts(storage, rows: list[dict], prefix: str, known: dict,
                    default_group: str = "") -> dict:
    """
    מכניס את מי שעבר את הבדיקות למאגר של הקמפיין (status='found').
    מחזיר {"added": [...], "skipped": [{name, email, reason}], "columns": {...}}.
    """
    headers = list(rows[0].keys()) if rows else []
    cols = map_columns(headers)
    added, skipped, seen = [], [], set()
    now = datetime.now(timezone.utc).isoformat()
    batch = []
    for row in rows:
        def get(field):
            col = cols.get(field)
            return str(row.get(col) or "").strip() if col else ""

        raw_name = get("name")
        email, reason = check_address(get("email"), known, seen)
        name = clean_name(raw_name) or raw_name or email
        if reason:
            skipped.append({"name": raw_name or email, "email": email, "reason": reason})
            continue
        seen.add(email)
        first = get("first_name") or "-"
        batch.append((f"{prefix}:{email}", name, get("city"), get("phone"),
                      get("website"), email, "", first,
                      get("group") or default_group, get("found_where"), now))
        added.append({"name": name, "email": email, "group": get("group") or default_group})

    with storage._conn() as conn:
        for i in range(0, len(batch), 9):      # D1: עד 100 משתנים בשאילתה
            chunk = batch[i:i + 9]
            conn.execute(
                "INSERT INTO {leads} (place_id,name,address,phone,website,email,specialty,"
                "first_name,primary_type,intro_how,lat,lng,review_count,status,source,found_at) VALUES "
                + ",".join(["(?,?,?,?,?,?,?,?,?,?,0,0,0,'found','manual',?)"] * len(chunk))
                + " ON CONFLICT(place_id) DO NOTHING",
                [v for t in chunk for v in t])
    logger.info("ייבוא: נוספו %d, דולגו %d", len(added), len(skipped))
    return {"added": added, "skipped": skipped, "columns": cols}


def add_test_address(storage, email: str, business_name: str, first_name: str,
                     campaign_key: str) -> None:
    """
    כתובת בדיקה (המייל של מירי): נכנסת גם אם כבר קיבלה מייל, ומסומנת
    "בדיקה פנימית" כדי שלא תיספר בתוצאות. אם כבר נשלחה בקמפיין הזה, היא
    חוזרת לממתינים כדי שאפשר יהיה לשלוח בדיקה נוספת.
    """
    email = (email or "").strip().lower()
    pid = f"manual:test:{email}"
    now = datetime.now(timezone.utc).isoformat()
    with storage._conn() as conn:
        conn.execute(
            "INSERT INTO {leads} (place_id,name,address,phone,website,email,specialty,"
            "first_name,primary_type,lat,lng,review_count,status,source,found_at) "
            "VALUES (?,?,'','','',?,'',?,'בדיקה פנימית',0,0,0,'found','manual',?) "
            "ON CONFLICT(place_id) DO UPDATE SET name=excluded.name, "
            "first_name=excluded.first_name, status='found', emailed_at=NULL, "
            "track_id=NULL, opened_at=NULL, clicked_at=NULL, replied_at=NULL, "
            "reply_note=NULL, campaign_id=NULL",
            (pid, business_name or "בדיקת מייל", email, first_name or "-", now))
        conn.execute("DELETE FROM {sent} WHERE lower(email)=? AND campaign=?",
                     (email, campaign_key))
