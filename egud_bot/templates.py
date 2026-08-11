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
           field="", neighborhood="", place_id="", **_):
    # פתיח: מזכירים את העסק שלהם, ואז ישר לעניין (כיוון ממוקד-כסף)
    if field and neighborhood:
        seen = f"ראיתי שיש לכם {field} ב{neighborhood}"
    elif field:
        seen = f"ראיתי שיש לכם {field}"
    elif neighborhood:
        seen = f"ראיתי שהעסק שלכם ב{neighborhood}"
    else:
        seen = ""
    intro = (f"{seen}, ורציתי לספר לכם על הזדמנות ששווה לכם הרבה כסף."
             if seen else "רציתי לספר לכם על הזדמנות ששווה לכם הרבה כסף.")
    sep = "&" if "?" in GRANT_BOT_URL else "?"
    bot_link = f"{GRANT_BOT_URL}{sep}ref={quote(place_id or '')}&src=grant"
    subject = (f"{business_name}, מענק ממשלתי לשדרוג דיגיטלי בעסק"
               if business_name else "מענק ממשלתי לשדרוג דיגיטלי בעסק")
    text = (
        f"שלום,\n\n"
        f"שמי {sender_name}, מ{association_name}.\n\n"
        f"{intro}\n\n"
        f"משרד הכלכלה נותן עכשיו מענק לעסקים שרוצים לשדרג את הצד הדיגיטלי שלהם. "
        f"כלומר, אם אתם קונים או מקימים מערכת לניהול העסק, לניהול מלאי וספקים, מערכת "
        f"מכירות (כולל אתר או חנות אונליין), מערכות אוטומציה, או תוכנה וציוד מחשוב, "
        f"המדינה מחזירה לכם עד 35 אחוז מהעלות (עד 350 אלף שקל). זה נקרא מענק "
        f"{GRANT_NAME} של משרד הכלכלה.\n\n"
        f"ומה שמייחד אותנו באיגוד, שתי הטבות נוספות:\n"
        f"• גם אם לא תהיו זכאים למענק של המדינה, אצלנו תקבלו החזר של 15 אחוז.\n"
        f"• את פתיחת התיק וההגשה אנחנו עושים לכם דרך נותני השירות שלנו בחצי מחיר.\n\n"
        f"ההגשה למענק של משרד הכלכלה היא עד {GRANT_DEADLINE}.\n\n"
        f"הדרך הכי פשוטה לבדוק אם אתם זכאים ולכמה כסף היא בדיקה קצרה של דקה כאן:\n"
        f"{bot_link}\n\n"
        f"או פשוט תשיבו לי עם שם וטלפון ואסביר לכם הכל.\n\n"
        f"בהצלחה,\n{sender_name}\n{association_name}\n"
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
    <p style="{p}">{intro}</p>
    <p style="{p}">משרד הכלכלה נותן עכשיו מענק לעסקים שרוצים לשדרג את הצד הדיגיטלי
      שלהם. כלומר, אם אתם קונים או מקימים מערכת לניהול העסק, לניהול מלאי וספקים,
      מערכת מכירות (כולל אתר או חנות אונליין), מערכות אוטומציה, או תוכנה וציוד
      מחשוב, <strong>המדינה מחזירה לכם עד 35 אחוז מהעלות</strong> (עד 350 אלף שקל).
      זה נקרא מענק {GRANT_NAME} של משרד הכלכלה.</p>
    <p style="margin:0 0 6px;">ומה שמייחד אותנו באיגוד, שתי הטבות נוספות:</p>
    <p style="margin:0 0 6px;padding-right:6px;">• גם אם לא תהיו זכאים למענק של
      המדינה, אצלנו תקבלו <strong>החזר של 15 אחוז</strong>.</p>
    <p style="margin:0 0 14px;padding-right:6px;">• את פתיחת התיק וההגשה אנחנו עושים
      לכם דרך נותני השירות שלנו <strong>בחצי מחיר</strong>.</p>
    <p style="{p}">ההגשה למענק של משרד הכלכלה היא עד {GRANT_DEADLINE}.</p>
    <p style="{p}">הדרך הכי פשוטה לבדוק אם אתם זכאים ולכמה כסף היא בדיקה קצרה של
      דקה כאן:<br>
      <a href="{bot_link}" target="_blank" style="color:#1a2e4a;">{GRANT_BOT_URL}</a></p>
    <p style="{p}">או פשוט תשיבו לי עם שם וטלפון ואסביר לכם הכל.</p>
    <p style="margin:0 0 4px;">בהצלחה,</p>
    <p style="margin:0;">{sender_name}<br>{association_name}</p>
  </div>
</body></html>"""
    return subject, html, text


CAMPAIGNS = {"funding": _funding, "hr": _hr, "crm": _crm, "grant": _grant}


def render(campaign, **ctx):
    """מחזיר (subject, html, text) לפי הקמפיין."""
    fn = CAMPAIGNS.get(campaign, _funding)
    return fn(**ctx)
