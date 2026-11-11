"""
מעקב פתיחות מייל — פיקסל שקוף בגוף ה-HTML.

איך זה עובד: לכל מייל שנשלח מוצמד מזהה אקראי, ובתחתית ה-HTML מוטמעת תמונה
בגודל פיקסל אחד שכתובתה מכילה את המזהה. כשתוכנת המייל של הנמען טוענת את
התמונה, השרת שלנו רושם פתיחה.

מגבלות שחשוב להכיר (ולא להתייחס למספר כאמת מוחלטת):
  * חלק גדול מתוכנות המייל חוסמות תמונות כברירת מחדל — פתיחה כזאת לא נספרת.
    כלומר המספר האמיתי גבוה ממה שנראה.
  * Gmail טוענת תמונות דרך שרת מטמון שלה, ולכן לפעמים נספרת "פתיחה" כשההודעה
    רק נסרקה, ולפעמים נספרות פתיחות חוזרות.
  * הכתובת חייבת להיות נגישה מהאינטרנט — פיקסל שמצביע ל-localhost לא ייטען
    אצל אף נמען, ואז לא תירשם אף פתיחה.
"""
import html as _html
import re
import secrets

PIXEL_COMMENT = "<!-- tracking pixel -->"


def new_track_id() -> str:
    """מזהה אקראי לכל מייל. לא ניתן לניחוש ולא חושף פרטים על הנמען."""
    return secrets.token_urlsafe(16)


def pixel_url(base_url: str, track_id: str) -> str:
    return f"{(base_url or '').rstrip('/')}/px/{track_id}.gif"


def add_pixel(html: str, base_url: str, track_id: str) -> str:
    """
    מטמיע את פיקסל המעקב לפני סגירת ה-body. בלי base_url מחזיר את ה-HTML
    כמו שהוא — עדיף מייל בלי מדידה מאשר מייל עם תמונה שבורה.
    """
    if not (base_url and track_id and html):
        return html
    img = (f'{PIXEL_COMMENT}<img src="{pixel_url(base_url, track_id)}" '
           f'width="1" height="1" alt="" style="display:block;border:0;'
           f'width:1px;height:1px;">')
    if "</body>" in html:
        return html.replace("</body>", f"{img}</body>", 1)
    return html + img


def click_url(base_url: str, track_id: str, link_id: int) -> str:
    return f"{(base_url or '').rstrip('/')}/c/{track_id}/{link_id}"


_CLICKS_OK: dict = {}


def clicks_supported(base_url: str) -> bool:
    """
    האם שירות המעקב כבר יודע להפנות לחיצות. גרסה ישנה של ה-Worker מחזירה
    פיקסל לכל כתובת, ואז קישור שעובר דרכו נפתח כדף ריק אצל הנמען. לכן
    בודקים פעם אחת לפני שליחה, ובלי תשובה ברורה הקישורים יוצאים כמו שהם.
    """
    base = (base_url or "").rstrip("/")
    if not base:
        return False
    if base not in _CLICKS_OK:
        try:
            import requests
            resp = requests.get(f"{base}/c/ping", timeout=10)
            _CLICKS_OK[base] = resp.status_code == 200 and resp.text.strip() == "clicks-ok"
        except Exception:  # noqa: BLE001
            return False      # לא שומרים: אולי זו תקלת רשת רגעית
    return _CLICKS_OK[base]


_HREF_RE = re.compile(r'(<a\b[^>]*?\bhref=")(https?://[^"]+)(")', re.I)


def add_click_tracking(html: str, base_url: str, track_id: str, link_id) -> str:
    """
    מעביר כל קישור במייל דרך שירות המעקב, כדי לספור מי לחץ. השירות רושם את
    הלחיצה ומפנה מיד לכתובת המקורית, כך שהנמען לא מרגיש בהבדל.

    link_id: פונקציה שמחזירה מספר קבוע לכל כתובת יעד (Storage.link_id).
    בלי base_url, או אם רישום הקישור נכשל, הקישור נשאר כמו שהוא: עדיף
    קישור שעובד בלי מדידה מאשר קישור שבור.
    """
    if not (base_url and track_id and html):
        return html

    def sub(match):
        url = _html.unescape(match.group(2))
        try:
            lid = link_id(url)
        except Exception:  # noqa: BLE001
            return match.group(0)
        return match.group(1) + click_url(base_url, track_id, lid) + match.group(3)

    return _HREF_RE.sub(sub, html)


def has_pixel(html: str) -> bool:
    return PIXEL_COMMENT in (html or "")


# GIF שקוף בגודל 1x1 — מה שהשרת מחזיר לבקשת הפיקסל
TRANSPARENT_GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c000000"
    "000100010000020144003b"
)
