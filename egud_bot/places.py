"""
לקוח ל-Google Places API (New / v1).

מבצע Nearby Search סביב כל שכונה. הערה: ה-Nearby Search החדש מחזיר עד 20
תוצאות לבקשה וללא עימוד, לכן אנחנו מפצלים את הסריקה לפי סוגי עסקים (types)
כדי להגדיל את הכיסוי, ומאחדים לפי place id.
"""
import time
import logging
import requests

logger = logging.getLogger(__name__)

PLACES_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"

# השדות שאנחנו מבקשים מ-Google (FieldMask). ככל שפחות שדות — זול יותר.
FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.rating",
    "places.userRatingCount",
    "places.websiteUri",
    "places.nationalPhoneNumber",
    "places.internationalPhoneNumber",
    "places.types",
    "places.businessStatus",
    "places.primaryType",
])

# סוגי עסקים מקומיים קטנים רלוונטיים. מפצלים לפי סוג כדי לעקוף את מגבלת 20 התוצאות.
LOCAL_BUSINESS_TYPES = [
    "store",
    "restaurant",
    "food",
    "bakery",
    "clothing_store",
    "grocery_store",
    "hair_care",
    "beauty_salon",
    "book_store",
    "electronics_store",
    "furniture_store",
    "jewelry_store",
    "shoe_store",
    "hardware_store",
    "florist",
    "cafe",
    "gift_shop",
    "convenience_store",
    "pharmacy",
    "laundry",
]


class PlacesClient:
    def __init__(self, api_key: str, request_delay: float = 1.0):
        self.api_key = api_key
        self.request_delay = request_delay
        self.session = requests.Session()

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        }

    def search_nearby(
        self,
        lat: float,
        lng: float,
        radius_meters: float,
        included_types: list[str],
        max_results: int = 20,
    ) -> list[dict]:
        """בקשה בודדת ל-Nearby Search."""
        body = {
            "includedTypes": included_types,
            "maxResultCount": max_results,
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": float(radius_meters),
                }
            },
            "languageCode": "he",
            "regionCode": "IL",
        }
        try:
            resp = self.session.post(
                PLACES_NEARBY_URL, headers=self._headers(), json=body, timeout=30
            )
        except requests.RequestException as exc:
            logger.warning("בקשת Places נכשלה: %s", exc)
            return []

        if resp.status_code != 200:
            logger.warning(
                "Places החזיר קוד %s: %s", resp.status_code, resp.text[:300]
            )
            return []

        return resp.json().get("places", [])

    def scan_point(
        self, lat: float, lng: float, radius_meters: float
    ) -> dict[str, dict]:
        """
        סורק נקודה אחת על פני כל סוגי העסקים ומחזיר מילון {place_id: place}.
        פיצול לפי סוג עוקף את מגבלת 20 התוצאות לבקשה.
        """
        found: dict[str, dict] = {}
        for biz_type in LOCAL_BUSINESS_TYPES:
            places = self.search_nearby(lat, lng, radius_meters, [biz_type])
            for place in places:
                pid = place.get("id")
                if pid and pid not in found:
                    found[pid] = place
            time.sleep(self.request_delay)
        return found
