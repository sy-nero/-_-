"""
מקור לקמפיין מ״א (משאבי אנוש): סריקת אתר הדרושים "דרושים" (drushim.co.il).

הזרימה שביקשת:
  1. נכנסים ל-drushim ומחפשים משרות בקטגוריות קמעונאות.
  2. מחלצים את שם החברה המפרסמת (מהמשרות שבהן הוא מפורסם).
  3. מחפשים באינטרנט את האתר של החברה (DuckDuckGo).
  4. מאתרים באתר את המייל, ושומרים ליד לשליחה.

דורש Playwright (דפדפן) כי drushim נטען ב-JavaScript וחוסם סקרייפינג רגיל:
  pip install playwright
  playwright install chromium

הערה: חלק מהמשרות מתפרסמות ללא שם חברה ("חברה מובילה"), ואותן אי אפשר
לזהות. כמו כן, כדאי לוודא שהשימוש תואם את תנאי השימוש של האתר.
"""
import re
import time
import logging
from urllib.parse import urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

from config import Config
from egud_bot.filters import BusinessLead, is_excluded_by_name
from egud_bot.email_finder import find_email
from egud_bot.storage import Storage

logger = logging.getLogger(__name__)

# קטגוריות קמעונאות בדרושים (אפשר לשנות/להוסיף מונחי חיפוש)
DEFAULT_QUERIES = [
    "מוכר", "מוכרת", "קופאי", "קופאית", "מכירות קמעונאות",
    "עובד חנות", "מנהל חנות", "סדרן", "אחסנאי",
]

DRUSHIM_SEARCH = "https://www.drushim.co.il/jobs/?q={q}"

# דומיינים של רשתות חברתיות/דרושים שאינם "אתר החברה"
_SKIP_DOMAINS = (
    "facebook.", "instagram.", "linkedin.", "youtube.", "drushim.",
    "alljobs.", "jobmaster.", "indeed.", "glassdoor.", "google.",
    "wikipedia.", "gov.il", "twitter.", "tiktok.", "waze.",
)

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}


def _find_company_website(company: str, delay: float = 1.0) -> str | None:
    """מחפש ב-DuckDuckGo את האתר הרשמי של החברה ומחזיר דומיין ראשון רלוונטי."""
    try:
        r = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": f"{company} אתר רשמי"}, headers=_UA, timeout=20,
        )
    except requests.RequestException:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.select("a.result__a"):
        href = a.get("href") or ""
        # DDG עוטף קישורים ב-/l/?uddg=<url>
        if "uddg=" in href:
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [""])[0])
        host = (urlparse(href).netloc or "").lower()
        if host and not any(s in host for s in _SKIP_DOMAINS):
            time.sleep(delay)
            return f"https://{host}"
    return None


def _scrape_drushim_companies(queries, max_companies: int, delay: float) -> list[str]:
    """מרנדר את drushim ומחלץ שמות חברות מהמשרות. מחזיר רשימת שמות ייחודיים."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("Playwright לא מותקן. הרץ: pip install playwright && playwright install chromium")
        return []

    companies: list[str] = []
    seen = set()
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page()
        for q in queries:
            if len(companies) >= max_companies:
                break
            url = DRUSHIM_SEARCH.format(q=q)
            logger.info("דרושים: מחפש '%s'", q)
            try:
                page.goto(url, timeout=45000, wait_until="domcontentloaded")
                page.wait_for_timeout(6000)
                # גלילה כדי לטעון עוד משרות
                for _ in range(3):
                    page.mouse.wheel(0, 4000)
                    page.wait_for_timeout(1500)
            except Exception as exc:  # noqa: BLE001
                logger.warning("דרושים נכשל עבור '%s': %s", q, str(exc)[:120])
                continue

            # חילוץ שמות חברה: drushim משתמש בקישורי /company/ וכן בשדות טקסט.
            names = page.eval_on_selector_all(
                "a[href*='/company'], [class*='company'], [class*='Company']",
                "els => els.map(e => e.innerText).filter(Boolean)",
            )
            for name in names:
                name = (name or "").strip()
                if name and name not in seen and 2 < len(name) < 60:
                    seen.add(name)
                    companies.append(name)
                    if len(companies) >= max_companies:
                        break
        browser.close()

    logger.info("נמצאו %d שמות חברה בדרושים", len(companies))
    return companies


def debug_drushim(query: str = "מוכר") -> None:
    """כלי אבחון: טוען דף דרושים, מדפיס מבנה, ושומר HTML — לכוונון הסלקטור."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright לא מותקן."); return

    with sync_playwright() as p:
        page = p.chromium.launch(args=["--no-sandbox"]).new_page()
        page.goto(DRUSHIM_SEARCH.format(q=query), timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(9000)
        for _ in range(3):
            page.mouse.wheel(0, 4000); page.wait_for_timeout(1500)

        html = page.content()
        with open("data/drushim_debug.html", "w", encoding="utf-8") as f:
            f.write(html)
        body = page.inner_text("body")

        print("=" * 60)
        print("TITLE:", page.title())
        print("URL  :", page.url)
        print("BODY_LEN:", len(body), "| HTML_LEN:", len(html))
        low = (body + html).lower()
        challenge = any(w in low for w in
                        ["cloudflare", "captcha", "אבטחה", "רובוט", "מאמת", "לא אנושי", "verify you are human"])
        print("נראה כמו מסך אימות/חסימה?:", challenge)
        print("BODY SNIPPET:", body[:300].replace("\n", " | "))

        # ספירת מחלקות נפוצות (לזהות כרטיסי משרה)
        classes = page.eval_on_selector_all(
            "[class]", "els => els.map(e => e.className).filter(c => typeof c === 'string')")
        from collections import Counter
        tokens = Counter()
        for c in classes:
            for t in c.split():
                tokens[t] += 1
        print("\n15 שמות מחלקה נפוצים (name: count):")
        for name, cnt in tokens.most_common(15):
            print(f"   {name}: {cnt}")

        # בדיקת סלקטורים אפשריים
        print("\nספירת סלקטורים:")
        for sel in ["a[href*='/company']", "a[href*='/job']", "[class*='company']",
                    "[class*='Company']", "[class*='card']", "[class*='job']",
                    "[data-testid]", "h2", "h3"]:
            try:
                n = len(page.query_selector_all(sel))
            except Exception:
                n = -1
            print(f"   {sel}: {n}")
        page.context.browser.close()
    print("\nנשמר: data/drushim_debug.html")


def scan_jobs(cfg: Config, storage: Storage, target_emails: int | None = None) -> dict:
    """
    סורק דרושים -> שם חברה -> אתר החברה -> מייל -> שמירה.
    עוצר כשנאספו target_emails מיילים.
    """
    target = cfg.target_emails if target_emails is None else target_emails
    delay = cfg.request_delay_seconds
    summary = {"companies": 0, "new": 0, "with_email": 0, "no_email": 0}

    companies = _scrape_drushim_companies(DEFAULT_QUERIES, max_companies=target * 4, delay=delay)
    summary["companies"] = len(companies)
    if not companies:
        logger.warning("לא נמצאו שמות חברה בדרושים (ייתכן שהמבנה השתנה או שאין Playwright).")
        return summary

    for company in companies:
        if is_excluded_by_name(company):
            continue
        pid = f"job_{company}"
        if storage.exists(pid):
            continue
        summary["new"] += 1

        website = _find_company_website(company, delay)
        email = find_email(website, delay) if website else None
        lead = BusinessLead(
            place_id=pid, name=company, address="", lat=0.0, lng=0.0, phone="",
            website=website or "", rating=None, review_count=0,
            business_status="OPERATIONAL", primary_type="", neighborhood="", types=[],
        )
        if email:
            summary["with_email"] += 1
            storage.upsert_lead(lead, email, status="found")
            logger.info("  ✔ מייל נמצא (%d/%d): %s → %s",
                        summary["with_email"], target, company, email)
        else:
            summary["no_email"] += 1
            storage.upsert_lead(lead, None, status="no_email")
        time.sleep(delay)
        if summary["with_email"] >= target:
            break

    logger.info("סיכום סריקת דרושים: %s", summary)
    return summary


def import_csv(storage: Storage, path: str, email_col: str = "email",
               name_col: str = "name") -> int:
    """מייבא רשימת עסקים מקובץ CSV (עמודות name,email) ל-DB של הקמפיין."""
    import csv
    added = 0
    with open(path, encoding="utf-8-sig") as f:
        for i, row in enumerate(csv.DictReader(f)):
            email = (row.get(email_col) or "").strip()
            if not email:
                continue
            pid = f"csv_{i}_{email.lower()}"
            if storage.exists(pid):
                continue
            lead = BusinessLead(
                place_id=pid, name=(row.get(name_col) or email).strip(), address="",
                lat=0.0, lng=0.0, phone=(row.get("phone") or "").strip(), website="",
                rating=None, review_count=0, business_status="OPERATIONAL",
                primary_type="", neighborhood="", types=[],
            )
            storage.upsert_lead(lead, email, status="found")
            added += 1
    logger.info("יובאו %d עסקים מ-%s", added, path)
    return added
