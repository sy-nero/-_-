"""
בדיקה שמייל כנראה קיים, לפני ששולחים אליו.

מייל שחוזר (bounce) פוגע במוניטין של תיבת השליחה, ושיעור החזרות גבוה גורם
ל-Gmail להתחיל לשים את כל המיילים שלנו בספאם, גם את הטובים. לכן מסננים:

1. דומיין שאין לו שרת דואר (רשומת MX) או שבכלל לא קיים.
2. ספקי אינטרנט ישנים שרוב התיבות בהם כבר נסגרו (נטוויז'ן, 013, אינטר וכו').
   לפי הנתונים שלנו: 25% עד 40% מהמיילים אליהם חזרו.
3. כתובת שכבר חזרה אלינו בקמפיין קודם.

מה שאי אפשר לבדוק מראש: תיבת Gmail שנסגרה. הדומיין קיים, ורק Gmail עצמו
יודע אם התיבה קיימת.
"""
import json
import logging
import urllib.parse

import requests

logger = logging.getLogger(__name__)

#: ספקים ישנים: שיעור ההחזרות אצלנו (אוקטובר 2026) בסוגריים
RISKY_DOMAINS = {
    "netvision.net.il",   # 25%
    "inter.net.il",       # 40%
    "barak.net.il",       # 40%
    "barak-online.net",
    "013.net",            # 33%
    "013.net.il",
    "013net.net",
    "017.net.il",         # 20%
    "014.net",
    "smile.net.il",
    "isdn.net.il",
    "actcom.co.il",
    "internet-zahav.net",
    "nonstop.net.il",
}

#: טעויות הקלדה נפוצות בדומיין, ומה התכוונו
TYPO_DOMAINS = {
    "gail.com": "gmail.com", "gmial.com": "gmail.com", "gmai.com": "gmail.com",
    "gamil.com": "gmail.com", "gmail.co": "gmail.com", "gmail.co.il": "gmail.com",
    "gmaill.com": "gmail.com", "gamail.com": "gmail.com", "gnail.com": "gmail.com",
    "walla.co": "walla.co.il", "wala.co.il": "walla.co.il", "walls.co.il": "walla.co.il",
    "netvison.net.il": "netvision.net.il", "bezeqint.co.il": "bezeqint.net",
    "bezeqint.net.il": "bezeqint.net", "hotmail.co": "hotmail.com",
}

_MX_CACHE: dict = {}


def fix_typo(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email:
        return email
    user, domain = email.rsplit("@", 1)
    return f"{user}@{TYPO_DOMAINS.get(domain, domain)}"


def _dns(name: str, rtype: str):
    """שאילתת DNS דרך HTTPS (Cloudflare): עובד גם כשאין גישה ישירה ל-DNS."""
    url = ("https://cloudflare-dns.com/dns-query?name=" + urllib.parse.quote(name)
           + "&type=" + rtype)
    resp = requests.get(url, headers={"accept": "application/dns-json"}, timeout=10)
    data = json.loads(resp.text)
    return data.get("Status"), data.get("Answer") or []


def domain_accepts_mail(domain: str):
    """True / False, או None כשאי אפשר לבדוק (אין רשת): אז לא פוסלים."""
    domain = domain.lower()
    if domain in _MX_CACHE:
        return _MX_CACHE[domain]
    try:
        status, answer = _dns(domain, "MX")
        if status == 3:               # NXDOMAIN: הדומיין לא קיים בכלל
            ok = False
        elif any(a.get("type") == 15 for a in answer):
            # MX "." (null MX) = הדומיין מצהיר שהוא לא מקבל דואר
            ok = not all(a.get("data", "").strip().endswith(" .") for a in answer
                         if a.get("type") == 15)
        else:
            # בלי MX דואר נמסר לכתובת הדומיין עצמו (A), אם יש כזו
            _, a_answer = _dns(domain, "A")
            ok = any(a.get("type") == 1 for a in a_answer)
    except (requests.RequestException, ValueError) as exc:
        logger.warning("בדיקת הדומיין %s נכשלה: %s", domain, exc)
        return None
    _MX_CACHE[domain] = ok
    return ok


def check(email: str, bounced: set = frozenset()) -> str:
    """מחזיר "" אם אפשר לשלוח, אחרת את הסיבה בעברית."""
    email = (email or "").strip().lower()
    if email in bounced:
        return "המייל כבר חזר בקמפיין קודם"
    domain = email.rsplit("@", 1)[-1]
    if domain in RISKY_DOMAINS:
        return f"ספק ישן ({domain}), רוב התיבות בו נסגרו"
    if domain_accepts_mail(domain) is False:
        return f"הדומיין {domain} לא מקבל מיילים"
    return ""
