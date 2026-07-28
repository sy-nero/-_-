"""
תבנית המייל שנשלח לעסקים.

הגישה: מייל קצר ואנושי, כמו שאדם אמיתי כותב בלי מאמץ. בלי צבעים, בלי לוגו,
בלי כפתורים ובלי שפה שיווקית. התייחסות קצרה לעסק (סוג ושכונה), ושאלה ישירה
עם מי לדבר. הפנייה: להשיב למייל.
"""

# מיפוי סוג העסק (Google type) לשם עברי, לפנייה אישית
FIELD_NOUNS = {
    "bakery": "מאפייה",
    "restaurant": "מסעדה",
    "cafe": "בית קפה",
    "clothing_store": "חנות בגדים",
    "grocery_store": "מכולת",
    "convenience_store": "מרכול",
    "hair_care": "מספרה",
    "beauty_salon": "מכון יופי",
    "book_store": "חנות ספרים",
    "electronics_store": "חנות אלקטרוניקה",
    "furniture_store": "חנות רהיטים",
    "jewelry_store": "חנות תכשיטים",
    "shoe_store": "חנות נעליים",
    "hardware_store": "חנות כלי עבודה",
    "florist": "חנות פרחים",
    "gift_shop": "חנות מתנות",
    "pharmacy": "בית מרקחת",
    "laundry": "מכבסה",
}


def field_noun(primary_type: str) -> str:
    """שם עסק בעברית לפי סוג, או ריק אם כללי/לא ידוע."""
    return FIELD_NOUNS.get((primary_type or "").lower(), "")


def _saw_clause(field: str = "", neighborhood: str = "") -> str:
    """משפט קצר שמראה שראינו את העסק, לפי הנתונים הקיימים."""
    if field and neighborhood:
        return f", וראיתי שיש לכם {field} ב{neighborhood}."
    if field:
        return f", וראיתי שיש לכם {field}."
    if neighborhood:
        return f", וראיתי שהעסק שלכם ב{neighborhood}."
    return "."


def build_subject(association_name: str, business_name: str = "") -> str:
    if business_name:
        return f"{business_name}, לגבי מימון לעסק"
    return "לגבי מימון לעסק שלכם"


def build_text(
    business_name: str,
    association_name: str,
    sender_name: str,
    sender_title: str,
    field: str = "",
    neighborhood: str = "",
) -> str:
    """גוף המייל כטקסט קצר ואנושי."""
    saw = _saw_clause(field, neighborhood)
    return (
        f"שלום,\n\n"
        f"שמי {sender_name}, מ{association_name}.\n\n"
        f"אנחנו מארגנים עכשיו קבוצה של בעלי עסקים מהמגזר החרדי בשביל להשיג מימון "
        f"בתנאים טובים{saw}\n\n"
        f"עם מי אפשר לדבר על זה אצלכם? אם זה מעניין אתכם, תשיבו לי לכאן עם שם וטלפון "
        f"ואחזור אליכם.\n\n"
        f"תודה,\n"
        f"{sender_name}\n"
        f"{association_name}\n"
    )


def build_html(
    business_name: str,
    association_name: str,
    sender_name: str,
    sender_title: str,
    field: str = "",
    neighborhood: str = "",
) -> str:
    """גוף המייל כ-HTML מינימלי, כדי שיראה כמו מייל רגיל שאדם כתב."""
    saw = _saw_clause(field, neighborhood)
    p = "margin:0 0 14px;"
    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body style="margin:0;padding:0;background:#ffffff;">
  <div dir="rtl" style="direction:rtl;text-align:right;max-width:600px;margin:0 auto;
       padding:22px 20px;font-family:Arial,Helvetica,sans-serif;font-size:16px;
       line-height:1.75;color:#222222;">
    <p style="{p}">שלום,</p>
    <p style="{p}">שמי {sender_name}, מ{association_name}.</p>
    <p style="{p}">
      אנחנו מארגנים עכשיו קבוצה של בעלי עסקים מהמגזר החרדי בשביל להשיג מימון
      בתנאים טובים{saw}
    </p>
    <p style="{p}">
      עם מי אפשר לדבר על זה אצלכם? אם זה מעניין אתכם, תשיבו לי לכאן עם שם וטלפון
      ואחזור אליכם.
    </p>
    <p style="margin:0 0 4px;">תודה,</p>
    <p style="margin:0;">{sender_name}<br>{association_name}</p>
  </div>
</body>
</html>"""
