"""
בדיקת תשובות: מי מהנמענים כתב בחזרה.

השליחה יוצאת ב-SMTP, ולכן האפליקציה לא רואה מה נכנס לתיבה. כאן נכנסים
לאותה תיבה ב-IMAP, עם אותה סיסמת אפליקציה, ומחפשים מיילים שהגיעו
מכתובות שנשלח אליהן. לא נוגעים במיילים, רק קוראים כותרות (BODY.PEEK),
כך שהם נשארים "לא נקראו" בתיבה.
"""
import email
import imaplib
import logging
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


def find_replies(sender: dict, recipients, since_days: int = 60) -> dict:
    """
    מחזיר {כתובת נמען: (תאריך, נושא)} לכל נמען שכתב לתיבה של השולח.
    sender: from_email / smtp_user / smtp_password / smtp_host.
    """
    wanted = {(r or "").strip().lower() for r in recipients if r}
    wanted = {w for w in wanted if w and not w.startswith(_SYSTEM)}
    if not wanted:
        return {}
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%d-%b-%Y")
    found = {}
    conn = imaplib.IMAP4_SSL(imap_host_for(sender.get("smtp_host")), 993)
    try:
        conn.login(sender.get("smtp_user") or sender["from_email"], sender["smtp_password"])
        conn.select("INBOX", readonly=True)
        status, data = conn.search(None, "SINCE", since)
        ids = (data[0] or b"").split() if status == "OK" else []
        for start in range(0, len(ids), 200):
            chunk = b",".join(ids[start:start + 200])
            status, rows = conn.fetch(chunk, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if status != "OK":
                continue
            for row in rows:
                if not isinstance(row, tuple):
                    continue
                msg = email.message_from_bytes(row[1])
                for _, addr in getaddresses([msg.get("From", "")]):
                    addr = addr.strip().lower()
                    if addr in wanted:
                        try:
                            when = parsedate_to_datetime(msg.get("Date")).isoformat()
                        except Exception:  # noqa: BLE001
                            when = ""
                        prev = found.get(addr)
                        if not prev or when > prev[0]:
                            found[addr] = (when, _text(msg.get("Subject", "")))
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    return found
