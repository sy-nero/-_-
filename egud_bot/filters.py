"""
סינון עסקים לפי הקריטריונים של האיגוד:
  - עסק פעיל (OPERATIONAL) — לא סגור לצמיתות/זמנית
  - "עסק חדש" = עד MAX_REVIEW_COUNT ביקורות (0 = בלי ביקורות בכלל)

הערה חשובה: ל-Google Places אין שדה "שנת ייסוד". הפרוקסי הטוב ביותר
ל"עסק חדש (עד שנה)" הוא מספר ביקורות נמוך/אפס — וזה גם הקריטריון השני
שהוגדר. לכן שני התנאים ("שנת ייסוד עד שנה" ו-"אין תגובות") מתמזגים
לתנאי אחד יישים: מספר ביקורות <= סף.
"""
from dataclasses import dataclass


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
    return True
