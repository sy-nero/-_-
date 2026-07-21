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
from urllib.parse import urlencode

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


def build_subject(association_name: str, business_name: str = "") -> str:
    if business_name:
        return f"{business_name}, נפתחת קבוצת מימון חדשה לעסקים ✦"
    return f"נפתחת קבוצת מימון חדשה לעסקים, הזמנה מ{association_name} ✦"


def _landing_link(base_url: str, place_id: str) -> str:
    """מוסיף פרמטר ref כדי לדעת מאיזה מייל הגיעה ההרשמה."""
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}{urlencode({'ref': place_id, 'src': 'email'})}"


def _benefit_row(icon: str, title: str, desc: str) -> str:
    """שורת יתרון עם אייקון זהב עגול."""
    return f"""
    <tr>
      <td style="padding:10px 0;" valign="top">
        <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
          <tr>
            <td width="46" valign="top">
              <div style="width:38px;height:38px;border-radius:50%;background:{GOLD};
                          color:{NAVY_DEEP};font-size:19px;font-weight:bold;text-align:center;
                          line-height:38px;">{icon}</div>
            </td>
            <td valign="top" style="padding-right:12px;">
              <div style="font-size:16px;font-weight:bold;color:{TEXT};margin-bottom:2px;">{title}</div>
              <div style="font-size:14px;color:{TEXT_2};line-height:1.6;">{desc}</div>
            </td>
          </tr>
        </table>
      </td>
    </tr>"""


def build_html(
    business_name: str,
    association_name: str,
    landing_url: str,
    unsubscribe_url: str,
    place_id: str = "",
    logo_src: str = "cid:logo",
) -> str:
    link = _landing_link(landing_url, place_id)
    greeting = f"שלום {business_name}," if business_name else "שלום,"

    benefits = (
        _benefit_row("₪", "מימון בתנאים מותאמים",
                     "גישה למקורות מימון והון לצמיחה, בהתאמה לצרכים של העסק שלכם.")
        + _benefit_row("✦", "קהילת עסקים חזקה",
                       "לצד עסקים נוספים מהמגזר: שיתופי פעולה, כוח קנייה והזדמנויות.")
        + _benefit_row("♦", "ליווי פיננסי אישי",
                       "ליווי מקצועי לאורך כל הדרך, מהבקשה ועד קבלת המימון בפועל.")
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
    נפתחת קבוצה חדשה למימון עסקים. הזמנה אישית מ{association_name}.
  </div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background:{PAGE_BG};padding:28px 12px;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;width:100%;background:{CARD};border-radius:18px;
                    overflow:hidden;box-shadow:0 8px 30px rgba(15,31,56,0.14);">

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
            <h1 style="margin:16px 0 8px;color:#ffffff;font-size:27px;line-height:1.35;font-weight:800;">
              קבוצת מימון חדשה לעסקים
            </h1>
            <div style="display:inline-block;height:3px;width:64px;background:{GOLD};
                        border-radius:2px;margin:8px 0 0;"></div>
          </td>
        </tr>

        <tr>
          <td style="padding:32px 34px 8px;">
            <p style="margin:0 0 14px;font-size:17px;font-weight:bold;color:{TEXT};">{greeting}</p>
            <p style="margin:0 0 12px;font-size:16px;line-height:1.75;color:{TEXT_2};">
              אנחנו <strong style="color:{TEXT};">איגוד העסקים החרדיים</strong>, ואנחנו פותחים
              בימים אלה <strong style="color:{TEXT};">קבוצה חדשה למימון עסקים</strong>.
            </p>
            <p style="margin:0 0 8px;font-size:16px;line-height:1.75;color:{TEXT_2};">
              במסגרת סריקה של העסקים החדשים והמבטיחים באזור זיהינו דווקא
              <strong style="color:{TEXT};">אתכם</strong>, ונשמח לצרף אתכם לקבוצה כבר בשלב ההקמה.
            </p>
          </td>
        </tr>

        <tr>
          <td style="padding:8px 34px 6px;">
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
                   style="display:inline-block;padding:16px 44px;color:{NAVY_DEEP};
                          text-decoration:none;font-size:18px;font-weight:800;border-radius:12px;">
                  להצטרפות לקבוצת המימון ›
                </a>
              </td></tr>
            </table>
            <p style="margin:16px 0 0;font-size:14px;color:{TEXT_2};">
              מעדיפים שנחזור אליכם? השאירו פרטים בקישור ונתקשר אליכם. 📞
            </p>
          </td>
        </tr>

        <tr>
          <td style="padding:22px 34px 4px;">
            <div style="border-top:1px solid #eef0f4;padding-top:14px;font-size:12px;color:#9aa2b1;
                        text-align:center;line-height:1.6;">
              אם הכפתור אינו עובד, העתיקו את הקישור לדפדפן:<br>
              <a href="{link}" style="color:{NAVY_MID};">{link}</a>
            </div>
          </td>
        </tr>

        <tr>
          <td style="padding:16px 30px 22px;background:{PAGE_BG};
                     color:#9aa2b1;font-size:12px;line-height:1.7;text-align:center;">
            הודעה זו נשלחה מטעם <strong style="color:{TEXT_2};">{association_name}</strong> לעסקים באזור.<br>
            אם אינכם מעוניינים לקבל פניות נוספות,
            <a href="{unsubscribe_url}" style="color:#9aa2b1;text-decoration:underline;">להסרה לחצו כאן</a>.
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def build_text(
    business_name: str,
    association_name: str,
    landing_url: str,
    unsubscribe_url: str,
    place_id: str = "",
) -> str:
    """גרסת טקסט פשוט (fallback עבור לקוחות מייל ללא HTML)."""
    link = _landing_link(landing_url, place_id)
    greeting = f"שלום {business_name}," if business_name else "שלום,"
    return (
        f"{greeting}\n\n"
        f"אנחנו {association_name}, ואנחנו פותחים בימים אלה קבוצה חדשה למימון עסקים.\n\n"
        f"במסגרת סריקה של העסקים החדשים והמבטיחים באזור זיהינו דווקא אתכם, "
        f"ונשמח לצרף אתכם לקבוצה כבר בשלב ההקמה.\n\n"
        f"מה מקבלים כחברים בקבוצה:\n"
        f"  • מימון והון לצמיחה בתנאים מותאמים\n"
        f"  • קהילת עסקים חזקה: שיתופי פעולה, כוח קנייה והזדמנויות\n"
        f"  • ליווי פיננסי אישי מהבקשה ועד קבלת המימון\n\n"
        f"להצטרפות לקבוצת המימון (או שנחזור אליכם טלפונית):\n{link}\n\n"
        f"הודעה זו נשלחה מטעם {association_name}. להסרה מהרשימה: {unsubscribe_url}\n"
    )
