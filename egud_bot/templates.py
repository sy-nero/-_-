"""
תבנית המייל שנשלח לעסקים (עברית, RTL).
"""
from urllib.parse import urlencode


def build_subject(association_name: str, business_name: str = "") -> str:
    if business_name:
        return f"{business_name} — הצטרפו ל{association_name}"
    return f"הצטרפו ל{association_name}"


def _landing_link(base_url: str, place_id: str) -> str:
    """מוסיף פרמטר ref כדי לדעת מאיזה מייל הגיעה ההרשמה."""
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}{urlencode({'ref': place_id, 'src': 'email'})}"


def build_html(
    business_name: str,
    association_name: str,
    landing_url: str,
    unsubscribe_url: str,
    place_id: str = "",
) -> str:
    link = _landing_link(landing_url, place_id)
    greeting = f"שלום {business_name}," if business_name else "שלום,"
    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f4f7;font-family:Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f7;padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0"
             style="max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden;
                    box-shadow:0 1px 4px rgba(0,0,0,0.08);">
        <tr>
          <td style="background:#1f3a5f;padding:24px;text-align:center;">
            <h1 style="margin:0;color:#ffffff;font-size:22px;">{association_name}</h1>
          </td>
        </tr>
        <tr>
          <td style="padding:32px 28px;color:#2b2b2b;font-size:16px;line-height:1.7;">
            <p style="margin:0 0 16px;">{greeting}</p>
            <p style="margin:0 0 16px;">
              אנחנו פונים אליכם מטעם <strong>{association_name}</strong> — קבוצה שמאגדת
              עסקים מקומיים באזור, ומעניקה לחברים בה ליווי, חשיפה ותמיכה כדי לצמוח
              ולהתפתח.
            </p>
            <p style="margin:0 0 16px;">
              זיהינו את העסק שלכם כעסק חדש ומבטיח באזור, ונשמח מאוד לצרף אתכם לקבוצה.
              החברות כוללת גישה לכלים, להטבות ולרשת קשרים של בעלי עסקים כמוכם.
            </p>
            <p style="margin:0 0 24px;">
              להשלמת פרטים והצטרפות — או כדי שנחזור אליכם טלפונית — לחצו על הכפתור:
            </p>
            <table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 auto;">
              <tr><td align="center" style="border-radius:8px;background:#2e7d32;">
                <a href="{link}" target="_blank"
                   style="display:inline-block;padding:14px 34px;color:#ffffff;
                          text-decoration:none;font-size:17px;font-weight:bold;border-radius:8px;">
                  להרשמה ולפרטים נוספים ›
                </a>
              </td></tr>
            </table>
            <p style="margin:24px 0 0;font-size:14px;color:#666;">
              אם הכפתור לא עובד, העתיקו את הקישור לדפדפן:<br>
              <a href="{link}" style="color:#1f3a5f;">{link}</a>
            </p>
          </td>
        </tr>
        <tr>
          <td style="padding:18px 28px;background:#fafafa;border-top:1px solid #eee;
                     color:#999;font-size:12px;line-height:1.6;text-align:center;">
            הודעה זו נשלחה מטעם {association_name} לעסקים באזור.<br>
            אם אינכם מעוניינים לקבל פניות נוספות,
            <a href="{unsubscribe_url}" style="color:#999;">להסרה מהרשימה לחצו כאן</a>.
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
        f"אנחנו פונים אליכם מטעם {association_name} — קבוצה שמאגדת עסקים מקומיים "
        f"באזור, ומעניקה לחברים ליווי, חשיפה ותמיכה.\n\n"
        f"זיהינו את העסק שלכם כעסק חדש ומבטיח, ונשמח לצרף אתכם.\n\n"
        f"להשלמת פרטים והצטרפות (או שנחזור אליכם טלפונית):\n{link}\n\n"
        f"---\n"
        f"הודעה זו נשלחה מטעם {association_name}. "
        f"להסרה מהרשימה: {unsubscribe_url}\n"
    )
