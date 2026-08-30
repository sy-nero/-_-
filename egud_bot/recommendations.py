"""
איתור המלצות אמיתיות על סוכן פוטנציאלי.

מייל הגיוס נפתח ב"ראיתי המלצה עליך" — ולכן חייבת להיות המלצה אמיתית מאחורי
המשפט. המודול הזה מחפש אותה בשלושה מקורות, לפי סדר אמינות:

  1. ביקורות Google על המשרד (הכי אמין — לקוחות אמיתיים, טקסט גלוי).
  2. עמוד "המלצות / לקוחות ממליצים" באתר המשרד.
  3. חיפוש Google ("<שם> המלצות") — רק אם מוגדר Custom Search.

בנוסף המודול מזהה בטקסט ההמלצות **למה דווקא הוא**: האם הממליצים הם בעלי
עסקים (ולא שכירים), האם מדובר בליווי שוטף, והאם יש ותק. זה הנימוק שנכנס
למייל. אם לא נמצאה המלצה — לא ממציאים אחת, והמשפט פשוט יורד מהמייל.
"""
import re
import logging
from dataclasses import dataclass, field, asdict
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MAX_QUOTE_CHARS = 140
MIN_QUOTE_CHARS = 40

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EgudBot/1.0)"}

# הממליץ הוא בעל עסק ולא שכיר — הסימן הכי חשוב (זה ה-ICP שלנו)
OWNER_HINTS = (
    "בעל עסק", "בעלת עסק", "בעלי עסקים", "העסק שלי", "העסק שלנו", "לעסק שלי",
    "החברה שלי", "החברה שלנו", "עצמאי", "עצמאית", "עוסק מורשה", "עוסק פטור",
    "פתחתי עסק", "פתיחת עסק", "החנות שלי", "המשרד שלי", "העובדים שלי",
    'בע"מ', "מחזור", "ספקים", "חשבוניות",
    # בהמלצה על רו"ח, אזכור "העסק" הוא כמעט תמיד העסק של הממליץ עצמו
    "את העסק", "העסק", "לעסק", "עסק שלי", "עסק שלנו",
)
# ליווי שוטף (ולא דוח שנתי חד-פעמי) — סימן ליחסי אמון מתמשכים
ONGOING_HINTS = (
    "ליווי", "מלווה", "ליווה", "זמין", "זמינות", "שוטף", "לאורך השנים",
    "כל שנה", "כבר שנים", "ייעוץ", "יעוץ", "צמיחה", "מענה", "סבלנות",
)
# ותק
VETERAN_HINTS = ("שנים", "ותק", "ותיק", "מזה")

# עמודי המלצות נפוצים באתרי משרדים
TESTIMONIAL_PATHS = ["/testimonials", "/reviews", "/recommendations",
                     "/המלצות", "/לקוחות-ממליצים", "/לקוחות"]
TESTIMONIAL_WORDS = ("המלצות", "ממליצים", "לקוחות מספרים", "מה אומרים",
                     "חוות דעת", "סיפורי לקוחות")


@dataclass
class Recommendation:
    """המלצה אמיתית שנמצאה, עם המקור שלה — כדי שאפשר יהיה לאמת אותה."""
    source: str = ""            # google | site | web
    quote: str = ""             # ציטוט קצר מההמלצה
    author: str = ""            # מי כתב אותה
    count: int = 0              # כמה המלצות יש בסך הכול (גוגל)
    rating: float | None = None
    url: str = ""               # קישור לאימות
    signals: list = field(default_factory=list)  # owners | ongoing | veteran

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data) -> "Recommendation | None":
        if not data:
            return None
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    @property
    def is_real(self) -> bool:
        """יש המלצה אמיתית רק אם יש ציטוט, או מסה של ביקורות בגוגל."""
        return bool(self.quote) or self.count >= 3


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _shorten(text: str, limit: int = MAX_QUOTE_CHARS) -> str:
    text = _clean(text).strip('"״”“')
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:־-") + "…"


# ---------------------- זיהוי "למה דווקא הוא" ----------------------
def detect_signals(texts, review_count: int = 0) -> list:
    """מזהה בטקסט ההמלצות מה מייחד את הסוכן הזה עבורנו."""
    blob = " ".join(t for t in texts if t)
    signals = []
    if any(h in blob for h in OWNER_HINTS):
        signals.append("owners")          # הממליצים הם בעלי עסקים — ה-ICP שלנו
    if any(h in blob for h in ONGOING_HINTS):
        signals.append("ongoing")         # ליווי שוטף, לא דוח פעם בשנה
    if review_count >= 10 or any(h in blob for h in VETERAN_HINTS):
        signals.append("veteran")         # ותק ויציבות
    return signals


# ---------------------- מקור 1: ביקורות Google ----------------------
def _review_text(review: dict) -> str:
    text = review.get("text")
    if isinstance(text, dict):                       # Places API (New)
        text = text.get("text", "")
    if not text and isinstance(review.get("originalText"), dict):
        text = review["originalText"].get("text", "")
    return _clean(text or "")


def _review_author(review: dict) -> str:
    author = review.get("authorAttribution")
    if isinstance(author, dict):                     # Places API (New)
        return _clean(author.get("displayName", ""))
    return _clean(review.get("author_name", ""))     # Places API (legacy)


def _pick_review(reviews: list) -> dict | None:
    """
    בוחר את ההמלצה הכי טובה לציטוט: חיובית, מספיק ארוכה, ועדיפות למי
    שכתב אותה כבעל עסק (זה מה שמעניין אותנו).
    """
    candidates = []
    for review in reviews or []:
        if not isinstance(review, dict):
            continue
        text = _review_text(review)
        rating = review.get("rating")
        if len(text) < MIN_QUOTE_CHARS:
            continue
        if rating is not None and rating < 4:
            continue
        candidates.append((any(h in text for h in OWNER_HINTS), len(text), review))
    if not candidates:
        return None
    # קודם המלצה של בעל עסק, ובתוך זה הארוכה ביותר (יש בה יותר מידע אמיתי)
    return max(candidates, key=lambda c: (c[0], c[1]))[2]


def from_place(place_id: str, reviews: list, rating=None,
               review_count: int = 0) -> Recommendation | None:
    """המלצה מתוך ביקורות Google."""
    best = _pick_review(reviews)
    texts = [_review_text(r) for r in (reviews or []) if isinstance(r, dict)]
    rec = Recommendation(
        source="google",
        quote=_shorten(_review_text(best)) if best else "",
        author=_review_author(best) if best else "",
        count=int(review_count or 0),
        rating=rating,
        url=(f"https://www.google.com/maps/place/?q=place_id:{place_id}"
             if place_id else ""),
        signals=detect_signals(texts, int(review_count or 0)),
    )
    # בלי ציטוט נשענים רק על מסת הביקורות — ואז חייב גם דירוג טוב,
    # אחרת "ראיתי את ההמלצות עליך" יהיה משפט מביך מול משרד עם ביקורות רעות.
    if not rec.quote and rating is not None and rating < 4.0:
        return None
    return rec if rec.is_real else None


# ---------------------- מקור 2: עמוד המלצות באתר ----------------------
def _quote_from_html(html: str) -> str:
    """מחלץ ציטוט מעמוד המלצות: blockquote, ואם אין — פסקה בתוך מרכאות."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    for block in soup.find_all(["blockquote", "q"]):
        text = _clean(block.get_text(" "))
        if len(text) >= MIN_QUOTE_CHARS:
            return text

    quoted = re.findall(r'["״“]([^"״”“]{40,300})["״”]', soup.get_text(" "))
    for text in quoted:
        if _clean(text):
            return _clean(text)
    return ""


def from_website(website: str, request_delay: float = 1.0) -> Recommendation | None:
    """מחפש עמוד המלצות באתר המשרד ומחלץ ממנו ציטוט."""
    if not website:
        return None
    if not urlparse(website).scheme:
        website = "https://" + website

    session = requests.Session()
    pages = [urljoin(website, p) for p in TESTIMONIAL_PATHS]

    # גם קישור בעמוד הבית שכתוב עליו "המלצות" / "לקוחות ממליצים"
    try:
        home = session.get(website, headers=HEADERS, timeout=15)
        if home.status_code == 200 and home.text:
            soup = BeautifulSoup(home.text, "html.parser")
            for a in soup.find_all("a", href=True):
                label = _clean(a.get_text(" "))
                if any(w in label for w in TESTIMONIAL_WORDS):
                    pages.insert(0, urljoin(website, a["href"]))
    except requests.RequestException as exc:
        logger.debug("קריאת %s נכשלה: %s", website, exc)

    seen = set()
    for url in pages[:5]:
        if url in seen:
            continue
        seen.add(url)
        try:
            resp = session.get(url, headers=HEADERS, timeout=15)
        except requests.RequestException:
            continue
        if resp.status_code != 200 or not resp.text:
            continue
        quote = _quote_from_html(resp.text)
        if quote:
            return Recommendation(source="site", quote=_shorten(quote), url=url,
                                  signals=detect_signals([quote]))
    return None


# ---------------------- מקור 3: חיפוש Google ----------------------
_SEARCH_SKIP = ("facebook.com", "linkedin.com", "instagram.com", "youtube.com",
                "wikipedia.org", "yad2", "gov.il")


def from_web_search(name: str, search_key: str, search_cx: str
                    ) -> Recommendation | None:
    """מחפש המלצות פומביות על המשרד (Google Custom Search)."""
    if not (name and search_key and search_cx):
        return None
    try:
        resp = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": search_key, "cx": search_cx,
                    "q": f'"{name}" המלצות', "num": 5},
            timeout=20,
        )
        items = resp.json().get("items", []) if resp.status_code == 200 else []
    except (requests.RequestException, ValueError):
        return None

    for item in items:
        link = item.get("link", "")
        if any(s in link for s in _SEARCH_SKIP):
            continue
        snippet = _clean(item.get("snippet", ""))
        # רק תוצאה שבאמת מדברת על המלצות, ולא סתם הזכירה את השם
        if len(snippet) < MIN_QUOTE_CHARS or not any(
                w in snippet + item.get("title", "") for w in TESTIMONIAL_WORDS):
            continue
        return Recommendation(source="web", quote=_shorten(snippet), url=link,
                              signals=detect_signals([snippet]))
    return None


def collect(lead, cfg=None, request_delay: float = 1.0) -> Recommendation | None:
    """
    מחפש המלצה אמיתית על הליד, לפי סדר האמינות. מחזיר None אם אין —
    ואז המייל פשוט לא יטען שראינו המלצה.
    """
    rec = from_place(lead.place_id, getattr(lead, "reviews", None),
                     lead.rating, lead.review_count)
    if rec:
        return rec
    rec = from_website(lead.website, request_delay)
    if rec:
        return rec
    return from_web_search(lead.name,
                           getattr(cfg, "google_search_key", ""),
                           getattr(cfg, "google_search_cx", ""))
