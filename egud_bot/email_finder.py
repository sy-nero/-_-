"""
איתור כתובת מייל מאתר האינטרנט של העסק.

Google Places לא מחזיר מייל, לכן אנחנו נכנסים לאתר של העסק (אם יש)
ומחפשים כתובת מייל בעמוד הבית ובעמודי "צור קשר" נפוצים.
"""
import re
import logging
from urllib.parse import urljoin, urlparse, unquote
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
# ולידציה מלאה של כתובת (בלי %, בלי רווחים) — לאחר ניקוי
EMAIL_STRICT_RE = re.compile(r"^[a-zA-Z0-9._+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

# סיומות קבצים שאינן מיילים אמיתיים (מסננים false positives)
_IGNORE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js")
# דומיינים של תמונות/דוגמאות שכדאי לפסול
_IGNORE_DOMAINS = ("example.com", "sentry.io", "wixpress.com", "godaddy.com")

CONTACT_PATHS = ["", "/contact", "/contact-us", "/about", "/צור-קשר", "/אודות", "/קשר"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; EgudBot/1.0; +https://example.co.il/bot)"
    )
}


def _clean_email(email: str) -> str | None:
    # פענוח %20 וכד', והסרת רווחים/סימנים מיותרים בקצוות
    email = unquote(email).strip().strip(".").strip().lower()
    # ולידציה קפדנית — פוסל כתובות עם רווחים/תווים לא חוקיים
    if not EMAIL_STRICT_RE.match(email):
        return None
    if any(email.endswith(suf) for suf in _IGNORE_SUFFIXES):
        return None
    domain = email.split("@")[-1]
    if any(bad in domain for bad in _IGNORE_DOMAINS):
        return None
    return email


def _extract_from_html(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    # 1) קישורי mailto: — האמינים ביותר
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            candidate = href[7:].split("?")[0]
            cleaned = _clean_email(candidate)
            if cleaned:
                return cleaned

    # 2) חיפוש טקסטואלי בגוף העמוד
    matches = EMAIL_RE.findall(soup.get_text(" "))
    for m in matches:
        cleaned = _clean_email(m)
        if cleaned:
            return cleaned
    return None


def find_email(website: str, request_delay: float = 1.0) -> str | None:
    """מחזיר כתובת מייל מהאתר, או None אם לא נמצאה."""
    if not website:
        return None

    parsed = urlparse(website)
    if not parsed.scheme:
        website = "https://" + website

    session = requests.Session()
    checked = set()
    for path in CONTACT_PATHS:
        url = urljoin(website, path) if path else website
        if url in checked:
            continue
        checked.add(url)
        try:
            resp = session.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
            if resp.status_code == 200 and resp.text:
                email = _extract_from_html(resp.text)
                if email:
                    return email
        except requests.RequestException as exc:
            logger.debug("שגיאה בקריאת %s: %s", url, exc)
        # נבדוק רק את עמוד הבית + עמוד צור-קשר אחד אמיתי כדי לחסוך בקשות
    return None
