"""
סינון עסקים לפי הקריטריונים של האיגוד:
  - עסק פעיל (OPERATIONAL) — לא סגור לצמיתות/זמנית
  - "עסק חדש" = עד MAX_REVIEW_COUNT ביקורות (0 = בלי ביקורות בכלל)

הערה חשובה: ל-Google Places אין שדה "שנת ייסוד". הפרוקסי הטוב ביותר
ל"עסק חדש (עד שנה)" הוא מספר ביקורות נמוך/אפס — וזה גם הקריטריון השני
שהוגדר. לכן שני התנאים ("שנת ייסוד עד שנה" ו-"אין תגובות") מתמזגים
לתנאי אחד יישים: מספר ביקורות <= סף.
"""
import re
from dataclasses import dataclass, field

# תווים בערבית — לזיהוי עסקים מהמגזר הערבי (לא רלוונטיים לאיגוד החרדי)
ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")

# סוגי מקומות שאינם עסקים שזקוקים למימון — נסננים החוצה
# (מוסדות ציבור, בנקים, בתי ספר, מוסדות דת, ממשלה, בריאות וכו')
EXCLUDED_TYPES = {
    # חינוך
    "school", "primary_school", "secondary_school", "university",
    "preschool", "library",
    # פיננסים / בנקאות
    "bank", "atm", "accounting",
    # ממשל / ציבורי / חירום
    "local_government_office", "city_hall", "courthouse", "police",
    "fire_station", "post_office", "embassy", "government",
    # דת
    "place_of_worship", "synagogue", "church", "mosque", "hindu_temple",
    "cemetery", "funeral_home",
    # בריאות / מוסדות
    "hospital", "doctor", "dentist",
    # תחבורה / תשתית
    "transit_station", "bus_station", "train_station", "subway_station",
    "airport", "parking",
}

# מילות מפתח בשם שמעידות על מוסד ולא על עסק (Google לא תמיד מסווג נכון)
EXCLUDED_NAME_KEYWORDS = (
    "ישיבה", "ישיבת", "בית המדרש", "בית מדרש", "תלמוד תורה",
    "כולל", "בית כנסת", "בית הכנסת", "סמינר", "אולפנה", "תיכון",
    "בית ספר", "בית-ספר", "גן ילדים", "מעון", "עמותה", "עמותת",
    "מוסדות", "משטרה", "עירייה", "עיריית", "מתנ\"ס", "מתנס",
    "בית חולים", "קופת חולים", "בנק ", "לשכת", "מועצה דתית",
    "חסד", "ארגון", "גמח", 'גמ"ח', "תנועת נוער", "תנועת",
    # מוסדות עם שם באנגלית
    "University", "College", "Collage", "Orphanage", "Yeshiva", "Yeshivat",
    "Kollel", "Seminary", "Academy", "Foundation", "Institute",
)


# רשימת היתר: רק אלה נחשבים חנות קמעונאית. הסוג הראשי (primary_type) של Google
# חייב להיות אחד מאלה, אחרת העסק נפסל (whitelist — מדויק הרבה יותר מרשימת חסימה).
RETAIL_STORE_TYPES = {
    "store", "clothing_store", "shoe_store", "jewelry_store", "bakery",
    "grocery_store", "convenience_store", "supermarket", "gift_shop",
    "book_store", "florist", "electronics_store", "furniture_store",
    "hardware_store", "pharmacy", "home_goods_store", "department_store",
    "liquor_store", "pet_store", "bicycle_store", "food", "shopping_mall",
    "toy_store", "cosmetics_store", "market",
}


def is_retail_shop(primary_type: str, types=()) -> bool:
    """
    חנות קמעונאית = יש לה סוג של חנות (מבין כל הסוגים, לא רק הראשי),
    והסוג הראשי אינו שירות/הסעדה/חברה. ה-primary_type של ה-API הישן גנרי
    לעיתים קרובות, ולכן בודקים את כל רשימת הסוגים.
    """
    pt = (primary_type or "").lower()
    ts = {(t or "").lower() for t in (types or [])}
    ts.add(pt)
    if pt in NON_RETAIL_TYPES:          # שירות/הסעדה/חברה כסוג ראשי
        return False
    return bool(ts & RETAIL_STORE_TYPES)  # חייב להיות בין הסוגים סוג של חנות


# סוגי מקום שאינם חנות קמעונאית (שירותים, אוכל מוכן, חברות, מקצועות) — נסננים
NON_RETAIL_TYPES = {
    # שירותים אישיים
    "hair_care", "beauty_salon", "laundry", "spa", "gym",
    # אוכל מוכן / הסעדה
    "restaurant", "cafe", "meal_takeaway", "meal_delivery", "catering",
    # חברות / נדל"ן / מקצועות / B2B
    "real_estate_agency", "general_contractor", "lawyer", "insurance_agency",
    "accounting", "moving_company", "storage", "travel_agency", "finance",
    "car_repair", "car_dealer", "car_wash", "electrician", "plumber",
    "painter", "roofing_contractor", "car_rental", "gas_station",
    "doctor", "dentist", "hospital", "physiotherapist", "veterinary_care",
}

# מילות מפתח בשם שמעידות על עסק שאינו חנות קמעונאית
NON_RETAIL_KEYWORDS = (
    "הנדסה", "תשתיות", "קבלן", 'נדל"ן', "נדלן", "סיטונאות", "סיטונאי",
    "ייעוץ", "הוצאת ספרים", "הוצאה לאור", "Services", "שירותים",
    "טיול", "טיולי", "טיולים", "Tours", "tours", "סיור", "תיירות",
    "סטודיו", "Studio", "studio",
    "שלטים", "דפוס", "מיתוג", "פרסום", " IT ", "IT Israel",
    "Solutions", "Systems", "טכנולוג", "מחשוב",
    "לבניין", "בנייה", "יזמות", "אחזקות", "השקעות",
)


# רשתות ארציות גדולות / חברות ענק — לא קהל היעד (עסקים קטנים בלבד).
# בדיקה לפי שם (substring). נכללות רק מילים ייחודיות שלא יתפסו עסק קטן בטעות.
CHAIN_NAME_KEYWORDS = (
    "ללין", "Laline", "נעמן", "Naaman", "רמי לוי", "שופרסל", "Shufersal",
    "יינות ביתן", "ויקטורי", "אושר עד", "טיב טעם", "סופר פארם", "Super-Pharm",
    "סופרפארם", "הום סנטר", "Home Center", "מקס סטוק", "Max Stock", "הולמס פלייס",
    "Holmes Place", "קסטרו", "Castro", "רנואר", "Renuar", "פוקס", "Fox Home",
    "H&M", "ZARA", "זארה", "מגה בעיר", "אייס", "ACE", "טרמינל איקס",
    "גולף אנד קו", "אושרי", "מחסני חשמל", "באג", "K.S.P", "קרביץ",
    # מותגים/רשתות חילוניים ארציים — לא מהמגזר החרדי
    "וולט", "Wolt", "טבע נאות", "Teva Naot", "ריפבליק", "Republic",
    "הודיז", "Hoodies", "ING", "מובילי", "Mobili", "מיסטר דונאטס",
    "Mr Donuts", "Mr. Donuts", "בורסה", "Bursa",
)

# דומיינים חסומים: רשתות גדולות + כתובות טכניות (staging/פיתוח) שאינן מייל אמיתי.
BLOCKED_EMAIL_DOMAINS = (
    "laline.co.il", "naaman-vardinon.co.il", "rami-levy.co.il",
    "holmesplace.co.il", "shufersal.co.il", "super-pharm.co.il",
    "delekmotors.co.il", "radware.com", "azurewebsites.net",
    # מותגים/רשתות חילוניים + חברות שאינן קמעונאיות חרדיות
    "wolt.com", "teva-naot.co.il", "republic-store.com", "ingsport.co.il",
    "hoodies.co.il", "mobili.co.il", "mr-donuts.co.il", "thebursa.co.il",
    "adrtech.co.il", "usys.co.il", "brillind.co.il", "poenta.vip", "arvana.co",
    # כתובות זבל/ברירת מחדל + חברות ענק + רשתות (חוזרות בסריקות)
    "google.com", "ourdomain.com", "hazorfim.co.il", "kpmg.com", "orcam.com",
    "mysite.com", "example.com", "domain.com", "wixsite.com",
    # פלטפורמות/בוני-אתרים (כתובת שגויה שנגרדת מאתר העסק) + מלונות ענק/לא-מגזר
    "web3d.co.il", "vio.com", "dvhl.de", "danhotels.com", "amcol.co.il",
    "olivetreehotel.co.il", "grandbeach.co.il", "ambassadorcollection.com",
    "holyestates.com",
)

# דפוסים בדומיין שמעידים על כתובת טכנית/לא-אמיתית (לא לשלוח אליהם)
BLOCKED_DOMAIN_PATTERNS = ("staging", "azurewebsites.net", "herokuapp", "-dev.", ".test")


def is_org_email(email: str) -> bool:
    """כתובת של ארגון (דומיין .org / .org.il) — לרוב לא חנות מסחרית."""
    e = (email or "").strip().lower()
    return e.endswith(".org") or e.endswith(".org.il")


# ספקי מייל חינמיים/אישיים — סימן לעסק זעיר (לא חברה מבוססת)
FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "walla.com", "walla.co.il", "hotmail.com",
    "hotmail.co.il", "outlook.com", "outlook.co.il", "yahoo.com", "ymail.com",
    "icloud.com", "live.com", "aol.com", "bezeqint.net", "013.net", "013net.co.il",
    "013.net.il", "inter.net.il", "netvision.net.il", "zahav.net.il", "012.net.il",
}

# סימני חברה רשומה בשם (בע"מ / Ltd) — לרוב יש דוחות מבוקרים (תנאי סף למענק)
LTD_MARKERS = ('בע"מ', "בע”מ", "בע'מ", "בעמ", " Ltd", " LTD", " ltd", "Inc")


def is_free_email(email: str) -> bool:
    e = (email or "").strip().lower()
    if "@" not in e:
        return True
    return e.rsplit("@", 1)[1] in FREE_EMAIL_DOMAINS


def looks_established(name: str, email: str) -> bool:
    """הערכה גסה של 'חברה מבוססת' (לא עסק זעיר) לקמפיין המענק:
    דומיין מייל עסקי משלה, או 'בע"מ'/Ltd בשם."""
    if not is_free_email(email):
        return True
    return any(m in (name or "") for m in LTD_MARKERS)


def is_blocked_email(email: str) -> bool:
    """כתובת של רשת גדולה, ארגון, או דומיין טכני — לא לשלוח אליה."""
    e = (email or "").strip().lower()
    if not e or "@" not in e:
        return True
    domain = e.rsplit("@", 1)[1]
    if is_org_email(e):
        return True
    if any(domain == d or domain.endswith("." + d) for d in BLOCKED_EMAIL_DOMAINS):
        return True
    if any(p in domain for p in BLOCKED_DOMAIN_PATTERNS):
        return True
    return False


def is_excluded_by_name(name: str) -> bool:
    """מזהה מה שאינו חנות קמעונאית חרדית: ערבית, מוסד, או חברה/שירות."""
    n = name or ""
    if ARABIC_RE.search(n):  # עסק מהמגזר הערבי
        return True
    if any(kw in n for kw in EXCLUDED_NAME_KEYWORDS):
        return True
    if any(kw in n for kw in NON_RETAIL_KEYWORDS):
        return True
    if any(kw in n for kw in CHAIN_NAME_KEYWORDS):  # רשת גדולה
        return True
    return False


@dataclass
class BusinessLead:
    place_id: str
    name: str
    address: str
    lat: float
    lng: float
    phone: str
    website: str
    rating: float | None
    review_count: int
    business_status: str
    primary_type: str
    neighborhood: str = ""
    types: list = field(default_factory=list)

    @classmethod
    def from_place(cls, place: dict, neighborhood: str = "") -> "BusinessLead":
        loc = place.get("location", {}) or {}
        return cls(
            place_id=place.get("id", ""),
            name=(place.get("displayName") or {}).get("text", ""),
            address=place.get("formattedAddress", ""),
            lat=loc.get("latitude", 0.0),
            lng=loc.get("longitude", 0.0),
            phone=place.get("nationalPhoneNumber")
            or place.get("internationalPhoneNumber", ""),
            website=place.get("websiteUri", ""),
            rating=place.get("rating"),
            review_count=int(place.get("userRatingCount", 0) or 0),
            business_status=place.get("businessStatus", ""),
            primary_type=place.get("primaryType", ""),
            neighborhood=neighborhood,
            types=place.get("types", []) or [],
        )


def passes_filters(
    lead: BusinessLead,
    max_review_count: int = 0,
    require_operational: bool = True,
) -> bool:
    """בודק אם עסק עומד בקריטריונים של האיגוד."""
    if require_operational and lead.business_status not in ("", "OPERATIONAL"):
        return False
    if lead.review_count > max_review_count:
        return False
    # רק חנות קמעונאית: יש סוג של חנות והסוג הראשי אינו שירות/חברה
    if not is_retail_shop(lead.primary_type, lead.types):
        return False
    # פסילה נוספת לפי מילות מפתח בשם (ישיבה, חברת הנדסה, סיטונאות, University וכו')
    if is_excluded_by_name(lead.name):
        return False
    return True


# ============ קמפיין CRM: עסקי שירות ומקצוע (מנהלים לקוחות/לידים) ============
# סוגי עסקי שירות שמתאימים ל-CRM (משרדים, סוכנויות, קליניקות, מוסכים וכו')
SERVICE_BUSINESS_TYPES = {
    "real_estate_agency", "insurance_agency", "lawyer", "accounting",
    "travel_agency", "moving_company", "car_repair", "car_dealer", "car_wash",
    "car_rental", "electrician", "plumber", "painter", "locksmith", "storage",
    "dentist", "doctor", "physiotherapist", "veterinary_care",
    "beauty_salon", "hair_care", "spa", "gym",
}

# מוסדות ציבור/דת/חינוך/ממשל שנפסלים גם בקמפיין CRM (בלי doctor/dentist שהם קליניקות פרטיות)
SERVICE_EXCLUDED_TYPES = {
    "school", "primary_school", "secondary_school", "university", "preschool",
    "library", "bank", "atm", "local_government_office", "city_hall",
    "courthouse", "police", "fire_station", "post_office", "embassy",
    "government", "place_of_worship", "synagogue", "church", "mosque",
    "hindu_temple", "cemetery", "funeral_home", "hospital", "transit_station",
    "bus_station", "train_station", "subway_station", "airport", "parking",
}


def is_service_business(primary_type: str, types=()) -> bool:
    """עסק שירות/מקצוע שמנהל לקוחות (מתאים ל-CRM), ואינו מוסד ציבורי."""
    ts = {(t or "").lower() for t in (types or [])}
    ts.add((primary_type or "").lower())
    if ts & SERVICE_EXCLUDED_TYPES:
        return False
    return bool(ts & SERVICE_BUSINESS_TYPES)


def is_excluded_by_name_service(name: str) -> bool:
    """פסילת שם לקמפיין CRM: ערבית, מוסד, או רשת גדולה (בלי מילות ה'לא-קמעונאי')."""
    n = name or ""
    if ARABIC_RE.search(n):
        return True
    if any(kw in n for kw in EXCLUDED_NAME_KEYWORDS):
        return True
    if any(kw in n for kw in CHAIN_NAME_KEYWORDS):
        return True
    return False


def passes_filters_service(
    lead: BusinessLead,
    max_review_count: int = 0,
    require_operational: bool = True,
) -> bool:
    """קריטריונים לקמפיין CRM: עסק שירות/מקצוע פעיל, לא מוסד, לא רשת."""
    if require_operational and lead.business_status not in ("", "OPERATIONAL"):
        return False
    if lead.review_count > max_review_count:
        return False
    if not is_service_business(lead.primary_type, lead.types):
        return False
    if is_excluded_by_name_service(lead.name):
        return False
    return True


# ענפי הכלכלה הזכאים למענק 4.56 לפי הסיווג האחיד של הלמ"ס:
# תעשייה מסורתית + סדרים G (מסחר ותיקון רכב), H (תחבורה/אחסנה),
# I (אירוח ואוכל), N (ניהול ותמיכה), וענפים 95/96 מסדר S (תיקונים ושירותים אישיים).
GRANT_ELIGIBLE_TYPES = (
    RETAIL_STORE_TYPES            # G: מסחר קמעונאי/סיטונאי
    | SERVICE_BUSINESS_TYPES     # N, 95, 96 ומקצועות: שירותים, מוסכים, קליניקות, יופי
    | {
        # I: שירותי אוכל (מסעדות/קפה/קייטרינג). מלונות (lodging) הוצאו בכוונה —
        # הם הכניסו רשתות גדולות ומלונות שאינם מהמגזר.
        "restaurant", "cafe", "meal_takeaway", "meal_delivery", "bakery",
        "food", "catering",
        # H: תחבורה, אחסנה, שילוח
        "moving_company", "storage",
        # 95/96: תיקונים ושירותים אישיים
        "laundry",
    }
)


def passes_filters_grant(
    lead: BusinessLead,
    max_review_count: int = 0,
    require_operational: bool = True,
) -> bool:
    """
    קריטריונים למענק 4.56: עסק מענף כלכלה זכאי (תעשייה מסורתית / מסחר / תחבורה /
    אירוח ואוכל / שירותים / תיקונים), ולא מוסד ציבורי או רשת. אין סינון לפי מספר
    ביקורות (המענק דורש עסק מבוסס עם ותק, לא דווקא חדש).
    """
    if require_operational and lead.business_status not in ("", "OPERATIONAL"):
        return False
    ts = {(t or "").lower() for t in (lead.types or [])}
    ts.add((lead.primary_type or "").lower())
    if ts & SERVICE_EXCLUDED_TYPES:          # מוסד ציבור/דת/חינוך/ממשל/בריאות ציבורי
        return False
    if not (ts & GRANT_ELIGIBLE_TYPES):
        return False
    if is_excluded_by_name_service(lead.name):
        return False
    return True
