"""
תבנית המייל שנשלח לעסקים.

הגישה: מייל אישי אמיתי מבן אדם (לא ניוזלטר מעוצב). בלי צבעים, בלי לוגו,
בלי כפתורים. טקסט פשוט, בגובה העיניים, חתום בשם ותפקיד, עם התייחסות אישית
לעסק (סוג ושכונה). הפנייה: להשיב למייל.
"""

# מיפוי סוג העסק (Google type) לשם עברי, לפנייה אישית
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
    """שם עסק בעברית לפי סוג, או ריק אם כללי/לא ידוע."""
    return FIELD_NOUNS.get((primary_type or "").lower(), "")


def _business_ref(field: str = "", neighborhood: str = "") -> str:
    """מתאר את העסק לפי הנתונים הקיימים: 'מאפייה בגאולה' / 'עסק במאה שערים' / 'עסק'."""
    if field and neighborhood:
        return f"{field} ב{neighborhood}"
    if field:
        return field
    if neighborhood:
        return f"עסק ב{neighborhood}"
    return "עסק"


def build_subject(association_name: str, business_name: str = "") -> str:
    if business_name:
        return f"{business_name}, בנוגע למימון לעסק שלך"
    return "בנוגע למימון לעסק שלך"


def build_text(
    business_name: str,
    association_name: str,
    sender_name: str,
    sender_title: str,
    field: str = "",
    neighborhood: str = "",
) -> str:
    """גוף המייל כטקסט אישי."""
    greeting = f"שלום {business_name}," if business_name else "שלום,"
    ref = _business_ref(field, neighborhood)
    return (
        f"{greeting}\n\n"
        f"שמי {sender_name}, אני {sender_title} ב{association_name}.\n\n"
        f"אנחנו מארגנים בימים אלה קבוצה של בעלי עסקים מהמגזר, שמטרתה להשיג מימון "
        f"בתנאים הוגנים. ראיתי שיש לך {ref}, אז חשבתי לפנות אליך באופן אישי.\n\n"
        f"אני מכיר את הסיפור טוב מדי: אתה צריך מימון, והבנקים מקשים, מבקשים ערבויות "
        f"שאין לך ומחזירים אותך ריק. בקבוצה שלנו אנחנו נלחמים בשבילך מול הגורמים, "
        f"דואגים שתקבל מימון אמיתי בתנאים הוגנים, ונמצאים לצידך לאורך כל הדרך.\n\n"
        f"אם זה מעניין אותך, פשוט תשיב לי למייל הזה עם שם וטלפון ואחזור אליך עם כל "
        f"הפרטים. בלי שום התחייבות.\n\n"
        f"בהצלחה,\n"
        f"{sender_name}\n"
        f"{sender_title}, {association_name}\n"
    )


def build_html(
    business_name: str,
    association_name: str,
    sender_name: str,
    sender_title: str,
    field: str = "",
    neighborhood: str = "",
) -> str:
    """גוף המייל כ-HTML מינימלי (ללא עיצוב/לוגו), כדי שיראה כמו מייל אישי רגיל."""
    greeting = f"שלום {business_name}," if business_name else "שלום,"
    ref = _business_ref(field, neighborhood)
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
    <p style="{p}">{greeting}</p>
    <p style="{p}">שמי {sender_name}, אני {sender_title} ב{association_name}.</p>
    <p style="{p}">
      אנחנו מארגנים בימים אלה קבוצה של בעלי עסקים מהמגזר, שמטרתה להשיג מימון
      בתנאים הוגנים. ראיתי שיש לך {ref}, אז חשבתי לפנות אליך באופן אישי.
    </p>
    <p style="{p}">
      אני מכיר את הסיפור טוב מדי: אתה צריך מימון, והבנקים מקשים, מבקשים ערבויות
      שאין לך ומחזירים אותך ריק. בקבוצה שלנו אנחנו נלחמים בשבילך מול הגורמים,
      דואגים שתקבל מימון אמיתי בתנאים הוגנים, ונמצאים לצידך לאורך כל הדרך.
    </p>
    <p style="{p}">
      אם זה מעניין אותך, פשוט תשיב לי למייל הזה עם שם וטלפון ואחזור אליך עם כל
      הפרטים. בלי שום התחייבות.
    </p>
    <p style="margin:0 0 4px;">בהצלחה,</p>
    <p style="margin:0;">{sender_name}<br>{sender_title}, {association_name}</p>
  </div>
</body>
</html>"""
