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
              <div style="font-size:18px;font-weight:bold;color:{TEXT};margin-bottom:3px;">{title}</div>
              <div style="font-size:16px;color:{TEXT_2};line-height:1.65;">{desc}</div>
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
        _benefit_row("₪", "חיסכון אמיתי בעלויות",
                     "במקום לשלם ביוקר ליועץ פרטי, כוח הקבוצה מוריד לך את המחיר משמעותית.")
        + _benefit_row("✦", "ליווי מקצועי מלא",
                       "אותו ידע וניסיון של יועצי מימון, בלי העמלות והאחוזים המנופחים.")
        + _benefit_row("♦", "מימון בתנאים הכי טובים",
                       "גישה למקורות מימון והשגת התנאים הטובים ביותר עבור העסק שלך.")
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
            <h1 style="margin:18px 0 4px;color:#ffffff;font-size:32px;line-height:1.3;font-weight:800;">
              נמאס לשלם הון ליועצי מימון?
            </h1>
            <p style="margin:0 0 6px;color:{GOLD};font-size:20px;font-weight:700;">
              קבוצת מימון חדשה לעסקים
            </p>
            <div style="display:inline-block;height:3px;width:64px;background:{GOLD};
                        border-radius:2px;margin:8px 0 0;"></div>
          </td>
        </tr>

        <tr>
          <td style="padding:32px 34px 4px;">
            <p style="margin:0 0 16px;font-size:20px;font-weight:bold;color:{TEXT};">{greeting}</p>
            <p style="margin:0 0 12px;font-size:18px;line-height:1.8;color:{TEXT_2};">
              כל בעל עסק שזקוק למימון יודע כמה זה עולה. יועצי מימון גובים אלפי שקלים
              ואחוזים שמנים מכל עסקה, ובסוף רוב הרווח נשאר אצלם.
            </p>
            <p style="margin:0 0 12px;font-size:18px;line-height:1.8;color:{TEXT_2};">
              לכן אנחנו ב<strong style="color:{TEXT};">איגוד העסקים החרדיים</strong> פותחים בימים אלו
              <strong style="color:{TEXT};">קבוצה שמורידה לך את עלויות יועצי המימון</strong>.
              כוח הקבוצה מביא לך את אותו ליווי מקצועי ואת אותם מקורות מימון,
              בשבריר מהמחיר שהיית משלם לבד.
            </p>
          </td>
        </tr>

        <tr>
          <td style="padding:12px 34px 6px;">
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
                  להשארת פרטים ›
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
    landing_url: str,
    unsubscribe_url: str,
    place_id: str = "",
) -> str:
    """גרסת טקסט פשוט (fallback עבור לקוחות מייל ללא HTML)."""
    link = _landing_link(landing_url, place_id)
    greeting = f"שלום {business_name}," if business_name else "שלום,"
    return (
        f"נמאס לשלם הון ליועצי מימון?\n\n"
        f"{greeting}\n\n"
        f"כל בעל עסק שזקוק למימון יודע כמה זה עולה. יועצי מימון גובים אלפי שקלים "
        f"ואחוזים שמנים מכל עסקה, ובסוף רוב הרווח נשאר אצלם.\n\n"
        f"לכן אנחנו ב{association_name} פותחים בימים אלו קבוצה שמורידה לך את עלויות "
        f"יועצי המימון. כוח הקבוצה מביא לך את אותו ליווי מקצועי ואת אותם מקורות מימון, "
        f"בשבריר מהמחיר שהיית משלם לבד.\n\n"
        f"מה תקבלו בקבוצה:\n"
        f"  • חיסכון אמיתי בעלויות, כוח הקבוצה מוריד לך את המחיר\n"
        f"  • ליווי מקצועי מלא, בלי העמלות והאחוזים המנופחים\n"
        f"  • מימון בתנאים הכי טובים עבור העסק שלך\n\n"
        f"להשארת פרטים:\n{link}\n"
    )
