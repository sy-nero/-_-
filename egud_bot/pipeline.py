"""
תזמור התהליך המלא: סריקה -> סינון -> איתור מייל -> שמירה -> שליחה.
"""
import json
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
                              passes_filters_agent,
                              is_blocked_email, looks_established)
from egud_bot.email_finder import find_email
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
        term = _NOISE_RE.sub("", part.strip().strip(_EDGE)).strip(_EDGE)
        if len(term) >= 2 and term not in terms:
            terms.append(term)
    return terms


def scan_by_query(cfg: Config, storage: Storage, query: str,
                  city: str = "jerusalem", target_emails: int = 50,
                  campaign: str = "agent") -> dict:
    """
    סורק לפי תחום שהוזן כטקסט חופשי ("יועצים עסקיים", "מאמן עסקי").

    למה בנפרד מהסריקה הרגילה: ל-Google יש טקסונומיה סגורה של סוגי מקומות,
    ותחומים כמו ייעוץ עסקי או אימון פשוט אינם בה. חיפוש הטקסט מגיע לתחומים
    האלה, במחיר של תוצאות פחות אחידות — ולכן הסינון כאן מקל: עסק פעיל, לא
    מוסד ולא רשת, ובעל ביקורות חיוביות לפי אותם תנאי סף.

    השדה יכול להכיל כמה תחומים מופרדים בפסיקים; כל אחד נסרק בנפרד
    (split_query), והעצירה היא כשמגיעים ליעד המיילים — לא בסוף הרשימה.
    """
    from data.neighborhoods import neighborhoods_for

    terms = split_query(query)
    if not terms:
        raise ValueError("צריך להזין תחום לחיפוש")

    client = make_client(cfg, include_reviews=(campaign == "agent"))
    neighborhoods = neighborhoods_for(city)
    summary = {"נסרקו": 0, "עברו סינון": 0, "חדשים": 0,
               "עם מייל": 0, "בלי מייל": 0, "עם המלצה": 0}
    logger.info("תחומים לחיפוש: %s", " · ".join(terms))

    for nb in neighborhoods:
        for term in terms:
            logger.info("מחפש \"%s\" ב%s (נאספו %d/%d)", term, nb.name,
                        summary["עם מייל"], target_emails)
            places = client.scan_text(term, nb.lat, nb.lng, cfg.search_radius_meters)
            summary["נסרקו"] += len(places)

            for place in places.values():
                lead = BusinessLead.from_place(place, neighborhood=nb.name)
                if not lead.place_id:
                    continue
                if not passes_filters_agent(lead, cfg.agent_min_reviews,
                                            cfg.require_operational,
                                            cfg.agent_min_rating,
                                            any_type=True):
                    continue
                summary["עברו סינון"] += 1
                if storage.exists(lead.place_id):
                    continue
                summary["חדשים"] += 1

                client.enrich_contact(lead)
                rec = recommendations.collect(lead, cfg, cfg.request_delay_seconds)
                lead.rec = rec.as_dict() if rec else {}
                if rec:
                    summary["עם המלצה"] += 1

                email = (find_email(lead.website, cfg.request_delay_seconds)
                         if lead.website else None)
                if email and is_blocked_email(email):
                    email = None
                if email:
                    summary["עם מייל"] += 1
                    storage.upsert_lead(lead, email, status="found")
                    logger.info("  \u2714 %s \u2192 %s", lead.name, email)
                else:
                    summary["בלי מייל"] += 1
                    storage.upsert_lead(lead, None, status="no_email")

                time.sleep(cfg.request_delay_seconds)
                if summary["עם מייל"] >= target_emails:
                    logger.info("הושג היעד — עוצר")
                    return summary

    logger.info("סיכום: %s", summary)
    return summary


def enrich_missing_emails(cfg: Config, storage: Storage, limit: int = 50) -> dict:
    """
    מנסה להשלים כתובות מייל ללידים שנסרקו בלי אתר. Google Places לא מחזיר
    מייל, ולידים בלי אתר נשארים תקועים — כאן מחפשים את אתר המשרד ברשת
    (Custom Search אם מוגדר, אחרת DuckDuckGo) ומחלצים ממנו מייל.
    """
    from egud_bot.jobscan import _find_company_website
    from data.neighborhoods import city_of

    leads = storage.leads_without_email(limit)
    summary = {"נבדקו": len(leads), "נמצא אתר": 0, "נמצא מייל": 0}
    if not leads:
        logger.info("אין לידים ללא מייל להעשרה.")
        return summary

    for i, lead in enumerate(leads, 1):
        name = lead["name"]
        city = city_of(lead["neighborhood"] or "")
        query = f"{name} {city}".strip()
        logger.info("[%d/%d] מחפש אתר עבור %s", i, len(leads), name)
        site = _find_company_website(query, cfg.request_delay_seconds,
                                     cfg.google_search_key, cfg.google_search_cx)
        if not site:
            continue
        summary["נמצא אתר"] += 1

        email = find_email(site, cfg.request_delay_seconds)
        if not email or is_blocked_email(email):
            continue
        summary["נמצא מייל"] += 1
        storage.update_contact(lead["place_id"], email, site)
        logger.info("  ✔ %s → %s", name, email)

    logger.info("סיכום העשרה: %s", summary)
    return summary


def send_emails(cfg: Config, storage: Storage, dry_run: bool = False,
                campaign: str = "funding", skip_contacted: bool = False,
                limit: int | None = None, confirm=None, confirm_batch=None,
                variant: str = "", only=None, custom=None) -> dict:
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
