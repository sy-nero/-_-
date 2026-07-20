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
) -> dict:
    """
    סורק את השכונות, מסנן, מאתר מיילים ושומר לידים חדשים ב-DB.
    מחזיר סיכום מספרי.
    """
    neighborhoods = neighborhoods or HAREDI_NEIGHBORHOODS
    client = make_client(cfg)

    summary = {"scanned": 0, "passed": 0, "new": 0, "with_email": 0, "no_email": 0}

    for nb in neighborhoods:
        logger.info("סורק שכונה: %s", nb.name)
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
            else:
                summary["no_email"] += 1
                storage.upsert_lead(lead, None, status="no_email")

            time.sleep(cfg.request_delay_seconds)

    logger.info("סיכום סריקה: %s", summary)
    return summary


def send_emails(cfg: Config, storage: Storage, dry_run: bool = False) -> dict:
    """
    שולח מייל ללידים חדשים שיש להם כתובת מייל (עד המכסה בהרצה).
    """
    leads = storage.leads_to_email(cfg.max_emails_per_run)
    summary = {"candidates": len(leads), "sent": 0, "failed": 0}

    if not leads:
        logger.info("אין לידים לשליחה.")
        return summary

    if dry_run:
        for lead in leads:
            logger.info("[DRY-RUN] היה נשלח מייל אל %s <%s>", lead["name"], lead["email"])
        summary["sent"] = len(leads)
        return summary

    with Mailer(
        host=cfg.smtp_host,
        port=cfg.smtp_port,
        user=cfg.smtp_user,
        password=cfg.smtp_password,
        from_email=cfg.from_email,
        from_name=cfg.from_name,
        reply_to=cfg.reply_to,
        use_ssl=cfg.smtp_use_ssl,
    ) as mailer:
        for lead in leads:
            subject = templates.build_subject(cfg.association_name, lead["name"])
            html = templates.build_html(
                lead["name"], cfg.association_name,
                cfg.landing_page_url, cfg.unsubscribe_url, lead["place_id"],
            )
            text = templates.build_text(
                lead["name"], cfg.association_name,
                cfg.landing_page_url, cfg.unsubscribe_url, lead["place_id"],
            )
            try:
                mailer.send(lead["email"], subject, html, text)
                storage.mark_emailed(lead["place_id"], success=True)
                summary["sent"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("שליחה אל %s נכשלה: %s", lead["email"], exc)
                storage.mark_emailed(lead["place_id"], success=False, error=str(exc))
                summary["failed"] += 1
            time.sleep(cfg.request_delay_seconds)

    logger.info("סיכום שליחה: %s", summary)
    return summary
