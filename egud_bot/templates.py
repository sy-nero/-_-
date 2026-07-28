"""
תבנית המייל שנשלח לעסקים — עיצוב מותג האיגוד (עברית, RTL).

המסר: איגוד העסקים החרדיים פותח קבוצה חדשה למימון עסקים, ומזמין את העסק
להצטרף כבר בשלב ההקמה. הניסוח כללי (לא מתמקד בתחום ספציפי).

צבעי המותג:
  זהב (אקצנט/כפתורים)   #f4ea67
  זהב כהה (hover)       #dcd13a
  נייבי כהה (Hero)      #1a2e4a
  נייבי בינוני          #243c60
  נייבי עמוק (טקסט/רקע) #0f1f38
  רקע דף                #f5f5f5
  כרטיס                 #ffffff
  טקסט ראשי             #111827
  טקסט משני             #4b5563
"""
from urllib.parse import urlencode, quote

# ---- פלטת צבעי המותג ----
GOLD = "#f4ea67"
GOLD_DARK = "#dcd13a"
NAVY_DARK = "#1a2e4a"
NAVY_MID = "#243c60"
NAVY_DEEP = "#0f1f38"
PAGE_BG = "#f5f5f5"
CARD = "#ffffff"
TEXT = "#111827"
TEXT_2 = "#4b5563"

# מיפוי סוג העסק (Google type) לשם עברי, לצורך פנייה אישית
FIELD_NOUNS = {
    "bakery": "מאפייה",
    "restaurant": "מסעדה",
    "cafe": "בית קפה",
    "clothing_store": "חנות אופנה",
    "grocery_store": "מכולת",
    "convenience_store": "מרכול",
    "hair_care": "מספרה",
    "beauty_salon": "מכון יופי",
    "book_store": "חנות ספרים",
    "electronics_store": "חנות אלקטרוניקה",
    "furniture_store": "חנות רהיטים",
    "jewelry_store": "חנות תכשיטים",
    "shoe_store": "חנות הנעלה",
    "hardware_store": "חנות כלי עבודה",
    "florist": "חנות פרחים",
    "gift_shop": "חנות מתנות",
    "pharmacy": "בית מרקחת",
    "laundry": "מכבסה",
}


def field_noun(primary_type: str) -> str:
    """שם עסק בעברית לפי סוג, או מחרוזת ריקה אם כללי/לא ידוע."""
    return FIELD_NOUNS.get((primary_type or "").lower(), "")


def _personal_intro(business_name: str, field: str = "", neighborhood: str = "") -> str:
    """בונה משפט פתיחה אישי לפי הנתונים הקיימים על העסק (שם/סוג/שכונה)."""
    biz = (business_name or "").strip()
    lead_in = f"שמנו לב ל{biz}" if biz else "שמנו לב לעסק שלך"
    tail = []
    if field:
        tail.append(field)
    if neighborhood:
        tail.append(f"מ{neighborhood}")
    suffix = ", " + " ".join(tail) if tail else ""
    return f"{lead_in}{suffix}, ופנינו אליך במיוחד."


def build_subject(association_name: str, business_name: str = "") -> str:
    if business_name:
        return f"{business_name}, הבנקים אמרו לא? אנחנו אומרים כן ✦"
    return f"הבנקים אמרו לא? אנחנו אומרים כן. הזמנה מ{association_name} ✦"


def _landing_link(base_url: str, place_id: str) -> str:
    """מוסיף פרמטר ref כדי לדעת מאיזה מייל הגיעה ההרשמה."""
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}{urlencode({'ref': place_id, 'src': 'email'})}"


def _benefit_row(icon: str, title: str, desc: str) -> str:
    """שורת יתרון עם אייקון זהב עגול."""
    return f"""
    <tr>
      <td style="padding:10px 0;" valign="top">
        <table role="presentation" dir="rtl" cellpadding="0" cellspacing="0" width="100%">
          <tr>
            <td width="46" valign="top">
              <div style="width:38px;height:38px;border-radius:50%;background:{GOLD};
                          color:{NAVY_DEEP};font-size:19px;font-weight:bold;text-align:center;
                          line-height:38px;">{icon}</div>
            </td>
            <td valign="top" style="padding-right:12px;direction:rtl;text-align:right;">
              <div style="font-size:18px;font-weight:bold;color:{TEXT};margin-bottom:3px;">{title}</div>
              <div style="font-size:16px;color:{TEXT_2};line-height:1.65;">{desc}</div>
            </td>
          </tr>
        </table>
      </td>
    </tr>"""


def _mailto(contact_email: str, business_name: str = "") -> str:
    """בונה קישור mailto עם נושא וגוף מוכנים מראש לפנייה חזרה לאיגוד."""
    subject = "מעוניין בקבוצת המימון של איגוד העסקים החרדיים"
    body = (
        "שלום,\n"
        "אשמח לקבל פרטים על קבוצת המימון.\n\n"
        f"שם העסק: {business_name}\n"
        "שם איש קשר: \n"
        "טלפון: \n"
    )
    return f"mailto:{contact_email}?subject={quote(subject)}&body={quote(body)}"


def build_html(
    business_name: str,
    association_name: str,
    contact_email: str,
    unsubscribe_url: str = "",
    place_id: str = "",
    logo_src: str = "cid:logo",
    field: str = "",
    neighborhood: str = "",
) -> str:
    link = _mailto(contact_email, business_name)
    greeting = f"שלום {business_name}," if business_name else "שלום,"
    intro = _personal_intro(business_name, field, neighborhood)

    benefits = (
        _benefit_row("₪", "גב אמיתי, לא עוד \"לא\"",
                     "אנחנו נלחמים כדי להשיג לך את המימון, גם כשהבנקים כבר אמרו לא.")
        + _benefit_row("♦", "בלי הפתעות ובלי אותיות קטנות",
                       "תנאים הוגנים ושקופים מהרגע הראשון, בלי עמלות מנופחות ובלי מלכודות.")
        + _benefit_row("✦", "מישהו מהצד שלך",
                       "ליווי אישי של אנשים מהמגזר שמבינים אותך ואת העסק, ורוצים שתצליח.")
    )

    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>{association_name}</title>
</head>
<body style="margin:0;padding:0;background:{PAGE_BG};
             font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;">
    הבנקים אמרו לך לא? קבוצת מימון חדשה לבעלי עסקים מתחילים, מ{association_name}.
  </div>
  <table role="presentation" dir="rtl" width="100%" cellpadding="0" cellspacing="0"
         style="background:{PAGE_BG};padding:28px 12px;direction:rtl;">
    <tr><td align="center">
      <table role="presentation" dir="rtl" width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;background:{CARD};border-radius:18px;
                    overflow:hidden;box-shadow:0 8px 30px rgba(15,31,56,0.14);direction:rtl;">

        <tr><td style="height:6px;background:{GOLD};font-size:0;line-height:0;">&nbsp;</td></tr>

        <tr>
          <td style="background:linear-gradient(135deg,{NAVY_DARK} 0%,{NAVY_MID} 55%,{NAVY_DEEP} 100%);
                     padding:40px 30px 36px;text-align:center;">
            <img src="{logo_src}" alt="{association_name}" width="230"
                 style="display:block;margin:0 auto;width:230px;max-width:70vw;height:auto;">
            <div style="display:inline-block;margin:26px 0 0;padding:5px 16px;border:1px solid {GOLD};
                        border-radius:999px;color:{GOLD};font-size:13px;font-weight:600;letter-spacing:.4px;">
              ✦ קבוצה חדשה נפתחת עכשיו
            </div>
            <h1 style="margin:18px 0 4px;color:#ffffff;font-size:32px;line-height:1.3;font-weight:800;">
              הבנקים אמרו לך לא?
            </h1>
            <p style="margin:0 0 6px;color:{GOLD};font-size:20px;font-weight:700;">
              קבוצת מימון לבעלי עסקים מתחילים
            </p>
            <div style="display:inline-block;height:3px;width:64px;background:{GOLD};
                        border-radius:2px;margin:8px 0 0;"></div>
          </td>
        </tr>

        <tr>
          <td dir="rtl" style="padding:32px 34px 4px;direction:rtl;text-align:right;">
            <p style="margin:0 0 16px;font-size:20px;font-weight:bold;color:{TEXT};">{greeting}</p>
            <p style="margin:0 0 12px;font-size:18px;line-height:1.8;color:{TEXT_2};">
              {intro} ובוא נדבר רגע בכנות, בגובה העיניים. אתה קם כל בוקר ונותן את
              הנשמה לעסק, ודווקא כשאתה צריך קצת אוויר לנשימה, כולם סוגרים לך את הדלת.
              כמה פעמים כבר שמעת "תחזור עם ערבויות"?
              <strong style="color:{TEXT};">כמה לילות כבר לא ישנת בגלל תזרים שנתקע?</strong>
            </p>
            <p style="margin:0 0 12px;font-size:18px;line-height:1.8;color:{TEXT_2};">
              אז תקשיב טוב: אנחנו לא בנק, ואנחנו לא נגדך.
              אנחנו ב<strong style="color:{TEXT};">איגוד העסקים החרדיים</strong> אנשים
              מהמגזר שלך, שהיו בדיוק במקום שאתה נמצא בו עכשיו. הקמנו את הקבוצה הזאת
              כדי לתת לך את מה שמגיע לך:
              <strong style="color:{TEXT};">מימון אמיתי, בתנאים הוגנים, ומישהו שנלחם
              בשבילך.</strong>
            </p>
          </td>
        </tr>

        <tr>
          <td dir="rtl" style="padding:12px 34px 6px;direction:rtl;text-align:right;">
            <p style="margin:0 0 6px;font-size:21px;font-weight:800;color:{NAVY_DARK};">
              מה תקבלו בקבוצה:
            </p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
              {benefits}
            </table>
          </td>
        </tr>

        <tr>
          <td style="padding:22px 34px 6px;text-align:center;">
            <table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 auto;">
              <tr><td align="center" style="border-radius:12px;background:{GOLD};
                       box-shadow:0 6px 16px rgba(244,234,103,0.5);">
                <a href="{link}" target="_blank"
                   style="display:inline-block;padding:17px 48px;color:{NAVY_DEEP};
                          text-decoration:none;font-size:20px;font-weight:800;border-radius:12px;">
                  כן, אני רוצה מימון הוגן ›
                </a>
              </td></tr>
            </table>
          </td>
        </tr>

        <tr><td style="height:14px;font-size:0;line-height:0;">&nbsp;</td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def build_text(
    business_name: str,
    association_name: str,
    contact_email: str,
    unsubscribe_url: str = "",
    place_id: str = "",
    field: str = "",
    neighborhood: str = "",
) -> str:
    """גרסת טקסט פשוט (fallback עבור לקוחות מייל ללא HTML)."""
    greeting = f"שלום {business_name}," if business_name else "שלום,"
    intro = _personal_intro(business_name, field, neighborhood)
    return (
        f"הבנקים אמרו לך לא?\n\n"
        f"{greeting}\n\n"
        f"{intro} ובוא נדבר רגע בכנות, בגובה העיניים. אתה קם כל בוקר ונותן את הנשמה "
        f"לעסק, ודווקא כשאתה צריך קצת אוויר לנשימה, כולם סוגרים לך את הדלת. כמה פעמים "
        f"כבר שמעת \"תחזור עם ערבויות\"? כמה לילות כבר לא ישנת בגלל תזרים שנתקע?\n\n"
        f"אז תקשיב טוב: אנחנו לא בנק, ואנחנו לא נגדך. אנחנו ב{association_name} אנשים "
        f"מהמגזר שלך, שהיו בדיוק במקום שאתה נמצא בו עכשיו. הקמנו את הקבוצה הזאת כדי "
        f"לתת לך את מה שמגיע לך: מימון אמיתי, בתנאים הוגנים, ומישהו שנלחם בשבילך.\n\n"
        f"מה תקבלו בקבוצה:\n"
        f"  • גב אמיתי, לא עוד \"לא\". נלחמים להשיג לך מימון גם כשהבנקים סירבו\n"
        f"  • בלי הפתעות ובלי אותיות קטנות, תנאים הוגנים ושקופים\n"
        f"  • מישהו מהצד שלך, ליווי אישי של אנשים שמבינים אותך\n\n"
        f"רוצה מימון הוגן? השיבו למייל הזה או שלחו הודעה אל: {contact_email}\n"
    )
