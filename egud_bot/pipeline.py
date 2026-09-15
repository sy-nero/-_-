"""
תזמור התהליך המלא: סריקה -> סינון -> איתור מייל -> שמירה -> שליחה.
"""
import json
import math
import os
import re
import time
import logging

from config import Config
from data.neighborhoods import HAREDI_NEIGHBORHOODS, Neighborhood, neighborhoods_for
from egud_bot.places import (make_client, SERVICE_BUSINESS_TYPES_QUERY,
                             GRANT_BUSINESS_TYPES_QUERY,
                             AGENT_BUSINESS_TYPES_QUERY)
from egud_bot.filters import (BusinessLead, passes_filters,
                              passes_filters_service, passes_filters_grant,
                              passes_filters_agent, family_of_query,
                              matches_query, in_requested_city,
                              is_valid_email,
                              is_blocked_email, looks_established)
from egud_bot.email_finder import find_email, find_contact
from egud_bot import recommendations, tracking
from egud_bot.storage import Storage
from egud_bot.mailer import Mailer
from egud_bot import templates

logger = logging.getLogger(__name__)


def _col(row, name: str) -> str:
    """קריאת עמודה מ-sqlite3.Row שאולי חסרה (DB ישן לפני המיגרציה)."""
    try:
        return (row[name] or "").strip()
    except (IndexError, KeyError):
        return ""


def _rec(row) -> dict:
    """ההמלצה שנמצאה על הליד (JSON ב-DB) — ריק אם לא נמצאה."""
    raw = _col(row, "rec_json")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def _render(template_campaign: str, ctx: dict, custom=None):
    """
    מרנדר מייל: נוסח מותאם אם הוגדר לקמפיין, אחרת התבנית המובנית.
    custom הוא (נושא, גוף, תחום־ברירת־מחדל).
    """
    if custom and (custom[0] or custom[1]):
        hint = custom[2] if len(custom) > 2 else ""
        return templates.render_custom(custom[0], custom[1],
                                       profession_hint=hint, **ctx)
    return templates.render(template_campaign, **ctx)


def build_ctx(cfg: Config, campaign: str, lead) -> dict:
    """מרכיב את משתני התבנית מליד (שורת DB או מילון) לפי הקמפיין."""
    from_email, from_name, _, _ = cfg.sender_for(campaign)
    ctx = dict(
        business_name=_col(lead, "name"),
        association_name=cfg.association_name,
        sender_name=from_name,
        sender_title=cfg.sender_title,
        contact_email=cfg.contact_email,
        course_url=cfg.course_url,
        place_id=_col(lead, "place_id"),
        field=templates.field_noun(_col(lead, "primary_type")),
        neighborhood=_col(lead, "neighborhood"),
        first_name=_col(lead, "first_name"),
        intro_how=_col(lead, "intro_how"),
        intro_fact=_col(lead, "intro_fact"),
        intro_why=_col(lead, "intro_why"),
        # מה שהעסק כותב על עצמו באתר, לשימוש ב-{{התמחות}} בנוסח
        specialty=_col(lead, "specialty"),
        rec=_rec(lead),
    )
    if campaign == "agent":
        # מייל הסוכנים חתום אישית בשם מירי מסינרו, ולא בשם האיגוד
        ctx.update(sender_title=cfg.agent_sender_title,
                   company=cfg.agent_company,
                   sender_phone=cfg.agent_sender_phone,
                   website=cfg.agent_website,
                   contact_email=from_email)
    return ctx


def scan(
    cfg: Config,
    storage: Storage,
    neighborhoods: list[Neighborhood] | None = None,
    target_emails: int | None = None,
    campaign: str = "funding",
    city: str = "jerusalem",
) -> dict:
    """
    סורק מקור לפי הקמפיין ושומר לידים חדשים ב-DB.
    funding — חנויות קמעונאיות דרך Google Places (לפי שכונות העיר שנבחרה).
    hr      — עסקים מאתרי דרושים (jobscan).
    agent   — משרדי רו"ח (סוכנים ממליצים) דרך Google Places.
    """
    if campaign == "hr":
        from egud_bot.jobscan import scan_jobs
        target = cfg.target_emails if target_emails is None else target_emails
        return scan_jobs(cfg, storage, target_emails=target)
    if neighborhoods is None:
        neighborhoods = neighborhoods_for(city)
    return scan_retail(cfg, storage, neighborhoods, target_emails, campaign)


def scan_retail(
    cfg: Config,
    storage: Storage,
    neighborhoods: list[Neighborhood] | None = None,
    target_emails: int | None = None,
    campaign: str = "funding",
) -> dict:
    """
    סורק עסקים דרך Google Places לפי שכונות.
    funding/hr — חנויות קמעונאיות. crm — עסקי שירות/מקצוע.
    agent — משרדי רו"ח ותיקים (סוכנים ממליצים).
    """
    neighborhoods = neighborhoods or HAREDI_NEIGHBORHOODS
    target = cfg.target_emails if target_emails is None else target_emails
    # לקמפיין הסוכנים מושכים גם ביקורות — הן הבסיס ל"ראיתי המלצה עליך"
    client = make_client(cfg, include_reviews=(campaign == "agent"))

    # בחירת סוגי חיפוש ומסנן לפי הקמפיין
    if campaign == "crm":
        query_types = SERVICE_BUSINESS_TYPES_QUERY
        passes = passes_filters_service
    elif campaign == "grant":
        query_types = GRANT_BUSINESS_TYPES_QUERY
        passes = passes_filters_grant
    elif campaign == "agent":
        custom = [t.strip() for t in (cfg.agent_types or "").split(",") if t.strip()]
        query_types = custom or AGENT_BUSINESS_TYPES_QUERY

        # כאן הסף הוא מינימום ותק (ולא מקסימום "חדשוּת" כמו בשאר הקמפיינים)
        def passes(lead, _max_reviews, require_operational):
            return passes_filters_agent(lead, cfg.agent_min_reviews,
                                        require_operational,
                                        cfg.agent_min_rating)
    else:
        query_types = None
        passes = passes_filters

    summary = {"scanned": 0, "passed": 0, "new": 0, "with_email": 0, "no_email": 0}
    if campaign == "agent":
        summary["with_rec"] = 0      # כמה מהם נמצאה עליהם המלצה אמיתית

    for nb in neighborhoods:
        logger.info("סורק שכונה: %s (מיילים שנאספו: %d/%d)",
                    nb.name, summary["with_email"], target)
        places = client.scan_point(nb.lat, nb.lng, cfg.search_radius_meters, query_types)
        summary["scanned"] += len(places)

        for place in places.values():
            lead = BusinessLead.from_place(place, neighborhood=nb.name)
            if not lead.place_id:
                continue
            if not passes(lead, cfg.max_review_count, cfg.require_operational):
                continue
            summary["passed"] += 1

            if storage.exists(lead.place_id):
                continue  # כבר טופל בעבר
            summary["new"] += 1

            # העשרת אתר/טלפון (רלוונטי ל-legacy — קריאת Details רק ללידים שעברו סינון)
            client.enrich_contact(lead)

            # קמפיין סוכנים: מחפשים המלצה אמיתית עליו (גוגל / אתר / חיפוש)
            if campaign == "agent":
                rec = recommendations.collect(lead, cfg, cfg.request_delay_seconds)
                lead.rec = rec.as_dict() if rec else {}
                if rec:
                    summary["with_rec"] += 1
                    logger.info("  ★ נמצאה המלצה (%s) על %s", rec.source, lead.name)

            email = find_email(lead.website, cfg.request_delay_seconds) if lead.website else None
            if email and is_blocked_email(email):  # רשת גדולה / ארגון / דומיין טכני
                email = None
            # קמפיין מענק: רק חברות מבוססות (לא עסק זעיר עם gmail ובלי בע"מ)
            if email and campaign == "grant" and not looks_established(lead.name, email):
                email = None
            if email:
                summary["with_email"] += 1
                storage.upsert_lead(lead, email, status="found")
                logger.info("  ✔ מייל נמצא (%d/%d): %s → %s",
                            summary["with_email"], target, lead.name, email)
            else:
                summary["no_email"] += 1
                storage.upsert_lead(lead, None, status="no_email")

            time.sleep(cfg.request_delay_seconds)

            if summary["with_email"] >= target:
                logger.info("הושג יעד של %d מיילים — עוצר את הסריקה.", target)
                logger.info("סיכום סריקה: %s", summary)
                return summary

    if summary["with_email"] < target:
        logger.warning(
            "הסריקה מוצתה עם %d מיילים בלבד (יעד: %d). "
            "רוב העסקים החדשים ללא אתר/מייל — שקלו העלאת MAX_REVIEW_COUNT או הרחבת שכונות.",
            summary["with_email"], target,
        )
    logger.info("סיכום סריקה: %s", summary)
    return summary


# מילות סיום שנספחות לרשימת תחומים ואינן תחום בפני עצמן
_NOISE_RE = re.compile(r"\s*(?:וכדומה|וכולי|וכדו|וכד|וכו|ועוד)['\u2019\u05f3]?\s*$")
_EDGE = "-\u2013\u2014,.\"'\u201c\u201d\u05f4\u05f3 "


# חיפוש הטקסט של Google מתייחס ל-location/radius כהטיה ולא כמסננת, ולכן
# חיפוש "עורכי דין" סביב שכונה בירושלים מחזיר גם משרדים בתל אביב ובחיפה.
# המרחק נמדד כאן ומי שרחוק מדי נפסל — אחרת המייל כותב "באזור ירושלים"
# למשרד בראשון לציון.
# 20 ק"מ היה רחב מדי: מודיעין עילית נמצאת 18.5 ק"מ משכונת רמות ועברה.
# המרחק הגדול ביותר בין שתי שכונות בירושלים -- העיר הפרוסה ביותר ברשימה --
# הוא 10.5 ק"מ, ולכן 13 מכסה כל עיר ברשימה וחוסם את השכנות.
MAX_DISTANCE_KM = float(os.getenv("SCAN_MAX_DISTANCE_KM", "13"))


def _distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """מרחק אווירי בין שתי נקודות (haversine), בקילומטרים."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


#: מילים שפותחות מקצוע. ו' החיבור שלפניהן מפרידה בין שני תחומים
#: ("יועצים עסקיים ומאמנים עסקיים") ולא בין שתי מילים באותו תחום.
#: בלי הפיצול כל המשפט נשלח לגוגל כשאילתה אחת, והוא מחפש את כל המילים
#: יחד -- מה שמחזיר אפס תוצאות בכל שכונה.
_PROFESSION_LEAD = (
    "יועץ", "יועצת", "יועצים", "יועצות", "ייעוץ", "יעוץ",
    "מאמן", "מאמנת", "מאמנים", "מאמנות", "אימון", "ליווי",
    "עורך", "עורכת", "עורכי", "עורכות", "רואה", "רואי", "רו\"ח",
    "מתווך", "מתווכת", "מתווכים", "סוכן", "סוכנת", "סוכני",
    "מנטור", "מנטורית", "מומחה", "מומחית", "מטפל", "מטפלת",
    "אדריכל", "מהנדס", "מעצב", "צלם", "מורה", "מדריך",
)
_CONJ_SPLIT = re.compile(
    r"\s+ו(?=(?:" + "|".join(re.escape(w) for w in _PROFESSION_LEAD) + r")\b)")


def split_query(query: str) -> list[str]:
    """
    מפרק את שדה "תחום לחיפוש" לרשימת מונחי חיפוש.

    מירי כותבת שם רשימה בשפה חופשית — "עורכי דין מסחריים, עובד מעביד,
    חוזים וכדו' -". חיפוש של המחרוזת הזאת כמו שהיא כמעט לא מחזיר תוצאות,
    כי Google מחפש את כל המילים יחד. לכן מפרידים בפסיקים, מנקים את מילות
    הסיום ואת הקווים והמרכאות שנשארו, ומחפשים כל מונח בנפרד. תקציב היעד
    משותף לכל המונחים, ולכן הפירוק לא מכפיל את עלות ה-API.
    """
    terms: list[str] = []
    for part in re.split(r"[,;\n/|]+", query or ""):
        # "יועצים עסקיים ומאמנים עסקיים" הם שני חיפושים, לא אחד
        for piece in _CONJ_SPLIT.split(part):
            term = _NOISE_RE.sub("", piece.strip().strip(_EDGE)).strip(_EDGE)
            if len(term) >= 2 and term not in terms:
                terms.append(term)
    return terms


def search_text_for(term: str, city: str) -> str:
    """
    מונח החיפוש שנשלח בפועל לגוגל, עם שם העיר בתוכו.

    ב-Text Search הישן location ו-radius הם הטיה בלבד ולא מסננת: חיפוש
    שאין לו התאמה מקומית מוחזר מכל הארץ. כך קרה שסריקה החזירה 600
    תוצאות ו-590 מהן נפסלו כרחוקות מדי -- בזבוז של 30 קריאות API.
    שם העיר בתוך הטקסט מצמצם את התוצאות במקור.
    """
    names = PROMPT_CITIES.get(city or "jerusalem")
    if not names or city == "all":
        return term
    city_name = names[0]
    if _normalize_he(city_name) in _normalize_he(term):
        return term                      # העיר כבר שם, לא נכפיל
    return f"{term} {city_name}"


def _normalize_he(text: str) -> str:
    return (text or "").replace("-", " ").replace('"', "").strip().lower()


#: כמה דוגמאות של פסילה להדפיס לפני שמפסיקים להציף את הלוג
_FAR_EXAMPLES = 5
_OFF_FIELD_EXAMPLES = 12


def _log_off_field(counters: dict, name: str) -> None:
    """
    דוגמאות למי שנפסל כ"לא מהתחום".

    "לא מהתחום: 928" יכול להיות שני דברים הפוכים: גוגל החזיר זבל
    (ואז הסינון עובד), או שהסינון מחמיר מדי ופוסל יועצים אמיתיים.
    בלי לראות שמות אי אפשר לדעת מי משניהם.
    """
    if counters["לא מהתחום"] > _OFF_FIELD_EXAMPLES:
        return
    logger.info("    לא מהתחום: %s", (name or "?")[:60])
    if counters["לא מהתחום"] == _OFF_FIELD_EXAMPLES:
        logger.info("    (לא מציג עוד דוגמאות של לא מהתחום)")


def _log_far(counters: dict, name: str, address: str, km: float = 0.0) -> None:
    if counters["רחוקים מדי"] > _FAR_EXAMPLES:
        return
    where = (address or "").strip() or "בלי כתובת"
    distance = f" ({km:.0f} ק\"מ)" if km else ""
    logger.info("    רחוק מדי: %s — %s%s", (name or "?")[:40], where[:60], distance)
    if counters["רחוקים מדי"] == _FAR_EXAMPLES:
        logger.info("    (לא מציג עוד דוגמאות של רחוקים מדי)")


def _handle_place(cfg: Config, storage: Storage, client, place: dict,
                  nb, counters: dict, reviews_floor: int,
                  rating_floor: float, family: str = "",
                  run_id: str = "", city: str = "",
                  seen: set | None = None) -> None:
    """
    מטפל בעסק אחד מתוצאות החיפוש: סינון, המלצה, מייל ושמירה.

    משותף לסריקה הרציפה (scan_by_query) ולסריקה במנות (scan_chunk), כדי
    ששתיהן יסננו וישמרו בדיוק אותו דבר.
    """
    lead = BusinessLead.from_place(place, neighborhood=nb.name)
    if not lead.place_id:
        return
    # חיפוש הטקסט מחזיר גם עסקים בעיר אחרת לגמרי. הכתובת היא הבדיקה
    # המדויקת (שם העיר כתוב בה), והמרחק הוא רשת ביטחון לכתובת חלקית.
    # "רחוקים מדי: 590" בלי דוגמאות לא מסביר כלום. חמש הראשונות נרשמות
    # ללוג, ומהן רואים מיד אם החיפוש נשלח לעיר הלא נכונה.
    if not in_requested_city(lead, city):
        counters["רחוקים מדי"] += 1
        _log_far(counters, lead.name, lead.address)
        return
    if lead.lat and lead.lng:
        km = _distance_km(nb.lat, nb.lng, lead.lat, lead.lng)
        if km > MAX_DISTANCE_KM:
            counters["רחוקים מדי"] += 1
            _log_far(counters, lead.name, lead.address, km)
            return
    # חיפוש הטקסט מחזיר "מה שמזכיר" ולא "מה שביקשת" -- כאן נפסל מי שאינו
    # מהתחום, כדי שלא נכתוב למשרד תיווך "ראיתי את ההמלצות עליך כעורך דין"
    if not matches_query(lead, family):
        counters["לא מהתחום"] += 1
        _log_off_field(counters, lead.name)
        return
    if not passes_filters_agent(lead, reviews_floor, cfg.require_operational,
                                rating_floor, any_type=True):
        return
    # אותו עסק נמצא שוב ושוב -- בכל שכונה סמוכה ובכל מונח חיפוש. בלי
    # הסינון הזה "עברו סינון" ספר כל מציאה מחדש, והציג 614 כשמדובר
    # בפועל בכמה עשרות עסקים שונים.
    if seen is not None:
        if lead.place_id in seen:
            return
        seen.add(lead.place_id)
    counters["עברו סינון"] += 1
    if storage.exists(lead.place_id):
        counters["כבר במאגר"] += 1
        return
    counters["חדשים"] += 1

    client.enrich_contact(lead)
    rec = recommendations.collect(lead, cfg, cfg.request_delay_seconds)
    lead.rec = rec.as_dict() if rec else {}
    if rec:
        counters["עם המלצה"] += 1

    email = find_email(lead.website, cfg.request_delay_seconds) if lead.website else None
    if email and is_blocked_email(email):
        email = None
    if email:
        counters["עם מייל"] += 1
        storage.upsert_lead(lead, email, status="found", run_id=run_id)
        logger.info("  \u2714 %s \u2192 %s", lead.name, email)
    else:
        counters["בלי מייל"] += 1
        storage.upsert_lead(lead, None, status="no_email", run_id=run_id)


def new_counters() -> dict:
    return {"נסרקו": 0, "רחוקים מדי": 0, "לא מהתחום": 0, "עברו סינון": 0,
            "כבר במאגר": 0, "חדשים": 0, "עם מייל": 0, "בלי מייל": 0,
            "עם המלצה": 0}


# ---------------------------------------------------------------------------
# פרומפט חופשי -> פרמטרי חיפוש
# ---------------------------------------------------------------------------
# במקום חמישה שדות נפרדים, כותבים משפט אחד:
#   "תחפש עורכי דין מסחריים בירושלים עם לפחות 3 ביקורות, תביאי 30"
# ומכאן נשלפים העיר, הכמות, תנאי הסף והתחום. מה שלא נאמר -- נשאר בברירת
# המחדל, ואף פעם לא מומצא.
#
# הפירוק מוצג למשתמשת לפני שהחיפוש רץ, כי מנתח שטועה בשקט גרוע משדות.
PROMPT_CITIES = {
    "jerusalem": ("ירושלים", "בירושלים", "י-ם"),
    "bnei-brak": ("בני ברק", "בבני ברק", "בני-ברק"),
    "beitar": ("ביתר עילית", "ביתר"),
    "modiin-illit": ("מודיעין עילית", "קרית ספר", "קריית ספר"),
    "elad": ("אלעד",),
    "beit-shemesh": ("בית שמש", "רמת בית שמש"),
    "ashdod": ("אשדוד",),
    "all": ("כל הערים החרדיות", "כל הערים", "כל הארץ", "בכל הארץ"),
}

# מילים שמסמנות למה מתייחס מספר שמופיע לידן
_REVIEW_WORDS = ("ביקורות", "ביקורת", "תגובות", "תגובה", "המלצות", "המלצה", "חוות דעת")
_RATING_WORDS = ("דירוג", "כוכבים", "כוכב", "ציון")
_TARGET_WORDS = ("נמענים", "לידים", "תוצאות", "אנשים", "עסקים", "שמות", "כתובות")

# ביטויים שהם הוראה ולא תחום, ויורדים לפני שנשארים עם המקצוע
_PROMPT_NOISE = (
    "תחפש", "תחפשי", "חפש", "חפשי", "תביא", "תביאי", "הבא", "הביאי",
    "תמצא", "תמצאי", "מצא", "מצאי", "אני רוצה", "רוצה", "בבקשה",
    "לפחות", "מינימום", "לכל הפחות", "ומעלה", "טובות", "טובים", "חיוביות",
    "חיוביים", "באזור", "אזור", "בעיר", "עם", "של", "שיש להם", "שיש",
    "ב", "מ", "עד", "לי", "לנו", "לך", "כאלה", "כאלו",
    # תיאורים שמירי כותבת בסוף המשפט, ואינם חלק מהמקצוע
    "באינטרנט", "באינרנטט", "ברשת", "בגוגל", "שיש להם", "שהם", "והם",
    "נראים", "נראה", "רציניים", "רצינים", "רציני", "גדולים", "גדול",
    "ותיקים", "ותיק", "מבוססים", "מבוסס", "מצליחים", "מצליח", "טוב",
    "וגם", "גם", "או",
)

#: מונח חיפוש ל-Google Places צריך להיות קצר. יותר מזה כמעט תמיד אומר
#: שנגררה לתוכו פרוזה מהמשפט, ואז גוגל מחפש את כל המילים יחד ולא מוצא דבר.
MAX_TERM_WORDS = 4


def _to_float(text: str) -> float | None:
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def parse_prompt(prompt: str) -> dict:
    """
    מפרק משפט חופשי לפרמטרי חיפוש.

    מחזיר תמיד את כל המפתחות; ערך None פירושו "לא נאמר", והקורא משאיר
    את ברירת המחדל שלו.
    """
    text = " " + re.sub(r"\s+", " ", prompt or "").strip() + " "
    found = {"city": None, "target": None, "min_reviews": None,
             "min_rating": None, "terms": [], "raw": (prompt or "").strip()}
    if not found["raw"]:
        return found

    # --- עיר ---
    lowered = text
    for key, names in PROMPT_CITIES.items():
        for name in sorted(names, key=len, reverse=True):
            if name in lowered:
                found["city"] = key
                text = text.replace(name, " ")
                break
        if found["city"]:
            break

    # --- מספרים, לפי המילה שלידם ---
    def take(words, cast, store):
        """
        קושר מספר למילה שלידו. קודם הצורה המפורשת ("דירוג 4.5") ורק אחריה
        המספר שלפני המילה ("3 ביקורות") -- ושם אסור שיהיה פסיק או מספר
        אחר בדרך, אחרת "20 נמענים, דירוג 4.5" היה קורא 20 כדירוג.
        """
        nonlocal text
        for word in words:
            for pattern in (rf"{word}\s*(?:של\s*)?[:־–-]?\s*(\d+(?:[.,]\d+)?)",
                            rf"(\d+(?:[.,]\d+)?)\s*[^\d,.]{{0,12}}?{word}"):
                match = re.search(pattern, text)
                if match:
                    value = cast(match.group(1))
                    if value is not None:
                        found[store] = value
                        text = text[:match.start()] + " " + text[match.end():]
                        return

    take(_RATING_WORDS, _to_float, "min_rating")
    take(_REVIEW_WORDS, lambda v: int(float(v.replace(",", "."))), "min_reviews")
    take(_TARGET_WORDS, lambda v: int(float(v.replace(",", "."))), "target")

    # דירוג יכול להיכתב כמספר עשרוני לבדו ("4.5"), וכמות כמספר שלם שנשאר
    if found["min_rating"] is None:
        match = re.search(r"(\d+[.,]\d+)", text)
        if match:
            found["min_rating"] = _to_float(match.group(1))
            text = text[:match.start()] + " " + text[match.end():]
    if found["target"] is None:
        match = re.search(r"\b(\d{1,3})\b", text)
        if match:
            found["target"] = int(match.group(1))
            text = text[:match.start()] + " " + text[match.end():]

    # --- מה שנשאר הוא התחום ---
    # מילות המפתח עצמן ("ביקורות", "דירוג", "נמענים") אינן חלק ממקצוע, גם
    # כשלא נצמד להן מספר -- אחרת "עורכי דין חוזים שיש להם ביקורות" הופך
    # למונח חיפוש שכולל את המילה ביקורות.
    for word in sorted(set(_PROMPT_NOISE) | set(_REVIEW_WORDS) |
                       set(_RATING_WORDS) | set(_TARGET_WORDS),
                       key=len, reverse=True):
        # ו' החיבור נדבקת למילה ("ומבוססים"), ולכן היא חלק מהתבנית
        text = re.sub(rf"(?<![א-ת])ו?{re.escape(word)}(?![א-ת])", " ", text)
    terms = []
    for term in split_query(re.sub(r"[ \t]{2,}", " ", text)):
        words = term.split()
        if len(words) > MAX_TERM_WORDS:
            term = " ".join(words[:MAX_TERM_WORDS])
        if term and term not in terms:
            terms.append(term)
    found["terms"] = terms
    return found


def describe_prompt(parsed: dict, cfg=None) -> str:
    """תיאור קריא של מה שהובן מהפרומפט, להצגה לפני שמריצים."""
    from data.neighborhoods import CITIES as CITY_MAP  # noqa: F401
    city_names = {k: v[0] for k, v in PROMPT_CITIES.items()}
    parts = []
    if parsed["terms"]:
        parts.append(" · ".join(parsed["terms"]))
    parts.append(city_names.get(parsed["city"] or "jerusalem", "ירושלים"))
    if parsed["target"]:
        parts.append(f"{parsed['target']} נמענים")
    if parsed["min_reviews"] is not None:
        parts.append(f"לפחות {parsed['min_reviews']} ביקורות")
    if parsed["min_rating"] is not None:
        parts.append(f"דירוג {parsed['min_rating']:g}+")
    return " · ".join(parts)


def scan_by_query(cfg: Config, storage: Storage, query: str,
                  city: str = "jerusalem", target_emails: int = 50,
                  campaign: str = "agent",
                  min_reviews: int | None = None,
                  min_rating: float | None = None) -> dict:
    """
    סורק לפי תחום שהוזן כטקסט חופשי ("יועצים עסקיים", "מאמן עסקי").

    למה בנפרד מהסריקה הרגילה: ל-Google יש טקסונומיה סגורה של סוגי מקומות,
    ותחומים כמו ייעוץ עסקי או אימון פשוט אינם בה. חיפוש הטקסט מגיע לתחומים
    האלה, במחיר של תוצאות פחות אחידות — ולכן הסינון כאן מקל: עסק פעיל, לא
    מוסד ולא רשת, ובעל ביקורות חיוביות לפי אותם תנאי סף.

    השדה יכול להכיל כמה תחומים מופרדים בפסיקים; כל אחד נסרק בנפרד
    (split_query), והעצירה היא כשמגיעים ליעד המיילים — לא בסוף הרשימה.

    זו הריצה הרציפה, לשימוש מהטרמינל. באפליקציה משתמשים ב-scan_chunk.
    """
    # parse_prompt ולא split_query: השדה הוא משפט חופשי, ובלי הפירוק
    # נשלחים לגוגל גם "תחפש", "תביאי 30" ושם העיר כאילו היו שמות מקצוע.
    parsed = parse_prompt(query)
    terms = parsed["terms"]
    if not terms:
        raise ValueError("צריך להזין תחום לחיפוש")
    if min_reviews is None:
        min_reviews = parsed["min_reviews"]
    if min_rating is None:
        min_rating = parsed["min_rating"]

    counters = new_counters()
    cursor = (0, 0, 0)
    seen: set = set()          # עסקים שכבר נספרו בהרצה הזאת
    while True:
        result = scan_chunk(cfg, storage, terms=terms, city=city,
                            target_emails=target_emails, campaign=campaign,
                            min_reviews=min_reviews, min_rating=min_rating,
                            cursor=cursor, counters=counters,
                            budget_seconds=None, seen=seen)
        counters = result["counters"]
        cursor = result["cursor"]
        if result["done"]:
            logger.info("סיכום: %s", counters)
            return counters


def scan_chunk(cfg: Config, storage: Storage, *, terms: list[str], city: str,
               target_emails: int, campaign: str,
               min_reviews: int | None, min_rating: float | None,
               cursor: tuple[int, int, int], counters: dict,
               budget_seconds: float | None = 45.0,
               run_id: str = "", seen: set | None = None) -> dict:
    """
    מריץ פיסת סריקה בתוך תקציב זמן, וחוזר עם סמן שממנו ממשיכים.

    למה במנות: סריקה מלאה נמשכת עשר דקות ויותר, ואין סביבת ריצה שמרשה
    בקשת HTTP כזאת — Vercel קוטע ב-5 דקות, ו-Render החינמי נרדם באמצע.
    כאן כל קריאה עושה כמה עשרות שניות של עבודה, שומרת מה שנמצא, ומחזירה
    את מיקומה. הקריאה הבאה ממשיכה בדיוק משם, ולכן הפסקה באמצע — סגירת
    לשונית, פריסה מחדש, נפילה — לא מאבדת דבר.

    הסמן הוא (שכונה, תחום, עסק). על חידוש מריצים שוב את אותו חיפוש
    ומדלגים לעסק שבו עצרנו; מה שכבר טופל שמור ב-DB ממילא.
    """
    from data.neighborhoods import neighborhoods_for

    reviews_floor = cfg.agent_min_reviews if min_reviews is None else min_reviews
    rating_floor = cfg.agent_min_rating if min_rating is None else min_rating
    neighborhoods = neighborhoods_for(city)
    client = make_client(cfg, include_reviews=(campaign == "agent"))
    family = family_of_query(" ".join(terms))
    nb_index, term_index, place_index = cursor
    deadline = None if budget_seconds is None else time.monotonic() + budget_seconds

    def out(done: bool, message: str = "") -> dict:
        total = max(len(neighborhoods) * len(terms), 1)
        step = min(nb_index * len(terms) + term_index, total)
        return {"cursor": (nb_index, term_index, place_index),
                "counters": counters, "done": done, "message": message,
                "progress": int(step * 100 / total)}

    while nb_index < len(neighborhoods):
        nb = neighborhoods[nb_index]
        while term_index < len(terms):
            term = terms[term_index]
            logger.info("מחפש \"%s\" ב%s (נאספו %d/%d)", term, nb.name,
                        counters["עם מייל"], target_emails)
            query = search_text_for(term, city)
            places = list(client.scan_text(query, nb.lat, nb.lng,
                                           cfg.search_radius_meters).values())
            if place_index == 0:          # סופרים פעם אחת, גם אם נחדש כאן
                counters["נסרקו"] += len(places)
                # בלי השורה הזאת "נאספו 0" נראה אותו דבר בין "גוגל לא
                # החזיר כלום" (מונח חיפוש גרוע) לבין "גוגל החזיר והכל
                # נפסל בסינון" -- שתי בעיות שונות לגמרי.
                if not places:
                    logger.info("  גוגל לא החזיר תוצאות למונח הזה כאן")
                else:
                    logger.info("  גוגל החזיר %d תוצאות", len(places))

            while place_index < len(places):
                _handle_place(cfg, storage, client, places[place_index], nb,
                              counters, reviews_floor, rating_floor, family,
                              run_id, city, seen)
                place_index += 1
                if counters["עם מייל"] >= target_emails:
                    return out(True, "הושג היעד")
                time.sleep(cfg.request_delay_seconds)
                if deadline and time.monotonic() > deadline:
                    return out(False, f"{term} ב{nb.name}")

            place_index = 0
            term_index += 1
            if deadline and time.monotonic() > deadline:
                return out(False, f"{term} ב{nb.name}")

        term_index = 0
        nb_index += 1

    return out(True, "נסרקו כל השכונות")


def enrich_missing_emails(cfg: Config, storage: Storage, limit: int = 50,
                          field: str = "") -> dict:
    """
    מנסה להשלים כתובות מייל ללידים שנסרקו בלי אתר. Google Places לא מחזיר
    מייל, ולידים בלי אתר נשארים תקועים — כאן מחפשים את אתר המשרד ברשת
    (Custom Search אם מוגדר, אחרת DuckDuckGo) ומחלצים ממנו מייל.

    field — להעשיר רק בעלי מקצוע מהתחום הזה. המאגר מצטבר ומכיל כמה
    מקצועות, ואין טעם לבזבז חיפושים על מי שלא נשלח אליו ממילא.
    """
    from egud_bot.jobscan import (_find_company_website, _clean_company_name,
                                  SearchQuotaError, SearchKeyError)
    from data.neighborhoods import city_of

    summary = {"נבדקו": 0, "נמצא אתר": 0, "נמצא מייל": 0}
    family = family_of_query(field) if field else ""
    if field and not family:
        logger.warning("התחום %r אינו מזוהה — לא מסננים לפיו.", field)

    # הסינון לפי תחום נעשה כאן ולא ב-SQL, ולכן מושכים מאגר גדול יותר:
    # אחרת limit=50 על מאגר מעורב היה מחזיר 50 שורות שרק 5 מהן מהתחום.
    leads = storage.leads_without_email(limit * 10 if family else limit)

    if family:
        before = len(leads)
        leads = [l for l in leads
                 if matches_query(BusinessLead.from_row(l), family)]
        skipped = before - len(leads)
        if skipped:
            logger.info("דילגתי על %d לידים שאינם מהתחום %r.", skipped, field)
            summary["לא מהתחום"] = skipped
        leads = leads[:limit]

    if not leads:
        logger.info("אין לידים ללא מייל להעשרה.")
        return summary

    # מפתח פסול מתגלה בליד הראשון. מאפסים אותו כדי שכל השאר ילכו ישר
    # ל-DuckDuckGo, במקום 77 בקשות כושלות עם אותה הודעה בדיוק.
    search_key = cfg.google_search_key

    for i, lead in enumerate(leads, 1):
        name = lead["name"]
        city = city_of(lead["neighborhood"] or "")
        # השם ב-Google Places עמוס מילות מפתח ולא ניתן לחיפוש כמו שהוא
        query = f"{_clean_company_name(name)} {city}".strip()
        logger.info("[%d/%d] %s → מחפש %r", i, len(leads), name, query)
        try:
            site = _find_company_website(query, cfg.request_delay_seconds,
                                         search_key, cfg.google_search_cx)
        except SearchQuotaError as exc:
            # אין טעם להמשיך: כל הבקשות הבאות ייכשלו באותה סיבה
            logger.error("מכסת החיפוש היומית של Google נגמרה — עוצרים כאן.")
            logger.error("  %s", exc)
            logger.error("  מה שנמצא עד כה נשמר. אפשר להמשיך מחר, או להסיר את "
                         "GOOGLE_SEARCH_KEY מ-.env כדי לעבור לחיפוש החינמי.")
            summary["נעצר"] = "מכסת החיפוש נגמרה"
            break
        except SearchKeyError as exc:
            logger.warning("מפתח החיפוש של Google אינו תקין: %s", exc)
            logger.warning("  ממשיכים עם DuckDuckGo. כדי להשתיק את ההודעה, "
                           "הסירי את GOOGLE_SEARCH_KEY מ-.env או החליפי אותו.")
            summary["מפתח פסול"] = "עברנו ל-DuckDuckGo"
            search_key = ""
            site = _find_company_website(query, cfg.request_delay_seconds,
                                         "", "")
        summary["נבדקו"] = i
        if not site:
            continue
        summary["נמצא אתר"] += 1
        logger.info("  אתר: %s", site)

        # מעבירים את השם הנקי כדי שאתר שאינו שייך לעסק ייפסל
        contact = find_contact(site, cfg.request_delay_seconds,
                               expect_name=_clean_company_name(name))
        email = contact["email"]
        if contact["specialty"]:
            storage.update_specialty(lead["place_id"], contact["specialty"])
            logger.info("  מהאתר: %s", contact["specialty"])
        if not email:
            # האתר עדיין שווה שמירה: ההרצה הבאה לא תחפש אותו מחדש,
            # ואפשר לפתוח אותו ידנית ולראות אם יש שם מייל
            storage.update_website(lead["place_id"], site)
            summary["אתר בלי מייל"] = summary.get("אתר בלי מייל", 0) + 1
            logger.info("  ✖ לא נמצא מייל באתר")
            continue
        if is_blocked_email(email):
            storage.update_website(lead["place_id"], site)
            logger.info("  ✖ המייל שנמצא חסום: %s", email)
            continue
        summary["נמצא מייל"] += 1
        storage.update_contact(lead["place_id"], email, site)
        logger.info("  ✔ %s → %s", name, email)

    logger.info("סיכום העשרה: %s", summary)
    return summary


def send_emails(cfg: Config, storage: Storage, dry_run: bool = False,
                campaign: str = "funding", skip_contacted: bool = False,
                limit: int | None = None, confirm=None, confirm_batch=None,
                variant: str = "", only=None, custom=None,
                field: str = "", city: str = "") -> dict:
    """
    שולח מייל ללידים חדשים שיש להם כתובת מייל (עד המכסה בהרצה).
    skip_contacted=True מדלג על כל מי שקיבל מייל באיזשהו קמפיין אחר
    (כדי לא לשלוח לאותו עסק שתי פניות שונות).
    limit — כמה מיילים לשלוח בהרצה הזאת (במקום MAX_EMAILS_PER_RUN).
    confirm — פונקציית אישור אינטראקטיבית. מקבלת את המייל המוכן ומחזירה
    "yes" / "no" / "quit". "quit" מבטל את ההרצה כולה ולא נשלח דבר, גם לא
    מיילים שאושרו קודם. אחרי סבב האישורים מוצגת רשימת הנמענים לאישור אחרון
    (confirm_batch), ורק אז נפתח חיבור ה-SMTP ונשלח.
    variant — "a" או "b" בבדיקת A/B: איזה נוסח לשלוח. כל נמען משויך לנוסח
    אחד בלבד, ומי שכבר קיבל נוסח לא ייכנס לקבוצה השנייה.
    only — אוסף place_id לשליחה. מסונן לפני חיתוך המכסה, כדי שבחירה מפורשת
    של נמענים לא תיחתך על ידי limit.
    custom — (נושא, גוף) של נוסח שנכתב באפליקציה. אם הועבר, הוא מחליף את
    התבניות המובנות.
    """
    # נוסח ב' הוא תבנית נפרדת; ברירת המחדל (ובנוסח א') היא תבנית הקמפיין
    template_campaign = f"{campaign}_offer" if variant == "b" else campaign
    # סינון לפי יומן שליחות קבוע: לעולם לא לשלוח שוב למי שכבר קיבל (גם אחרי מחיקת DB)
    sent_before = storage.already_sent_emails()
    if skip_contacted:
        sent_before = sent_before | storage.contacted_any_campaign()
    all_candidates = storage.leads_to_email(10 ** 9)
    # חסימת רשתות גדולות / ארגונים / דומיינים טכניים (הגנה גם אם נכנסו ל-DB בעבר)
    blocked = [l for l in all_candidates if is_blocked_email(l["email"])]
    remaining = [l for l in all_candidates if not is_blocked_email(l["email"])]

    # כתובת שגויה חוזרת כ-bounce, ושיעור bounce גבוה פוגע במוניטין השולח --
    # כלומר כתובת אחת שגויה מזיקה גם לכל השאר
    invalid = [l for l in remaining if not is_valid_email(l["email"])]
    remaining = [l for l in remaining if is_valid_email(l["email"])]

    # field: לשלוח רק לבעלי מקצוע מהתחום הזה. המאגר מצטבר ומכיל כמה
    # מקצועות, ונוסח שנכתב ליועצים עסקיים לא מתאים לעורכי דין.
    off_field = []
    if field:
        family = family_of_query(field)
        if family:
            off_field = [l for l in remaining
                         if not matches_query(BusinessLead.from_row(l), family)]
            remaining = [l for l in remaining
                         if matches_query(BusinessLead.from_row(l), family)]
        else:
            logger.warning("התחום %r אינו מזוהה — לא מסננים לפיו.", field)

    # city: לפסול מי שהשם או הכתובת מצהירים על עיר אחרת
    off_city = []
    if city:
        off_city = [l for l in remaining
                    if not in_requested_city(BusinessLead.from_row(l), city)]
        remaining = [l for l in remaining
                     if in_requested_city(BusinessLead.from_row(l), city)]
    # קמפיין מענק: לדלג על עסקים זעירים (gmail ובלי בע"מ) — רק חברות מבוססות
    small = []
    if campaign == "grant":
        small = [l for l in remaining if not looks_established(l["name"], l["email"])]
        remaining = [l for l in remaining if looks_established(l["name"], l["email"])]
    skipped = [l for l in remaining if (l["email"] or "").lower() in sent_before]
    if only is not None:            # בחירה מפורשת — לפני חיתוך המכסה
        only = set(only)
        remaining = [l for l in remaining if l["place_id"] in only]
    max_this_run = limit if limit else cfg.max_emails_per_run
    leads = [l for l in remaining
             if (l["email"] or "").lower() not in sent_before][:max_this_run]

    summary = {"candidates": len(leads), "sent": 0, "failed": 0,
               "skipped_already_sent": len(skipped),
               "skipped_blocked": len(blocked)}
    for label, group in (("דולגו: כתובת לא תקינה", invalid),
                         ("דולגו: לא מהתחום", off_field),
                         ("דולגו: עיר אחרת", off_city)):
        if group:
            summary[label] = len(group)
            for lead in group[:5]:
                logger.info("  %s — %s <%s>", label, lead["name"], lead["email"])
    if small:
        summary["skipped_small"] = len(small)
        logger.info("דילוג על %d עסקים זעירים (מענק: רק חברות מבוססות).", len(small))
    if blocked:
        logger.info("דילוג על %d כתובות חסומות (רשת גדולה / ארגון / דומיין טכני).",
                    len(blocked))
    if skipped:
        logger.info("דילוג על %d כתובות שכבר קיבלו מייל בעבר.", len(skipped))

    if not leads:
        logger.info("אין לידים חדשים לשליחה (כולם כבר קיבלו או שאין מיילים).")
        return summary

    # אישור אנושי לפני שליחה: מציגים כל מייל ושואלים
    if confirm and not dry_run:
        approved = []
        for index, lead in enumerate(leads, 1):
            ctx = build_ctx(cfg, campaign, lead)
            subject, _html, text = _render(template_campaign, ctx, custom)
            answer = confirm(lead, subject, text, index, len(leads), ctx.get("rec"))
            if answer == "quit":
                # ביטול מלא: גם מה שאושר קודם לא נשלח
                summary.update(candidates=0, declined=len(leads), cancelled=True)
                logger.info("ההרצה בוטלה — לא נשלח אף מייל.")
                return summary
            if answer == "yes":
                approved.append(lead)
        summary["declined"] = len(leads) - len(approved)
        leads = approved
        summary["candidates"] = len(leads)
        if not leads:
            logger.info("לא אושר אף מייל — לא נשלח דבר.")
            return summary
        # אישור אחרון על הרשימה כולה, רגע לפני שנפתח חיבור SMTP
        if confirm_batch and not confirm_batch(leads):
            summary.update(candidates=0, declined=summary["declined"] + len(leads),
                           cancelled=True)
            logger.info("השליחה בוטלה בשלב האישור הסופי — לא נשלח אף מייל.")
            return summary

    if dry_run:
        for lead in leads:
            logger.info("[DRY-RUN] היה נשלח מייל אל %s <%s>", lead["name"], lead["email"])
        summary["would_send"] = len(leads)
        summary["note"] = "תצוגה מקדימה בלבד — לא נשלח דבר! להרצה אמיתית: python main.py send"
        logger.info("זו תצוגה מקדימה (DRY-RUN) — לא נשלח אף מייל בפועל.")
        return summary

    # שולח לפי קמפיין (grant נשלח מהמייל האישי של מירי; אחרים מכתובת האיגוד)
    from_email, from_name, smtp_user, smtp_password = cfg.sender_for(campaign)
    with Mailer(
        host=cfg.smtp_host,
        port=cfg.smtp_port,
        user=smtp_user,
        password=smtp_password,
        from_email=from_email,
        from_name=from_name,         # שם השולח האישי, כדי שייראה כמו מייל מאדם
        reply_to=from_email,         # תשובות חוזרות לשולח עצמו
        use_ssl=cfg.smtp_use_ssl,
        logo_path="",                # מייל אישי, ללא לוגו
    ) as mailer:
        for lead in leads:
            subject, html, text = _render(
                template_campaign, build_ctx(cfg, campaign, lead), custom)
            # פיקסל מעקב פתיחות (רק אם הוגדרה כתובת ציבורית)
            track_id = ""
            if cfg.tracking_base_url:
                track_id = tracking.new_track_id()
                html = tracking.add_pixel(html, cfg.tracking_base_url, track_id)
            try:
                mailer.send(lead["email"], subject, html, text)
                if track_id:
                    storage.set_track_id(lead["place_id"], track_id)
                storage.mark_emailed(lead["place_id"], success=True)
                if variant:
                    storage.set_variant(lead["place_id"], variant)
                storage.record_sent(lead["email"])   # יומן קבוע נגד שליחה כפולה
                summary["sent"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("שליחה אל %s נכשלה: %s", lead["email"], exc)
                storage.mark_emailed(lead["place_id"], success=False, error=str(exc))
                summary["failed"] += 1
            time.sleep(cfg.request_delay_seconds)

    logger.info("סיכום שליחה: %s", summary)
    return summary
