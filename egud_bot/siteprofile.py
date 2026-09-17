"""
מה העסק אומר על עצמו באתר שלו.

מייל שמתייחס למה שכתוב באתר של הנמען נקרא אחרת ממייל כללי. כאן מחלצים
מהאתר משפט קצר שמתאר את ההתמחות -- מתוך התיאור שהעסק עצמו כתב, ולא
מניסוח שלנו. אם לא נמצא משהו נקי, מחזירים מחרוזת ריקה: עדיף משפט בלי
ההתייחסות מאשר משפט שמייחס לנמען דבר שלא אמר.
"""
import re
import logging

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MAX_CHARS = 120

# ביטויים שיווקיים ריקים: אם זה כל מה שיש, אין על מה להתייחס
_FLUFF = (
    "ברוכים הבאים", "ברוך הבא", "דף הבית", "עמוד הבית", "home page",
    "welcome to", "אתר בבנייה", "לחץ כאן", "צור קשר", "קרא עוד",
    "untitled", "my site", "אתר חדש", "wix", "wordpress",
)
# מציינים שמובילים לתיאור העיסוק: מה שבא אחריהם הוא בדרך כלל ההתמחות
_LEAD_INS = ("מתמחה ב", "מתמחים ב", "עוסק ב", "עוסקים ב", "מלווה",
             "מלווים", "עוזר ל", "עוזרים ל", "specializing in", "helping")

_WS = re.compile(r"\s+")


def _clean(text: str) -> str:
    text = _WS.sub(" ", (text or "")).strip(" \t\n\r|-–—·•")
    return text


#: מספר טלפון, פקס או ת"ד -- נחלצו מהעמוד ונראים כמו תיאור אם לא בודקים
_DIGITS = re.compile(r"[\d\-()+.\s]{7,}")
_WORD = re.compile(r"[A-Za-z\u0590-\u05FF]{2,}")
MIN_WORDS = 4


def _is_fluff(text: str) -> bool:
    """
    האם הטקסט אינו תיאור עיסוק אמיתי.

    בבדיקה מול אתרים אמיתיים נחלץ "052-713-1429" כתיאור, והמייל היה
    יוצא עם 'ראיתי באתר שלך: "052-713-1429"'. לכן נפסלים גם מחרוזות
    שרובן ספרות וגם קטעים קצרים מכדי להיות משפט.
    """
    low = text.lower()
    if len(text) < 12 or any(f in low for f in _FLUFF):
        return True
    words = _WORD.findall(text)
    if len(words) < MIN_WORDS:
        return True
    # רובו ספרות וסימנים: טלפון, פקס, כתובת
    digits = sum(1 for c in text if c.isdigit())
    return digits > len(text) / 3 or bool(_DIGITS.fullmatch(text))


def _trim(text: str, business_name: str = "") -> str:
    """
    מקצר לכדי משפט אחד, ומוריד את שם העסק מההתחלה.

    כותרות אתרים בנויות לרוב "שם העסק | מה הוא עושה", ורק החלק השני
    מעניין אותנו.
    """
    text = _clean(text)
    if not text:
        return ""

    # "שם העסק | ייעוץ עסקי לעצמאים" -> החלק הארוך והמתאר מבין השניים
    parts = [_clean(p) for p in re.split(r"\s*[|–—]\s*|\s+[-]\s+", text)]
    parts = [p for p in parts if p]
    if len(parts) > 1:
        name_low = (business_name or "").lower()
        described = [p for p in parts
                     if not (name_low and p.lower() in name_low)]
        if described:
            text = max(described, key=len)

    # משפט ראשון בלבד
    text = re.split(r"(?<=[.!?])\s+", text)[0]
    if len(text) > MAX_CHARS:
        cut = text[:MAX_CHARS].rsplit(" ", 1)[0]
        text = cut
    return _clean(text)


def specialty_from_html(html: str, business_name: str = "") -> str:
    """
    משפט אחד שמתאר במה העסק מתמחה, בניסוח של העסק עצמו.

    סדר העדיפויות הוא לפי כמה הטקסט נכתב בכוונה לתאר את העסק: קודם
    משפט שפותח ב"מתמחה ב...", אחר כך התיאור הרשמי (meta description),
    אחר כך הכותרת הראשית, ולבסוף כותרת הדף.
    """
    try:
        soup = BeautifulSoup(html or "", "html.parser")
    except Exception:                                   # noqa: BLE001
        return ""

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    candidates = []

    # 1) התיאור הרשמי שהעסק כתב לעצמו. זה הטקסט הכי מכוון לתאר את
    # העסק, ולכן הוא ראשון -- קטע מגוף העמוד עלול להיות שבר משפט
    # שיווקי שנתלש מהקשרו.
    for attrs in ({"name": "description"}, {"property": "og:description"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            candidates.append(tag["content"])

    # 2) משפט מפורש על ההתמחות, בגוף העמוד
    body_text = _clean(soup.get_text(" "))
    for lead_in in _LEAD_INS:
        idx = body_text.find(lead_in)
        if idx != -1:
            candidates.append(body_text[idx:idx + MAX_CHARS * 2])
            break

    # 3) הכותרת הראשית בעמוד, ואז כותרת הדף
    h1 = soup.find("h1")
    if h1:
        candidates.append(h1.get_text(" "))
    if soup.title and soup.title.string:
        candidates.append(soup.title.string)

    for raw in candidates:
        text = _trim(raw, business_name)
        if text and not _is_fluff(text):
            return text
    return ""
