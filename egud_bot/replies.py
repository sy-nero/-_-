"""
בדיקת תשובות: מי מהנמענים כתב בחזרה.

השליחה יוצאת ב-SMTP, ולכן האפליקציה לא רואה מה נכנס לתיבה. כאן נכנסים
לאותה תיבה ב-IMAP, עם אותה סיסמת אפליקציה, ומחפשים מיילים שהגיעו
מכתובות שנשלח אליהן. לא נוגעים במיילים, רק קוראים כותרות (BODY.PEEK),
כך שהם נשארים "לא נקראו" בתיבה.

איפה מחפשים: בכל הדואר ולא רק בדואר הנכנס. תשובה שהועברה לארכיון, שסומנה
בתווית או שנמחקה מהדואר הנכנס היא עדיין תשובה, ובחיפוש ב-INBOX בלבד היא
פשוט לא נספרה.

תשובה מכתובת אחרת: לפעמים בעל העסק עונה מתיבה אחרת מזו שאליה שלחנו (מייל
המשרד הועבר לנייד, או שהשותף ענה). לכן תשובה ("Re:") שהנושא שלה הוא בדיוק
הנושא ששלחנו לנמען מסוים נספרת לנמען הזה, גם כשהכתובת שונה.
"""
import email
import imaplib
import logging
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime

logger = logging.getLogger(__name__)

# כתובות שהן לא תשובה של אדם: החזרות של מערכת הדואר
_SYSTEM = ("mailer-daemon@", "postmaster@", "no-reply@", "noreply@")


def imap_host_for(smtp_host: str) -> str:
    host = (smtp_host or "").strip().lower()
    if not host or "gmail" in host or "google" in host:
        return "imap.gmail.com"
    return host.replace("smtp.", "imap.", 1)


def _text(value) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:  # noqa: BLE001
        return value or ""


# מענה אוטומטי: לפי הכותרות הסטנדרטיות, ולפי ניסוחים נפוצים בנושא
_AUTO_SUBJECT = ("automatic reply", "auto reply", "autoreply", "out of office",
                 "מענה אוטומטי", "תשובה אוטומטית", "תודה שפניתם", "תודה על פנייתך",
                 "תודה על פנייתכם", "קיבלנו את פנייתך", "מחוץ למשרד")


def _is_auto(msg) -> bool:
    if (msg.get("Auto-Submitted") or "no").strip().lower() not in ("", "no"):
        return True
    if msg.get("X-Autoreply") or msg.get("X-Autorespond"):
        return True
    if (msg.get("Precedence") or "").strip().lower() in ("auto_reply", "bulk", "junk"):
        return True
    subject = _text(msg.get("Subject", "")).lower()
    return any(k in subject for k in _AUTO_SUBJECT)


#: קידומות של תשובה והעברה בנושא, בעברית ובאנגלית
_REPLY_PREFIX = re.compile(r"^\s*(re|fw|fwd|השב|תגובה|הועבר|העבר)\s*(\[\d+\])?\s*:\s*", re.I)


#: מילים בתחילת תשובה שמשמעותן "אל תשלחו לי יותר"
_REMOVE_WORDS = ("הסר", "הסירו", "להסיר", "תסירו", "תוריד", "תורידו", "הורידו", "הוריד",
                 "לא מעוניין", "לא מעוניינת", "לא מעוניינים", "אל תשלחו", "תפסיקו",
                 "unsubscribe", "remove")


def asks_removal(text: str) -> bool:
    """
    האם התשובה מבקשת להפסיק לשלוח. בודקים רק את מה שהנמען כתב, לפני הציטוט
    של המייל שלנו: אחרת "הסר" מתוך שורת ההסרה שלנו היה נספר כבקשה.
    """
    own = []
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith(">") or re.match(r"^(On .+wrote:|ב.+כתב.*:|-----Original|From:|מאת:)", s):
            break
        own.append(s)
    head = " ".join(own)[:400].lower()
    # מילה שלמה בלבד: "הסר" לא אמור להתאים ל"הסרטון"
    letters = "\u0590-\u05ffa-z"
    return any(re.search(rf"(?<![{letters}]){re.escape(w)}(?![{letters}])", head)
               for w in _REMOVE_WORDS)


def _plain_body(raw: bytes) -> str:
    msg = email.message_from_bytes(raw)
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_type() == "text/plain":
            try:
                return part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", "replace")
            except Exception:  # noqa: BLE001
                continue
    return ""


def normalize_subject(subject: str) -> tuple[str, bool]:
    """הנושא בלי Re:/Fwd: ובלי רווחים כפולים, והאם הייתה לו קידומת של תשובה."""
    text = _text(subject)
    was_reply = False
    while True:
        new = _REPLY_PREFIX.sub("", text, count=1)
        if new == text:
            break
        was_reply, text = True, new
    return re.sub(r"\s+", " ", text).strip().lower(), was_reply


def _all_mail(conn) -> str:
    """
    שם התיקייה "כל הדואר" ב-Gmail. השם משתנה לפי שפת הממשק ("[Gmail]/All
    Mail", "[Gmail]/כל הדואר"), ולכן מזהים אותה לפי הדגל \\All ולא לפי השם.
    בשרת שאין בו תיקייה כזו מחפשים ב-INBOX.
    """
    try:
        status, rows = conn.list()
    except imaplib.IMAP4.error:
        return "INBOX"
    for row in rows or []:
        line = row.decode("utf-8", "replace") if isinstance(row, bytes) else str(row)
        match = re.match(r'\((?P<flags>[^)]*)\)\s+(?:"[^"]*"|NIL)\s+(?P<name>.+)$', line)
        if match and "\\all" in match.group("flags").lower():
            return match.group("name").strip()
    return "INBOX"


def _fetch(conn, ids: list, query: str) -> list:
    """
    FETCH שלא נופל בגלל הודעה אחת. Gmail מחזיר לפעמים "System Error" על
    קבוצת הודעות (הודעה פגומה, עומס רגעי). אז מחלקים לחצאים עד שמגיעים
    להודעה הבעייתית, ומדלגים רק עליה.
    """
    if not ids:
        return []
    try:
        status, rows = conn.fetch(b",".join(ids), query)
        return rows if status == "OK" else []
    except imaplib.IMAP4.abort:
        raise   # החיבור נסגר: אין טעם להמשיך עליו
    except imaplib.IMAP4.error as exc:
        if len(ids) == 1:
            logger.warning("דילוג על הודעה %s: %s", ids[0], exc)
            return []
        mid = len(ids) // 2
        return _fetch(conn, ids[:mid], query) + _fetch(conn, ids[mid:], query)


def find_replies(sender: dict, recipients, since_days: int = 60,
                 subjects: dict | None = None) -> dict:
    """
    מחזיר {"replies": {נמען: (תאריך, נושא)}, "bounces": {נמען: סיבה}}.

    subjects: {נושא ששלחנו (מנורמל): נמען}. תשובה מכתובת אחרת עם אותו נושא
    נספרת לנמען הזה.

    תשובה = מייל שהגיע מכתובת של נמען. החזרה = הודעת מערכת (mailer-daemon)
    על נמען שהמייל אליו לא נמסר. Gmail שם את הכתובת בכותרת
    X-Failed-Recipients; אם היא חסרה, מחפשים את הכתובת בתחילת גוף ההודעה.
    sender: from_email / smtp_user / smtp_password / smtp_host.
    """
    wanted = {(r or "").strip().lower() for r in recipients if r}
    wanted = {w for w in wanted if w and not w.startswith(_SYSTEM)}
    out = {"replies": {}, "bounces": {}, "unsubscribes": set()}
    if not wanted:
        return out
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%d-%b-%Y")
    conn = imaplib.IMAP4_SSL(imap_host_for(sender.get("smtp_host")), 993)
    try:
        conn.login(sender.get("smtp_user") or sender["from_email"], sender["smtp_password"])
        status, _ = conn.select(_all_mail(conn), readonly=True)
        if status != "OK":
            conn.select("INBOX", readonly=True)
        own = {(sender.get("from_email") or "").strip().lower(),
               (sender.get("smtp_user") or "").strip().lower()} - {""}
        subjects = subjects or {}
        reply_ids = []
        status, data = conn.search(None, "SINCE", since)
        ids = (data[0] or b"").split() if status == "OK" else []
        system_ids = []
        for start in range(0, len(ids), 200):
            rows = _fetch(conn, ids[start:start + 200],
                          "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE X-FAILED-RECIPIENTS "
                          "AUTO-SUBMITTED X-AUTOREPLY X-AUTORESPOND PRECEDENCE)])")
            for row in rows:
                if not isinstance(row, tuple):
                    continue
                msg = email.message_from_bytes(row[1])
                senders = [a.strip().lower() for _, a in getaddresses([msg.get("From", "")])]
                if any(a.startswith(_SYSTEM) for a in senders):
                    failed = [a.strip().lower() for _, a in
                              getaddresses([msg.get("X-Failed-Recipients", "")])]
                    hits = [a for a in failed if a in wanted]
                    if hits:
                        for a in hits:
                            out["bounces"][a] = _text(msg.get("Subject", "")) or "המייל חזר"
                    else:
                        msg_id = row[0].split()[0]
                        system_ids.append(msg_id)
                    continue
                if _is_auto(msg):
                    continue   # מענה אוטומטי ("תודה שפניתם", "אני מחוץ למשרד") אינו תשובה
                if own & set(senders):
                    continue   # מייל שיצא מהתיבה עצמה (ב"כל הדואר" יש גם את הנשלחים)
                try:
                    when = parsedate_to_datetime(msg.get("Date")).astimezone(timezone.utc).isoformat()
                except Exception:  # noqa: BLE001
                    when = ""
                subject = _text(msg.get("Subject", ""))
                hits = [(a, subject) for a in senders if a in wanted]
                if not hits and subjects:
                    norm, was_reply = normalize_subject(subject)
                    target = subjects.get(norm) if was_reply else None
                    if target:
                        hits = [(target, f"{subject} (מהכתובת {senders[0] if senders else ''})")]
                for addr, note in hits:
                    reply_ids.append((addr, row[0].split()[0]))
                    prev = out["replies"].get(addr)
                    if not prev or when > prev[0]:
                        out["replies"][addr] = (when, note)
        # תשובות: קוראים את הגוף (רק של התשובות, לא של כל התיבה) ובודקים
        # אם הנמען ביקש שלא נפנה אליו שוב
        for addr, msg_id in reply_ids:
            rows = _fetch(conn, [msg_id], "(BODY.PEEK[])")
            raw = b"".join(r[1] for r in rows if isinstance(r, tuple))
            if raw and asks_removal(_plain_body(raw)):
                out["unsubscribes"].add(addr)
        # הודעות מערכת בלי כותרת: מחפשים את הכתובת בתחילת הגוף
        for msg_id in system_ids:
            rows = _fetch(conn, [msg_id], "(BODY.PEEK[TEXT]<0.6000>)")
            body = b"".join(r[1] for r in rows if isinstance(r, tuple)).decode(
                "utf-8", "replace").lower()
            for addr in wanted:
                if addr in body:
                    out["bounces"].setdefault(addr, "המייל חזר")
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    return out
