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

# מילים שמסמנות עמוד "צור קשר"/"אודות" בקישור עצמו. עדיף לעקוב אחרי
# הקישורים שבאתר מאשר לנחש נתיבים: אתרים ישראליים רבים משתמשים בכתובות
# בעברית ("/צור-קשר", "/אודות") שלא תמיד זהות לניחוש שלנו.
_CONTACT_WORDS = ("contact", "about", "kesher", "צור", "קשר", "אודות", "מי-אני",
                  "עלי", "amod", "צרו")
_MAX_FOLLOW = 3


def _contact_links(soup, base_url: str) -> list[str]:
    """קישורי צור-קשר/אודות שמופיעים בפועל בעמוד, לפי הטקסט או הכתובת."""
    found, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        haystack = (href + " " + a.get_text(" ", strip=True)).lower()
        if not any(w in haystack for w in _CONTACT_WORDS):
            continue
        url = urljoin(base_url, href)
        if urlparse(url).netloc != urlparse(base_url).netloc:
            continue                      # לא לצאת לדומיין אחר
        if url not in seen:
            seen.add(url)
            found.append(url)
        if len(found) >= _MAX_FOLLOW:
            break
    return found


def _name_tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[\s\-־,]+", (name or "").lower()) if len(t) >= 3]


def mentions_name(html_text: str, domain: str, name: str) -> bool:
    """
    האם האתר באמת שייך לעסק הזה.

    חיפוש לפי שם ועיר מחזיר לא פעם אתר מקרי שמדורג גבוה — moovitapp.com
    עבור "מרים רוטנמר", mada.org.il עבור "דוד סלאנים". בלי בדיקה כזאת
    היינו שולחים מייל לכתובת אקראית לגמרי.
    """
    tokens = _name_tokens(name)
    if not tokens:
        return True                       # אין על מה לאמת — לא פוסלים
    hay = (html_text or "").lower() + " " + (domain or "").lower()
    hits = [t for t in tokens if t in hay]
    if any(len(t) >= 4 for t in hits):
        return True
    return bool(hits) and len(hits) == len(tokens)

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


def _decode_cf_email(hex_str: str) -> str | None:
    """
    מפענח כתובת שהוסתרה ע"י Cloudflare Email Protection.

    האתר מציג "[email protected]" ומחביא את הכתובת האמיתית במחרוזת hex:
    הבייט הראשון הוא מפתח, וכל השאר הם התווים ב-XOR מולו. זו הגנה נפוצה
    מאוד באתרים ישראליים, ובלי פענוח הכתובת פשוט לא נראית בטקסט.
    """
    hex_str = (hex_str or "").strip().lstrip("#")
    if len(hex_str) < 4 or len(hex_str) % 2:
        return None
    try:
        key = int(hex_str[:2], 16)
        return "".join(chr(int(hex_str[i:i + 2], 16) ^ key)
                       for i in range(2, len(hex_str), 2))
    except ValueError:
        return None


def _cf_candidates(soup) -> list[str]:
    """כל הכתובות המוצפנות בעמוד, בשתי הצורות ש-Cloudflare מייצר."""
    out = []
    for el in soup.select("[data-cfemail]"):
        decoded = _decode_cf_email(el.get("data-cfemail", ""))
        if decoded:
            out.append(decoded)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "email-protection#" in href:
            decoded = _decode_cf_email(href.split("#", 1)[1])
            if decoded:
                out.append(decoded)
    return out


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

    # 2) כתובות שהוסתרו ע"י Cloudflare
    for candidate in _cf_candidates(soup):
        cleaned = _clean_email(candidate)
        if cleaned:
            return cleaned

    # 3) חיפוש טקסטואלי בגוף העמוד
    matches = EMAIL_RE.findall(soup.get_text(" "))
    for m in matches:
        cleaned = _clean_email(m)
        if cleaned:
            return cleaned
    return None


def find_email(website: str, request_delay: float = 1.0,
               expect_name: str = "") -> str | None:
    """
    מחזיר כתובת מייל מהאתר, או None אם לא נמצאה.

    expect_name — שם העסק. אם הוא לא מוזכר בעמוד הבית, האתר נפסל:
    סימן שהחיפוש החזיר אתר של מישהו אחר.
    """
    if not website:
        return None

    parsed = urlparse(website)
    if not parsed.scheme:
        website = "https://" + website

    session = requests.Session()
    domain = urlparse(website).netloc

    # עמוד הבית קודם: גם מאמת שהאתר שייך לעסק, וגם מספק את הקישורים
    # האמיתיים לעמודי צור-קשר/אודות במקום לנחש נתיבים.
    home_links = []
    reached = 0            # כמה עמודים הצלחנו באמת לקרוא
    problems = []
    home = None
    try:
        home = session.get(website, headers=HEADERS, timeout=15,
                           allow_redirects=True)
    except requests.RequestException as exc:
        # חלק מהאתרים מוגשים רק תחת www. כישלון חיבור לדומיין החשוף
        # אינו בהכרח אתר מת — שווה ניסיון אחד נוסף לפני שמוותרים.
        if not domain.startswith("www."):
            retry = website.replace("://" + domain, "://www." + domain, 1)
            logger.debug("ניסיון חוזר עם www: %s", retry)
            try:
                home = session.get(retry, headers=HEADERS, timeout=15,
                                   allow_redirects=True)
                website, domain = retry, "www." + domain
            except requests.RequestException:
                home = None
        if home is None:
            problems.append(f"/: {type(exc).__name__}")
            logger.debug("שגיאה בקריאת %s: %s", website, exc)

    try:
        if home is not None and home.status_code != 200:
            problems.append(f"/: קוד {home.status_code}")
        if home is not None and home.status_code == 200 and home.text:
            reached += 1
            soup = BeautifulSoup(home.text, "html.parser")
            if expect_name and not mentions_name(soup.get_text(" "), domain,
                                                 expect_name):
                logger.info("  ✖ %s לא מזכיר את %r — כנראה אתר של מישהו אחר",
                            domain, expect_name)
                return None
            email = _extract_from_html(home.text)
            if email:
                return email
            home_links = _contact_links(soup, website)
    except requests.RequestException as exc:
        problems.append(f"/: {type(exc).__name__}")
        logger.debug("שגיאה בעיבוד %s: %s", website, exc)

    for url in home_links:
        try:
            resp = session.get(url, headers=HEADERS, timeout=15,
                               allow_redirects=True)
            if resp.status_code == 200 and resp.text:
                reached += 1
                email = _extract_from_html(resp.text)
                if email:
                    return email
        except requests.RequestException as exc:
            logger.debug("שגיאה בקריאת %s: %s", url, exc)

    # גיבוי: ניחוש נתיבים, למקרה שאין באתר קישור מזוהה לצור-קשר.
    # reached ו-problems נצברים מלמעלה, כדי שההבחנה בין "אין מייל באתר"
    # לבין "לא הצלחנו בכלל להיכנס לאתר" תישאר נכונה.
    checked = {website} | set(home_links)
    for path in CONTACT_PATHS:
        url = urljoin(website, path) if path else website
        if url in checked:
            continue
        checked.add(url)
        try:
            resp = session.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
            if resp.status_code == 200 and resp.text:
                reached += 1
                email = _extract_from_html(resp.text)
                if email:
                    return email
            elif resp.status_code != 404:      # 404 על עמוד צור-קשר הוא רגיל
                problems.append(f"{path or '/'}: קוד {resp.status_code}")
        except requests.RequestException as exc:
            problems.append(f"{path or '/'}: {type(exc).__name__}")
            logger.debug("שגיאה בקריאת %s: %s", url, exc)
        # נבדוק רק את עמוד הבית + עמוד צור-קשר אחד אמיתי כדי לחסוך בקשות

    if not reached:
        logger.warning("לא הצלחנו לקרוא אף עמוד ב-%s (%s)",
                       website, "; ".join(problems[:3]) or "בלי פירוט")
    return None
