"""
תבניות המייל, לפי קמפיין:
  funding — מימון (פנייה אישית לחנות קמעונאית).
  hr      — משאבי אנוש (קורס וכנס לגיוס עובדים).

הגישה בשני המקרים: מייל קצר ואנושי, בלי עיצוב כבד. ל-hr יש שני כפתורים
(רכישת הקורס + הרשמה לכנס במייל).
"""
from urllib.parse import quote

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
    btn = ("display:inline-block;padding:13px 30px;border-radius:8px;"
           "text-decoration:none;font-weight:bold;font-size:16px;")
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
    <p style="margin:22px 0;">
      <a href="{course_link}" target="_blank"
         style="{btn}background:#1a2e4a;color:#ffffff;">לרכישת הקורס ›</a>
    </p>
    <p style="{p}">ולהרשמה לכנס, פשוט השיבו למייל הזה עם שם וטלפון ונחזור אליכם.</p>
    <p style="margin:0 0 4px;">תודה,</p>
    <p style="margin:0;">{sender_name}<br>{association_name}</p>
  </div>
</body></html>"""
    return subject, html, text


CAMPAIGNS = {"funding": _funding, "hr": _hr}


def render(campaign, **ctx):
    """מחזיר (subject, html, text) לפי הקמפיין."""
    fn = CAMPAIGNS.get(campaign, _funding)
    return fn(**ctx)
