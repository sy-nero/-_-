"""
תזמור התהליך המלא: סריקה -> סינון -> איתור מייל -> שמירה -> שליחה.
"""
import time
import logging

from config import Config
from data.neighborhoods import HAREDI_NEIGHBORHOODS, Neighborhood
from egud_bot.places import make_client
from egud_bot.filters import BusinessLead, passes_filters
from egud_bot.email_finder import find_email
from egud_bot.storage import Storage
from egud_bot.mailer import Mailer
from egud_bot import templates

logger = logging.getLogger(__name__)


def scan(
    cfg: Config,
    storage: Storage,
    neighborhoods: list[Neighborhood] | None = None,
    target_emails: int | None = None,
) -> dict:
    """
    סורק את השכונות, מסנן, מאתר מיילים ושומר לידים חדשים ב-DB.
    עוצר מוקדם ברגע שנאספו `target_emails` מיילים חדשים (ברירת מחדל: cfg.target_emails).
    מחזיר סיכום מספרי.
    """
    neighborhoods = neighborhoods or HAREDI_NEIGHBORHOODS
    target = cfg.target_emails if target_emails is None else target_emails
    client = make_client(cfg)

    summary = {"scanned": 0, "passed": 0, "new": 0, "with_email": 0, "no_email": 0}

    for nb in neighborhoods:
        logger.info("סורק שכונה: %s (מיילים שנאספו: %d/%d)",
                    nb.name, summary["with_email"], target)
        places = client.scan_point(nb.lat, nb.lng, cfg.search_radius_meters)
        summary["scanned"] += len(places)

        for place in places.values():
            lead = BusinessLead.from_place(place, neighborhood=nb.name)
            if not lead.place_id:
                continue
            if not passes_filters(lead, cfg.max_review_count, cfg.require_operational):
                continue
            summary["passed"] += 1

            if storage.exists(lead.place_id):
                continue  # כבר טופל בעבר
            summary["new"] += 1

            # העשרת אתר/טלפון (רלוונטי ל-legacy — קריאת Details רק ללידים שעברו סינון)
            client.enrich_contact(lead)

            email = find_email(lead.website, cfg.request_delay_seconds) if lead.website else None
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


def send_emails(cfg: Config, storage: Storage, dry_run: bool = False) -> dict:
    """
    שולח מייל ללידים חדשים שיש להם כתובת מייל (עד המכסה בהרצה).
    """
    # סינון לפי יומן שליחות קבוע: לעולם לא לשלוח שוב למי שכבר קיבל (גם אחרי מחיקת DB)
    sent_before = storage.already_sent_emails()
    all_candidates = storage.leads_to_email(10 ** 9)
    skipped = [l for l in all_candidates if (l["email"] or "").lower() in sent_before]
    leads = [l for l in all_candidates
             if (l["email"] or "").lower() not in sent_before][:cfg.max_emails_per_run]

    summary = {"candidates": len(leads), "sent": 0, "failed": 0,
               "skipped_already_sent": len(skipped)}
    if skipped:
        logger.info("דילוג על %d כתובות שכבר קיבלו מייל בעבר.", len(skipped))

    if not leads:
        logger.info("אין לידים חדשים לשליחה (כולם כבר קיבלו או שאין מיילים).")
        return summary

    if dry_run:
        for lead in leads:
            logger.info("[DRY-RUN] היה נשלח מייל אל %s <%s>", lead["name"], lead["email"])
        summary["would_send"] = len(leads)
        summary["note"] = "תצוגה מקדימה בלבד — לא נשלח דבר! להרצה אמיתית: python main.py send"
        logger.info("זו תצוגה מקדימה (DRY-RUN) — לא נשלח אף מייל בפועל.")
        return summary

    with Mailer(
        host=cfg.smtp_host,
        port=cfg.smtp_port,
        user=cfg.smtp_user,
        password=cfg.smtp_password,
        from_email=cfg.from_email,
        from_name=cfg.sender_name,   # שם השולח האישי, כדי שייראה כמו מייל מאדם
        reply_to=cfg.reply_to,
        use_ssl=cfg.smtp_use_ssl,
        logo_path="",                # מייל אישי, ללא לוגו
    ) as mailer:
        for lead in leads:
            field = templates.field_noun(lead["primary_type"])
            nb = lead["neighborhood"] or ""
            subject = templates.build_subject(cfg.association_name, lead["name"])
            html = templates.build_html(
                lead["name"], cfg.association_name,
                cfg.sender_name, cfg.sender_title, field=field, neighborhood=nb,
            )
            text = templates.build_text(
                lead["name"], cfg.association_name,
                cfg.sender_name, cfg.sender_title, field=field, neighborhood=nb,
            )
            try:
                mailer.send(lead["email"], subject, html, text)
                storage.mark_emailed(lead["place_id"], success=True)
                storage.record_sent(lead["email"])   # יומן קבוע נגד שליחה כפולה
                summary["sent"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("שליחה אל %s נכשלה: %s", lead["email"], exc)
                storage.mark_emailed(lead["place_id"], success=False, error=str(exc))
                summary["failed"] += 1
            time.sleep(cfg.request_delay_seconds)

    logger.info("סיכום שליחה: %s", summary)
    return summary
