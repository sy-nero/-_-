"""
תבניות המייל, לפי קמפיין:
  funding — מימון (פנייה אישית לחנות קמעונאית).
  hr      — משאבי אנוש (קורס וכנס לגיוס עובדים).
  crm     — מערכת CRM בתנאי האיגוד.
  grant   — מענק מחשוב 4.56.
  agent   — גיוס סוכנים ממליצים (רו"ח, מאמנים עסקיים) — ראו docs/agents.md.

הגישה בכל המקרים: מייל קצר ואנושי, בלי עיצוב כבד. ל-hr יש שני כפתורים
(רכישת הקורס + הרשמה לכנס במייל).
"""
import re
from urllib.parse import quote

from egud_bot import recommendations
from data.neighborhoods import city_of

# מיפוי סוג העסק (Google type) לשם עברי (לקמפיין המימון)
FIELD_NOUNS = {
    "bakery": "מאפייה", "restaurant": "מסעדה", "cafe": "בית קפה",
    "clothing_store": "חנות בגדים", "grocery_store": "מכולת",
    "convenience_store": "מרכול", "hair_care": "מספרה",
    "beauty_salon": "מכון יופי", "book_store": "חנות ספרים",
    "electronics_store": "חנות אלקטרוניקה", "furniture_store": "חנות רהיטים",
    "jewelry_store": "חנות תכשיטים", "shoe_store": "חנות נעליים",
    "hardware_store": "חנות כלי עבודה", "florist": "חנות פרחים",
    "gift_shop": "חנות מתנות", "pharmacy": "בית מרקחת", "laundry": "מכבסה",
    # עסקי שירות/מקצוע (קמפיין CRM)
    "lawyer": "משרד עורכי דין", "accounting": "משרד רואי חשבון",
    "real_estate_agency": "משרד תיווך", "insurance_agency": "סוכנות ביטוח",
    "travel_agency": "סוכנות נסיעות", "moving_company": "חברת הובלות",
    "dentist": "מרפאת שיניים", "doctor": "מרפאה",
    "physiotherapist": "קליניקת פיזיותרפיה", "veterinary_care": "מרפאה וטרינרית",
    "car_repair": "מוסך", "car_dealer": "סוכנות רכב", "spa": "ספא",
    "gym": "חדר כושר", "locksmith": "מנעולן",
}


def field_noun(primary_type: str) -> str:
    return FIELD_NOUNS.get((primary_type or "").lower(), "")


def _saw_clause(field: str = "", neighborhood: str = "") -> str:
    if field and neighborhood:
        return f", וראיתי שיש לכם {field} ב{neighborhood}."
    if field:
        return f", וראיתי שיש לכם {field}."
    if neighborhood:
        return f", וראיתי שהעסק שלכם ב{neighborhood}."
    return "."


# ------------------------- קמפיין: מימון -------------------------
def _funding(business_name, association_name, sender_name, sender_title,
             field="", neighborhood="", **_):
    saw = _saw_clause(field, neighborhood)
    subject = (f"{business_name}, לגבי מימון לעסק" if business_name
               else "לגבי מימון לעסק שלכם")
    text = (
        f"שלום,\n\n"
        f"שמי {sender_name}, מ{association_name}.\n\n"
        f"אנחנו מארגנים עכשיו קבוצה של בעלי עסקים מהמגזר החרדי בשביל להשיג מימון "
        f"בתנאים טובים{saw}\n\n"
        f"עם מי אפשר לדבר על זה אצלכם? אם זה מעניין אתכם, תשיבו לי לכאן עם שם וטלפון "
        f"ואחזור אליכם.\n\n"
        f"תודה,\n{sender_name}\n{association_name}\n"
    )
    p = "margin:0 0 14px;"
    html = f"""<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;padding:0;background:#ffffff;">
  <div dir="rtl" style="direction:rtl;text-align:right;max-width:600px;margin:0 auto;
       padding:22px 20px;font-family:Arial,Helvetica,sans-serif;font-size:16px;
       line-height:1.75;color:#222222;">
    <p style="{p}">שלום,</p>
    <p style="{p}">שמי {sender_name}, מ{association_name}.</p>
    <p style="{p}">אנחנו מארגנים עכשיו קבוצה של בעלי עסקים מהמגזר החרדי בשביל להשיג
      מימון בתנאים טובים{saw}</p>
    <p style="{p}">עם מי אפשר לדבר על זה אצלכם? אם זה מעניין אתכם, תשיבו לי לכאן עם
      שם וטלפון ואחזור אליכם.</p>
    <p style="margin:0 0 4px;">תודה,</p>
    <p style="margin:0;">{sender_name}<br>{association_name}</p>
  </div>
</body></html>"""
    return subject, html, text


# ------------------------- קמפיין: משאבי אנוש (מ״א) -------------------------
def _hr(business_name, association_name, sender_name, sender_title,
        contact_email="", course_url="", place_id="", **_):
    sep = "&" if "?" in course_url else "?"
    course_link = f"{course_url}{sep}ref={quote(place_id or '')}&src=hr"

    subject = (f"{business_name}, מחפשים עובד? יש לנו קורס וכנס"
               if business_name else "מחפשים עובד? קורס וכנס לבעלי עסקים")
    text = (
        f"שלום,\n\n"
        f"שמי {sender_name}, מ{association_name}.\n\n"
        f"ראינו שאתם עדיין מחפשים עובד חדש לעסק. גיוס של עובד טוב הוא מהמשימות "
        f"הכי חשובות (והכי מתישות) לבעל עסק.\n\n"
        f"לכן ארגנו קורס וכנס לבעלי עסקים: איך למצוא, לגייס ולשמור עובדים טובים, "
        f"בלי לבזבז זמן וכסף.\n\n"
        f"לרכישת הקורס:\n{course_link}\n\n"
        f"ולהרשמה לכנס, פשוט השיבו למייל הזה עם שם וטלפון ונחזור אליכם.\n\n"
        f"תודה,\n{sender_name}\n{association_name}\n"
    )
    p = "margin:0 0 14px;"
    html = f"""<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;padding:0;background:#ffffff;">
  <div dir="rtl" style="direction:rtl;text-align:right;max-width:600px;margin:0 auto;
       padding:22px 20px;font-family:Arial,Helvetica,sans-serif;font-size:16px;
       line-height:1.75;color:#222222;">
    <p style="{p}">שלום,</p>
    <p style="{p}">שמי {sender_name}, מ{association_name}.</p>
    <p style="{p}">ראינו שאתם עדיין מחפשים עובד חדש לעסק. גיוס של עובד טוב הוא
      מהמשימות הכי חשובות (והכי מתישות) לבעל עסק.</p>
    <p style="{p}">לכן ארגנו <strong>קורס וכנס</strong> לבעלי עסקים: איך למצוא,
      לגייס ולשמור עובדים טובים, בלי לבזבז זמן וכסף.</p>
    <p style="{p}">לרכישת הקורס, היכנסו לקישור:<br>
      <a href="{course_link}" target="_blank"
         style="color:#1a2e4a;">{course_url}</a></p>
    <p style="{p}">ולהרשמה לכנס, פשוט השיבו למייל הזה עם שם וטלפון ונחזור אליכם.</p>
    <p style="margin:0 0 4px;">תודה,</p>
    <p style="margin:0;">{sender_name}<br>{association_name}</p>
  </div>
</body></html>"""
    return subject, html, text


# ------------------------- קמפיין: מערכת CRM -------------------------
# מחירי הקבוצה (ניתן לעדכן כאן). "רגיל" מול "בתנאי האיגוד".
CRM_REGULAR = "3,500 ש\"ח הקמה + 150 ש\"ח לחודש"
CRM_DEAL = "1,500 ש\"ח הקמה + 50 ש\"ח לחודש"


def _crm(business_name, association_name, sender_name, sender_title,
         field="", neighborhood="", **_):
    saw = _saw_clause(field, neighborhood)
    subject = (f"{business_name}, מערכת CRM לעסק בתנאי האיגוד" if business_name
               else "מערכת CRM לעסק בתנאי האיגוד")
    text = (
        f"שלום,\n\n"
        f"שמי {sender_name}, מ{association_name}.\n\n"
        f"אנחנו מארגנים עכשיו קבוצה של בעלי עסקים מהמגזר להקמת מערכת CRM לניהול "
        f"לקוחות, לידים ומכירות{saw}\n\n"
        f"בזכות הכמות השגנו תנאים מיוחדים למצטרפים דרך האיגוד: במקום {CRM_REGULAR}, "
        f"רק {CRM_DEAL}.\n\n"
        f"אם זה מתאים לעסק שלכם, תשיבו לי לכאן עם שם וטלפון ואחזור אליכם עם כל הפרטים.\n\n"
        f"תודה,\n{sender_name}\n{association_name}\n"
    )
    p = "margin:0 0 14px;"
    html = f"""<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;padding:0;background:#ffffff;">
  <div dir="rtl" style="direction:rtl;text-align:right;max-width:600px;margin:0 auto;
       padding:22px 20px;font-family:Arial,Helvetica,sans-serif;font-size:16px;
       line-height:1.75;color:#222222;">
    <p style="{p}">שלום,</p>
    <p style="{p}">שמי {sender_name}, מ{association_name}.</p>
    <p style="{p}">אנחנו מארגנים עכשיו קבוצה של בעלי עסקים מהמגזר להקמת מערכת
      <strong>CRM</strong> לניהול לקוחות, לידים ומכירות{saw}</p>
    <p style="{p}">בזכות הכמות השגנו תנאים מיוחדים למצטרפים דרך האיגוד:
      במקום {CRM_REGULAR}, רק <strong>{CRM_DEAL}</strong>.</p>
    <p style="{p}">אם זה מתאים לעסק שלכם, תשיבו לי לכאן עם שם וטלפון ואחזור אליכם
      עם כל הפרטים.</p>
    <p style="margin:0 0 4px;">תודה,</p>
    <p style="margin:0;">{sender_name}<br>{association_name}</p>
  </div>
</body></html>"""
    return subject, html, text


# ------------------------- קמפיין: מענק מחשוב 4.56 -------------------------
GRANT_NAME = 'הוראת מנכ"ל 4.56'
GRANT_DEADLINE = "25 באוגוסט"
GRANT_BOT_URL = "https://egud.org.il/grant-456"


def _grant(business_name, association_name, sender_name,
           field="", neighborhood="", **_):
    # סגנון המימון המנצח: קצר, אישי, בקשה להשיב עם שם וטלפון (בלי קישור/בוט)
    saw = _saw_clause(field, neighborhood)
    subject = (f"{business_name}, לגבי מענק לשדרוג העסק" if business_name
               else "לגבי מענק לשדרוג העסק")
    text = (
        f"שלום,\n\n"
        f"שמי {sender_name}, מ{association_name}.\n\n"
        f"יש עכשיו מענק ממשלתי חדש לשדרוג דיגיטלי וטכנולוגי בעסק, והמדינה מחזירה עד "
        f"35 אחוז מהעלות{saw}\n\n"
        f"ואצלנו באיגוד אפשר לקבל עוד 15 אחוז מעבר לזה. ההגשה עד {GRANT_DEADLINE}.\n\n"
        f"רוצים לבדוק אם זה מתאים לכם? תשיבו לי לכאן עם שם וטלפון ואחזור אליכם עם כל "
        f"הפרטים.\n\n"
        f"תודה,\n{sender_name}\n{association_name}\n"
    )
    p = "margin:0 0 14px;"
    html = f"""<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;padding:0;background:#ffffff;">
  <div dir="rtl" style="direction:rtl;text-align:right;max-width:600px;margin:0 auto;
       padding:22px 20px;font-family:Arial,Helvetica,sans-serif;font-size:16px;
       line-height:1.75;color:#222222;">
    <p style="{p}">שלום,</p>
    <p style="{p}">שמי {sender_name}, מ{association_name}.</p>
    <p style="{p}">יש עכשיו מענק ממשלתי חדש לשדרוג דיגיטלי וטכנולוגי בעסק, והמדינה
      מחזירה עד <strong>35 אחוז מהעלות</strong>{saw}</p>
    <p style="{p}">ואצלנו באיגוד אפשר לקבל עוד <strong>15 אחוז</strong> מעבר לזה.
      ההגשה עד {GRANT_DEADLINE}.</p>
    <p style="{p}">רוצים לבדוק אם זה מתאים לכם? תשיבו לי לכאן עם שם וטלפון ואחזור
      אליכם עם כל הפרטים.</p>
    <p style="margin:0 0 4px;">תודה,</p>
    <p style="margin:0;">{sender_name}<br>{association_name}</p>
  </div>
</body></html>"""
    return subject, html, text


# ------------------ קמפיין: גיוס סוכנים ממליצים (agent) ------------------
# המטרה היחידה של המייל: שהסוכן ישאיר טלפון. אין בו עמלה, אחוזים או בקשת פגישה.
# הנוסח והפרופיל של "מי מתאים להיות סוכן" מתועדים ב-docs/agents.md.

# תארים ותיאורי מקצוע שמופיעים לפני שם של אדם — "רו״ח משה כהן",
# "יועץ עסקי אברהם כץ". מוסרים אותם כדי להגיע לשם עצמו.
PERSON_TITLES = ('רו"ח', "רו״ח", 'עו"ד', "עו״ד", "יועץ מס", "יועצת מס",
                 'ד"ר', "ד״ר", "דר'", "מר", "גב'",
                 "יועץ עסקי", "יועצת עסקית", "יועץ", "יועצת",
                 "מאמן עסקי", "מאמנת עסקית", "מאמן", "מאמנת",
                 "רואה חשבון", "עורך דין", "עורכת דין", "סוכן ביטוח",
                 # תארים שמופיעים בפועל בשמות עסקים בגוגל, לרוב משורשרים:
                 # "עורך דין וטוען רבני יוסף שאוליאן"
                 "וטוען רבני", "טוען רבני", "טוענת רבנית", "ונוטריון",
                 "נוטריון", "ועורך דין", "ורואה חשבון", "ומגשר", "מגשר",
                 "מגשרת", "סוכנת ביטוח", "יועץ פנסיוני", "מתווך", "מתווכת")

# סימנים לכך שהשם הוא של משרד/חברה ולא של אדם
FIRM_MARKERS = ("משרד", "ושות", 'בע"מ', "בע״מ", "בעמ", "חברת", "קבוצת",
                "&", "Ltd", "LTD", "Inc")

_HEB_WORD_RE = re.compile(r"[\u0590-\u05EA'\u05F3\u05F4-]{2,}")


def person_first_name(name: str) -> str:
    """
    מחזיר שם פרטי רק כשברור שהשם הוא של אדם (למשל "רו״ח משה כהן" → "משה").
    בכל מקרה אחר מחזיר מחרוזת ריקה — עדיף "שלום," בלי שם מאשר לפנות בשם שגוי.
    """
    n = (name or "").strip()
    # מסירים תיאורים חוזרים: "יועץ עסקי" ואחריו "רו״ח" וכדומה
    for _ in range(3):
        for title in sorted(PERSON_TITLES, key=len, reverse=True):
            if n.startswith(title):
                n = n[len(title):].strip(" -–,")
                break
        else:
            break
    if not n or any(m in n for m in FIRM_MARKERS):
        return ""
    words = n.split()
    if len(words) != 2 or not all(_HEB_WORD_RE.fullmatch(w) for w in words):
        return ""
    return words[0]


def agent_fact(fact: str = "", field: str = "", neighborhood: str = "") -> str:
    """
    העובדה הקונקרטית שנכנסת ל"ראיתי ש...". מעדיפים עובדה שהוזנה ידנית;
    אחרת בונים רק ממה שידוע באמת מהסריקה (תחום + שכונה). לא ממציאים כלום.
    """
    if fact:
        return fact
    if field and neighborhood:
        return f"יש לך {field} ב{neighborhood}"
    if field:
        return f"יש לך {field}"
    if neighborhood:
        return f"אתה פעיל ב{neighborhood}"
    return ""


def usable_quote(rec) -> str:
    """
    הציטוט שמותר להיכנס למייל: רק כזה שנוגע לעסק. המלצה אמיתית על עניין
    פרטי (קצבאות, החזר מס לשכיר) מסגירה שהפנייה אוטומטית, ולכן במקרה כזה
    לא מצטטים כלום ונשענים על מסת ההמלצות בלבד. הבדיקה נעשית גם כאן ולא
    רק בסריקה, כדי שגם לידים שנסרקו לפני התיקון יטופלו נכון.
    """
    text = ((rec or {}).get("quote") or "").strip()
    return text if recommendations.is_business_relevant(text) else ""


def agent_seen_line(rec=None, fact: str = "", field: str = "",
                    neighborhood: str = "") -> str:
    """
    שורת "מה ראיתי עליו" — הלגיטימציה לפנייה. הבסיס הוא המלצה אמיתית
    שנמצאה (ביקורות גוגל / עמוד המלצות באתר / חיפוש), עם ציטוט כשיש.
    בלי המלצה אמיתית לא כותבים שראינו המלצה — נופלים לעובדה שידועה בוודאות.
    """
    seen = ""
    if rec:
        quote = usable_quote(rec)
        source = rec.get("source") or ""
        count = int(rec.get("count") or 0)
        rating = rec.get("rating")
        where = {"google": "בגוגל", "site": "באתר שלך"}.get(source, "ברשת")
        if quote and source == "google":
            seen = f'ראיתי את ההמלצות עליך בגוגל, ואחד הלקוחות כתב שם: "{quote}"'
        elif quote:
            seen = f'ראיתי המלצה עליך {where}: "{quote}"'
        elif count >= 3:
            grade = f", בדירוג {rating}" if rating else ""
            seen = f"ראיתי את ההמלצות עליך בגוגל — {count} לקוחות{grade}."
    fact = agent_fact(fact, field, neighborhood) if not seen else fact
    if fact:
        return f"{seen} וראיתי גם ש{fact}." if seen else f"ראיתי ש{fact}."
    return seen


# ניסוח יחיד של המקצוע ("חיפשתי רואה חשבון באזור ירושלים")
AGENT_PROFESSIONS = {
    "משרד רואי חשבון": "רואה חשבון",
    "משרד עורכי דין": "עורך דין",
    "סוכנות ביטוח": "סוכן ביטוח",
    "משרד תיווך": "מתווך",
    "סוכנות נסיעות": "סוכן נסיעות",
}

# ניסוח רבים של המקצוע (ל"אני מחפשת רואי חשבון ותיקים...")
AGENT_PROFESSIONALS = {
    "משרד רואי חשבון": "רואי חשבון",
    "משרד עורכי דין": "עורכי דין",
    "סוכנות ביטוח": "סוכני ביטוח",
    "משרד תיווך": "מתווכים",
}


def agent_why_line(rec=None, field: str = "", neighborhood: str = "") -> str:
    """
    "למה דווקא אתה" — הנימוק לפנייה, מבוסס על מה שבאמת עולה מההמלצות:
    האם הממליצים הם בעלי עסקים, והאם מדובר בליווי שוטף. בלי המלצות נשאר
    הנימוק האמיתי של הסינון עצמו: ותק + לקוחות שהם בעלי עסקים.
    """
    # הנימוק נגזר רק ממה שכתוב בציטוט שמוצג במייל. סימנים שהגיעו מהמלצות
    # אחרות היו יוצרים טענה שלא נובעת מהמשפט שמעליה.
    quote = usable_quote(rec)
    signals = recommendations.detect_signals([quote]) if quote else []
    if "owners" in signals and "ongoing" in signals:
        return ("פניתי דווקא אליך כי ההמלצות עליך הן מבעלי עסקים, ורואים בהן "
                "שאתה מלווה אותם לאורך זמן ולא רק מגיש דוח פעם בשנה.")
    if "owners" in signals:
        return ("פניתי דווקא אליך כי ההמלצות עליך הן מבעלי עסקים — "
                "וזה בדיוק הקהל שאני עובדת איתו.")
    if "ongoing" in signals:
        return ("פניתי דווקא אליך כי מההמלצות רואים שאתה מלווה את הלקוחות "
                "לאורך זמן, ולא רק מגיש דוח פעם בשנה.")
    who = AGENT_PROFESSIONALS.get(field, "בעלי מקצוע")
    where = f" ב{neighborhood}" if neighborhood else ""
    return (f"פניתי דווקא אליך כי אני מחפשת {who} ותיקים{where} "
            f"שהלקוחות שלהם הם בעלי עסקים קטנים.")


def _department_of(sender_title: str) -> str:
    """'מנהלת מחלקת הטכנולוגיה' → 'מחלקת הטכנולוגיה' (לשורת החתימה)."""
    t = (sender_title or "").strip()
    for prefix in ("מנהלת ", "מנהל ", "ראש "):
        if t.startswith(prefix):
            return t[len(prefix):]
    return t


def reviews_line(rec=None) -> str:
    """
    מה שראינו עליו — לפי מספר הביקורות בפועל. "הרבה ביקורות" נאמר רק כשיש
    באמת הרבה; בשתיים-שלוש זה היה נשמע מנופח ולא אמין.
    """
    count = int((rec or {}).get("count") or 0)
    if count >= 8:
        return "ראיתי הרבה ביקורות חיוביות מלקוחות שלך"
    if count >= 2:
        return "ראיתי ביקורות חיוביות מלקוחות שלך"
    return ""


def _agent_signature(sender_name, contact_email, website=""):
    sign = [sender_name]
    if contact_email:
        sign.append(contact_email)
    if website:
        sign.append(website)
    return sign


def _agent_opening(sender_name, sender_title, first_name, intro_how,
                   rec, field, neighborhood, area):
    """
    פתיחת המייל — זהה בשני הנוסחים: היכרות, איך הגעתי אליו, ומה ראיתי.
    ההבדל בין הנוסחים מתחיל רק אחרי הפתיחה הזאת.
    """
    # התחום של הנמען עצמו. בלי התאמה מדויקת משתמשים בשם התחום כפי שהוא,
    # ורק אם אין כלום נופלים לניסוח כללי — לעולם לא לכתוב תחום שגוי.
    profession = AGENT_PROFESSIONS.get(field) or field or "בעל מקצוע"
    area = area or city_of(neighborhood)
    where = f" באזור {area}" if area else ""
    found = intro_how.strip() or f"חיפשתי {profession}{where} ונתקלתי בך"
    seen = reviews_line(rec)
    return [
        f"היי {first_name}," if first_name else "היי,",
        f"{sender_name}, {sender_title} - נעים להכיר.",
        f"{found} - {seen}." if seen else f"{found}.",
    ]


def _agent_html(lines, sign):
    p = "margin:0 0 14px;"
    body = "\n".join(f'    <p style="{p}">{line}</p>' for line in lines)
    # כתובות ומיילים הם טקסט לטיני בתוך פסקה בעברית: בלי dir="ltr" הדפדפן
    # מזיז את הלוכסן הסוגר לתחילת השורה ("/https://...").
    sign = [(f'<a href="{v}" dir="ltr" style="color:#1a2e4a;'
             f'unicode-bidi:embed;">{v}</a>' if v.startswith("http")
             else (f'<span dir="ltr">{v}</span>' if "@" in v else v))
            for v in sign]
    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;padding:0;background:#ffffff;">
  <div dir="rtl" style="direction:rtl;text-align:right;max-width:600px;margin:0 auto;
       padding:22px 20px;font-family:Arial,Helvetica,sans-serif;font-size:16px;
       line-height:1.75;color:#222222;">
{body}
    <p style="margin:0;">{"<br>".join(sign)}</p>
  </div>
</body></html>"""


# ------------------ הודעה 1: פנייה ראשונה ------------------
def _agent(business_name="", sender_name="מירי לודמיר",
           sender_title="מנהלת סינרו טק", company="סינרו טק",
           contact_email="", website="", first_name="", intro_how="",
           rec=None, field="", neighborhood="", area="", **_):
    first_name = (first_name or person_first_name(business_name)).strip()
    subject = (f"{first_name}, רציתי לכתוב לך אישית" if first_name
               else "רציתי לכתוב לך אישית")
    lines = _agent_opening(sender_name, sender_title, first_name, intro_how,
                           rec, field, neighborhood, area) + [
        "רציתי לדבר איתך על שיתוף פעולה שאנחנו מציעים לבעלי מקצוע בתחום שלך.",
        "תכתבו לי כאן את הטלפון שלכם ואחזור אליכם להצגת ההצעה המלאה.",
    ]
    sign = _agent_signature(sender_name, contact_email, website)
    text = "\n\n".join(lines) + "\n\n" + "\n".join(sign) + "\n"
    return subject, _agent_html(lines, sign), text


# ------------------ נוסח ב': ההצעה ישירות ------------------
# שני הנוסחים נשלחים לשתי קבוצות שונות (A/B), לא זה אחרי זה.
# תנאי שיתוף הפעולה (ניתן לעדכן כאן)
AGENT_CRM_MONTHS_FREE = 3
AGENT_COMMISSION = "10%"


def _agent_offer(business_name="", sender_name="מירי לודמיר",
                 sender_title="מנהלת סינרו טק", contact_email="", website="",
                 first_name="", intro_how="", rec=None, field="",
                 neighborhood="", area="", **_):
    """נוסח ב': אותה פתיחה בדיוק כמו נוסח א', וממשיך ישר לתנאי ההצעה."""
    first_name = (first_name or person_first_name(business_name)).strip()
    subject = (f"{first_name}, הצעה לשיתוף פעולה" if first_name
               else "הצעה לשיתוף פעולה")
    lines = _agent_opening(sender_name, sender_title, first_name, intro_how,
                           rec, field, neighborhood, area) + [
        f"רציתי להציע לך שיתוף פעולה: תקבל מערכת CRM מתקדמת לניהול לקוחות "
        f"ולידים - {AGENT_CRM_MONTHS_FREE} חודשים במתנה.",
        f"בנוסף, על כל רכישה של מי שהפניתם תקבלו עמלה בשווי {AGENT_COMMISSION}.",
        "תכתבו לי כאן את הטלפון שלכם ואחזור אליכם להצגת ההצעה המלאה.",
    ]
    sign = _agent_signature(sender_name, contact_email, website)
    text = "\n\n".join(lines) + "\n\n" + "\n".join(sign) + "\n"
    return subject, _agent_html(lines, sign), text


CAMPAIGNS = {"funding": _funding, "hr": _hr, "crm": _crm, "grant": _grant,
             "agent": _agent, "agent_offer": _agent_offer}


def render(campaign, **ctx):
    """מחזיר (subject, html, text) לפי הקמפיין."""
    fn = CAMPAIGNS.get(campaign, _funding)
    return fn(**ctx)


def whatsapp_text(campaign, **ctx):
    """אותו נוסח כהודעת וואטסאפ — גוף הטקסט בלבד, בלי שורת הנושא."""
    return render(campaign, **ctx)[2]


# ------------------ נוסח מותאם שהמשתמשת כותבת באפליקציה ------------------
# מציני המקום שאפשר להשתמש בהם בנוסח. כל מה שלא מוכר נשאר כמו שהוא, כדי
# שסוגריים מסולסלים בטקסט לא יפילו את השליחה.
PLACEHOLDERS = {
    "שם": "first_name_or_business",
    "שם_פרטי": "first_name",
    "שם_העסק": "business_name",
    "תחום": "profession",
    "עיר": "area",
    "שכונה": "neighborhood",
    "ביקורות": "review_count",
    "דירוג": "rating",
    "שולח": "sender_name",
    "אתר": "website",
    "מייל_שולח": "contact_email",
}

_PLACEHOLDER_RE = re.compile(r"\{\{?\s*([^{}]+?)\s*\}?\}")


def custom_values(business_name="", first_name="", field="", neighborhood="",
                  area="", rec=None, sender_name="", contact_email="",
                  website="", profession_hint="", **_) -> dict:
    """
    הערכים שמוזרקים לנוסח מותאם, מנתוני הליד.

    לאנשי קשר שהועלו מקובץ אין סוג עסק מגוגל ואין שכונה מוכרת, ולכן התחום
    נופל לתחום שהוגדר בקמפיין, והאזור לערך שנרשם בקובץ.
    """
    first = (first_name or person_first_name(business_name)).strip()
    rec = rec or {}
    return {
        "first_name": first,
        "first_name_or_business": first or business_name,
        "business_name": business_name,
        "profession": (AGENT_PROFESSIONS.get(field) or field
                       or profession_hint or "בעל מקצוע"),
        "area": area or city_of(neighborhood) or neighborhood,
        "neighborhood": neighborhood,
        "review_count": str(rec.get("count") or ""),
        "rating": str(rec.get("rating") or ""),
        "sender_name": sender_name,
        "contact_email": contact_email,
        "website": website,
    }


def fill_placeholders(text: str, values: dict) -> str:
    """
    מחליף {{שם}} / {שם} בערכים. מציין מקום לא מוכר נשאר כמו שהוא.

    רווח נחשב כמו קו תחתון: מי שכותב {{שם פרטי}} מתכוון ל-{{שם_פרטי}},
    וזה בדיוק מה שקורה בפועל כשמקלידים. בלי זה המציין נשאר במייל כמו
    שהוא, והנמען מקבל "היי {{שם פרטי}},".
    """
    def sub(match):
        key = re.sub(r"[\s]+", "_", match.group(1).strip())
        field = PLACEHOLDERS.get(key)
        if field is None:
            return match.group(0)
        return values.get(field, "")
    return _PLACEHOLDER_RE.sub(sub, text or "")


def _tidy(text: str) -> str:
    """
    מנקה את הנוסח אחרי הזרקת הערכים: מציין מקום ריק לא ישאיר "היי ,"
    או רווח כפול באמצע משפט.
    """
    text = re.sub(r"[ \t]{2,}", " ", text or "")
    text = re.sub(r"\s+([,.!?])", r"\1", text)
    text = re.sub(r"^([^\S\n]*\S+)[ \t]*,", r"\1,", text, flags=re.M)
    return text.strip()


def render_custom(subject_tpl: str, body_tpl: str, **ctx):
    """
    מרנדר נוסח שנכתב באפליקציה. מחזיר (subject, html, text) באותו מבנה
    כמו שאר התבניות, כדי שהשליחה לא תדע להבחין ביניהן.
    """
    values = custom_values(**ctx)
    subject = _tidy(fill_placeholders(subject_tpl, values))
    body = _tidy(fill_placeholders(body_tpl, values))

    lines = [ln.strip() for ln in body.split("\n\n") if ln.strip()]
    text = "\n\n".join(lines) + "\n"
    p = "margin:0 0 14px;"
    html_lines = "\n".join(
        f'    <p style="{p}">{ln.replace(chr(10), "<br>")}</p>' for ln in lines)
    html = f"""<!DOCTYPE html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;padding:0;background:#ffffff;">
  <div dir="rtl" style="direction:rtl;text-align:right;max-width:600px;margin:0 auto;
       padding:22px 20px;font-family:Arial,Helvetica,sans-serif;font-size:16px;
       line-height:1.75;color:#222222;">
{html_lines}
  </div>
</body></html>"""
    return subject, html, text
