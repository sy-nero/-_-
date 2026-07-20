"""
שכונות חרדיות בירושלים עם קואורדינטות מרכז משוערות.
משמש כמרכזי חיפוש עבור Google Places Nearby Search.

ניתן להוסיף/להסיר שכונות לפי הצורך. הקואורדינטות משוערות (מרכז שכונה),
והרדיוס נקבע ב-.env (SEARCH_RADIUS_METERS).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Neighborhood:
    name: str          # שם השכונה
    lat: float
    lng: float


# שכונות חרדיות מרכזיות בירושלים
HAREDI_NEIGHBORHOODS: list[Neighborhood] = [
    Neighborhood("מאה שערים", 31.7906, 35.2244),
    Neighborhood("גאולה", 31.7897, 35.2200),
    Neighborhood("בית ישראל", 31.7920, 35.2270),
    Neighborhood("הבוכרים", 31.7930, 35.2230),
    Neighborhood("עזרת תורה", 31.7980, 35.2180),
    Neighborhood("סנהדריה", 31.7986, 35.2210),
    Neighborhood("סנהדריה המורחבת", 31.8020, 35.2230),
    Neighborhood("שמואל הנביא", 31.7960, 35.2260),
    Neighborhood("מעלות דפנה", 31.7970, 35.2320),
    Neighborhood("רמת אשכול", 31.8000, 35.2320),
    Neighborhood("תל ארזה", 31.7970, 35.2200),
    Neighborhood("קרית בעלז", 31.7960, 35.2150),
    Neighborhood("רוממה", 31.7960, 35.2050),
    Neighborhood("גבעת שאול", 31.7930, 35.1930),
    Neighborhood("הר נוף", 31.7880, 35.1760),
    Neighborhood("רמת שלמה", 31.8137, 35.2260),
    Neighborhood("רמות", 31.8230, 35.1900),
    Neighborhood("נווה יעקב", 31.8430, 35.2400),
]
