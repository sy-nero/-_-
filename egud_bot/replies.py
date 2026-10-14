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
    מחזיר {"replies": {נמען: (תאריך, נושא)}, "bounces": {נמען: סיבה}}.

    תשובה = מייל שהגיע מכתובת של נמען. החזרה = הודעת מערכת (mailer-daemon)
    על נמען שהמייל אליו לא נמסר. Gmail שם את הכתובת בכותרת
    X-Failed-Recipients; אם היא חסרה, מחפשים את הכתובת בתחילת גוף ההודעה.
    sender: from_email / smtp_user / smtp_password / smtp_host.
    """
    wanted = {(r or "").strip().lower() for r in recipients if r}
    wanted = {w for w in wanted if w and not w.startswith(_SYSTEM)}
    out = {"replies": {}, "bounces": {}}
    if not wanted:
        return out
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%d-%b-%Y")
    conn = imaplib.IMAP4_SSL(imap_host_for(sender.get("smtp_host")), 993)
    try:
        conn.login(sender.get("smtp_user") or sender["from_email"], sender["smtp_password"])
        conn.select("INBOX", readonly=True)
        status, data = conn.search(None, "SINCE", since)
        ids = (data[0] or b"").split() if status == "OK" else []
        system_ids = []
        for start in range(0, len(ids), 200):
            chunk = b",".join(ids[start:start + 200])
            status, rows = conn.fetch(
                chunk, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE X-FAILED-RECIPIENTS)])")
            if status != "OK":
                continue
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
                for addr in senders:
                    if addr in wanted:
                        try:
                            when = parsedate_to_datetime(msg.get("Date")).isoformat()
                        except Exception:  # noqa: BLE001
                            when = ""
                        prev = out["replies"].get(addr)
                        if not prev or when > prev[0]:
                            out["replies"][addr] = (when, _text(msg.get("Subject", "")))
        # הודעות מערכת בלי כותרת: מחפשים את הכתובת בתחילת הגוף
        for msg_id in system_ids:
            status, rows = conn.fetch(msg_id, "(BODY.PEEK[TEXT]<0.6000>)")
            if status != "OK":
                continue
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
