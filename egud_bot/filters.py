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
    "חסד", "ארגון", "גמח", 'גמ"ח',
)


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
    "painter", "roofing_contractor", "car_rental",
}

# מילות מפתח בשם שמעידות על עסק שאינו חנות קמעונאית
NON_RETAIL_KEYWORDS = (
    "הנדסה", "תשתיות", "קבלן", 'נדל"ן', "נדלן", "סיטונאות", "סיטונאי",
    "ייעוץ", "הוצאת ספרים", "הוצאה לאור", "Services", "שירותים",
)


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
    # פסילת מוסדות שאינם עסקים (בנקים, בתי ספר, משטרה, מוסדות דת וכו')
    all_types = set(lead.types) | {lead.primary_type}
    if all_types & EXCLUDED_TYPES:
        return False
    # רק חנות קמעונאית: פסילת שירותים/הסעדה/חברות (מספרה, מסעדה, נדל"ן וכו')
    if lead.primary_type in NON_RETAIL_TYPES:
        return False
    # פסילה נוספת לפי מילות מפתח בשם (ישיבה, חברת הנדסה, סיטונאות וכו')
    if is_excluded_by_name(lead.name):
        return False
    return True
