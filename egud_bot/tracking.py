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


def has_pixel(html: str) -> bool:
    return PIXEL_COMMENT in (html or "")


# GIF שקוף בגודל 1x1 — מה שהשרת מחזיר לבקשת הפיקסל
TRANSPARENT_GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c000000"
    "000100010000020144003b"
)
