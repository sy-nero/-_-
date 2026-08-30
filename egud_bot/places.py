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

# סוגי עסקי שירות/מקצוע (לקמפיין CRM) — עסקים שמנהלים לקוחות ולידים.
SERVICE_BUSINESS_TYPES_QUERY = [
    "real_estate_agency", "insurance_agency", "lawyer", "accounting",
    "travel_agency", "moving_company", "car_repair", "car_dealer",
    "electrician", "plumber", "painter", "locksmith", "storage",
    "dentist", "doctor", "physiotherapist", "veterinary_care",
    "beauty_salon", "hair_care", "spa", "gym",
]

# קמפיין מענק 4.56 — כל הענפים הזכאים, בתעדוף לסקטורים שהכי צורכים שדרוג טכנולוגי.
# הסורק עוצר ב-50 מיילים, לכן הסוגים עתירי-הטכנולוגיה מופיעים ראשונים ונאספים קודם.
GRANT_PRIORITY_TYPES = [
    # קמעונאות עתירת-מלאי (POS, ניהול מלאי, מכירות אונליין)
    "electronics_store", "furniture_store", "hardware_store", "home_goods_store",
    "jewelry_store", "department_store", "supermarket", "clothing_store",
    "shoe_store", "book_store", "pharmacy", "bicycle_store", "pet_store",
    "toy_store",
    # רכב (מוסכים, סוכנויות)
    "car_dealer", "car_repair",
    # שירותים עם ניהול לקוחות (CRM, תיקים, זימון תורים)
    "real_estate_agency", "insurance_agency", "lawyer", "accounting",
    "travel_agency",
    # קליניקות עם מערכות וציוד
    "dentist", "doctor", "physiotherapist", "veterinary_care",
    # לוגיסטיקה ואחסנה
    "moving_company", "storage",
]
GRANT_EXTRA_QUERY = ["meal_takeaway", "meal_delivery", "supermarket"]
GRANT_BUSINESS_TYPES_QUERY = list(dict.fromkeys(
    GRANT_PRIORITY_TYPES
    + LOCAL_BUSINESS_TYPES + SERVICE_BUSINESS_TYPES_QUERY + GRANT_EXTRA_QUERY
))


# קמפיין גיוס סוכנים (agent) — בעלי מקצוע שיש להם יחסי אמון עם בעלי עסקים.
# ל-Google Places יש סוג מקום רק ל"משרד רואי חשבון" (accounting); מאמנים
# עסקיים, מטפלים ובעלי עסקים מהקהילה אין להם סוג מקום — אותם מייבאים מ-CSV
# (python main.py import --campaign agent agents.csv). ראו docs/agents.md.
AGENT_BUSINESS_TYPES_QUERY = ["accounting"]

LEGACY_NEARBY_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
LEGACY_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"


class PlacesClient:
    """לקוח ל-Places API (New / v1)."""

    mode = "new"

    def __init__(self, api_key: str, request_delay: float = 1.0):
        self.api_key = api_key
        self.request_delay = request_delay
        self.session = requests.Session()

    def enrich_contact(self, lead) -> None:
        """ב-API החדש האתר/טלפון כבר הגיעו בסריקה — אין צורך בהעשרה."""
        return None

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
        self, lat: float, lng: float, radius_meters: float,
        included_types: list[str] | None = None,
    ) -> dict[str, dict]:
        """
        סורק נקודה אחת על פני כל סוגי העסקים ומחזיר מילון {place_id: place}.
        פיצול לפי סוג עוקף את מגבלת 20 התוצאות לבקשה.
        """
        found: dict[str, dict] = {}
        for biz_type in (included_types or LOCAL_BUSINESS_TYPES):
            places = self.search_nearby(lat, lng, radius_meters, [biz_type])
            for place in places:
                pid = place.get("id")
                if pid and pid not in found:
                    found[pid] = place
            time.sleep(self.request_delay)
        return found


def _legacy_to_new(result: dict) -> dict:
    """ממיר תוצאת Nearby של ה-API הישן למבנה של ה-API החדש (כדי לאחד את הקוד)."""
    loc = (result.get("geometry", {}) or {}).get("location", {}) or {}
    return {
        "id": result.get("place_id", ""),
        "displayName": {"text": result.get("name", "")},
        "formattedAddress": result.get("vicinity", "") or result.get("formatted_address", ""),
        "location": {"latitude": loc.get("lat", 0.0), "longitude": loc.get("lng", 0.0)},
        "rating": result.get("rating"),
        "userRatingCount": result.get("user_ratings_total", 0) or 0,
        "websiteUri": "",  # מגיע בקריאת Details נפרדת (enrich_contact)
        "nationalPhoneNumber": "",
        "businessStatus": result.get("business_status", ""),
        "types": result.get("types", []),
        "primaryType": (result.get("types") or [""])[0],
    }


class LegacyPlacesClient:
    """
    לקוח ל-Places API הישן (maps.googleapis.com/maps/api/place).
    בשימוש כשה-API החדש חסום בפרויקט. תומך בעימוד (next_page_token) ומעשיר
    אתר/טלפון דרך קריאת Place Details.
    """

    mode = "legacy"

    def __init__(self, api_key: str, request_delay: float = 1.0, max_pages_per_type: int = 1):
        self.api_key = api_key
        self.request_delay = request_delay
        self.max_pages_per_type = max_pages_per_type
        self.session = requests.Session()

    def search_nearby_type(
        self, lat: float, lng: float, radius_meters: float, biz_type: str
    ) -> list[dict]:
        results: list[dict] = []
        params = {
            "location": f"{lat},{lng}",
            "radius": int(radius_meters),
            "type": biz_type,
            "language": "he",
            "key": self.api_key,
        }
        for page in range(self.max_pages_per_type):
            try:
                resp = self.session.get(LEGACY_NEARBY_URL, params=params, timeout=30)
                data = resp.json()
            except (requests.RequestException, ValueError) as exc:
                logger.warning("בקשת Places (legacy) נכשלה: %s", exc)
                break

            status = data.get("status")
            if status not in ("OK", "ZERO_RESULTS"):
                logger.warning("Places (legacy) status=%s: %s", status,
                               data.get("error_message", ""))
                break
            results.extend(data.get("results", []))

            token = data.get("next_page_token")
            if not token or page + 1 >= self.max_pages_per_type:
                break
            # ה-token נהיה תקף רק אחרי השהיה קצרה
            time.sleep(2.0)
            params = {"pagetoken": token, "key": self.api_key}
        return results

    def scan_point(self, lat: float, lng: float, radius_meters: float,
                   included_types: list[str] | None = None) -> dict[str, dict]:
        found: dict[str, dict] = {}
        for biz_type in (included_types or LOCAL_BUSINESS_TYPES):
            for result in self.search_nearby_type(lat, lng, radius_meters, biz_type):
                pid = result.get("place_id")
                if pid and pid not in found:
                    found[pid] = _legacy_to_new(result)
            time.sleep(self.request_delay)
        return found

    def enrich_contact(self, lead) -> None:
        """ממלא אתר וטלפון לליד דרך Place Details (רק ללידים שעברו סינון)."""
        if not lead.place_id:
            return
        params = {
            "place_id": lead.place_id,
            "fields": "website,formatted_phone_number",
            "language": "he",
            "key": self.api_key,
        }
        try:
            data = self.session.get(LEGACY_DETAILS_URL, params=params, timeout=30).json()
        except (requests.RequestException, ValueError) as exc:
            logger.debug("Details (legacy) נכשל עבור %s: %s", lead.place_id, exc)
            return
        result = data.get("result", {}) or {}
        if result.get("website"):
            lead.website = result["website"]
        if result.get("formatted_phone_number") and not lead.phone:
            lead.phone = result["formatted_phone_number"]


def _new_api_available(api_key: str) -> bool:
    """בדיקת probe: האם ה-API החדש זמין למפתח (לא חסום)."""
    try:
        resp = requests.post(
            PLACES_NEARBY_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "places.id",
            },
            json={
                "includedTypes": ["bakery"],
                "maxResultCount": 1,
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": 31.79, "longitude": 35.22},
                        "radius": 100.0,
                    }
                },
            },
            timeout=20,
        )
    except requests.RequestException:
        return False
    return resp.status_code == 200


def make_client(cfg):
    """
    בוחר לקוח לפי PLACES_API_MODE:
      - 'new'    → API חדש בלבד
      - 'legacy' → API ישן בלבד
      - 'auto'   → בודק אם החדש זמין, אחרת נופל ל-legacy
    """
    mode = getattr(cfg, "places_api_mode", "auto").lower()
    if mode == "new":
        return PlacesClient(cfg.google_api_key, cfg.request_delay_seconds)
    if mode == "legacy":
        return LegacyPlacesClient(
            cfg.google_api_key, cfg.request_delay_seconds, cfg.max_pages_per_type
        )
    # auto
    if _new_api_available(cfg.google_api_key):
        logger.info("Places API (New) זמין — משתמש ב-API החדש")
        return PlacesClient(cfg.google_api_key, cfg.request_delay_seconds)
    logger.info("Places API (New) חסום — נופל ל-API הישן (legacy)")
    return LegacyPlacesClient(
        cfg.google_api_key, cfg.request_delay_seconds, cfg.max_pages_per_type
    )
