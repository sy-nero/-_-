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
)


def is_org_email(email: str) -> bool:
    """כתובת של ארגון (דומיין .org / .org.il) — לרוב לא חנות מסחרית."""
    e = (email or "").strip().lower()
    return e.endswith(".org") or e.endswith(".org.il")


def is_excluded_by_name(name: str) -> bool:
    """מזהה מה שאינו חנות קמעונאית חרדית: ערבית, מוסד, או חברה/שירות."""
    n = name or ""
    if ARABIC_RE.search(n):  # עסק מהמגזר הערבי
        return True
    if any(kw in n for kw in EXCLUDED_NAME_KEYWORDS):
        return True
    if any(kw in n for kw in NON_RETAIL_KEYWORDS):
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
