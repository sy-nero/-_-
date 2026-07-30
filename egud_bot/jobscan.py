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

# קטגוריות דרושים רלוונטיות לקמעונאות
DRUSHIM_CATEGORIES = ["cat33", "cat17", "cat32"]  # קמעונאות, מכירות, אופנה
DRUSHIM_CAT_URL = "https://www.drushim.co.il/jobs/{cat}/?page={page}"
DRUSHIM_SEARCH = "https://www.drushim.co.il/jobs/{q}/"  # לשימוש כלי האבחון


def _extract_company(card_text: str) -> str | None:
    """שם החברה הוא השורה השנייה בכרטיס. מדלג על משרות חסויות/אנונימיות."""
    lines = [l.strip() for l in (card_text or "").split("\n") if l.strip()]
    if len(lines) < 2:
        return None
    comp = lines[1]
    if ("חסוי" in comp or comp.startswith("-") or comp.startswith("|")
            or len(comp) < 2 or len(comp) > 50 or "|" in comp):
        return None
    return comp

# דומיינים של רשתות חברתיות/דרושים שאינם "אתר החברה"
_SKIP_DOMAINS = (
    "facebook.", "instagram.", "linkedin.", "youtube.", "drushim.",
    "alljobs.", "jobmaster.", "indeed.", "glassdoor.", "google.",
    "wikipedia.", "gov.il", "twitter.", "tiktok.", "waze.",
)

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}


def _first_good_host(urls) -> str | None:
    for href in urls:
        host = (urlparse(href).netloc or "").lower()
        if host and not any(s in host for s in _SKIP_DOMAINS):
            return f"https://{host}"
    return None


def _search_google(company: str, key: str, cx: str) -> str | None:
    """Google Custom Search API — אמין, לא נחסם."""
    try:
        r = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": key, "cx": cx, "q": f"{company} אתר רשמי", "num": 5},
            timeout=20,
        )
        items = r.json().get("items", []) if r.status_code == 200 else []
    except (requests.RequestException, ValueError):
        return None
    return _first_good_host(it.get("link", "") for it in items)


def _search_ddg(company: str) -> str | None:
    """DuckDuckGo (חינמי, אך נחסם אחרי מספר חיפושים) — גיבוי בלבד."""
    time.sleep(4.0)
    try:
        r = requests.get("https://html.duckduckgo.com/html/",
                         params={"q": f"{company} אתר רשמי"}, headers=_UA, timeout=20)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    urls = []
    for a in soup.select("a.result__a"):
        href = a.get("href") or ""
        if "uddg=" in href:
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [""])[0])
        urls.append(href)
    return _first_good_host(urls)


def _find_company_website(company: str, delay: float = 1.0,
                          search_key: str = "", search_cx: str = "") -> str | None:
    """מחפש את אתר החברה — דרך Google Custom Search אם מוגדר, אחרת DuckDuckGo."""
    if search_key and search_cx:
        return _search_google(company, search_key, search_cx)
    return _search_ddg(company)


def _scrape_drushim_companies(max_companies: int, delay: float, max_pages: int = 5) -> list[str]:
    """מרנדר קטגוריות קמעונאות בדרושים ומחלץ שמות חברות (שורה 2 בכל כרטיס)."""
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
        for cat in DRUSHIM_CATEGORIES:
            for pg in range(1, max_pages + 1):
                if len(companies) >= max_companies:
                    break
                url = DRUSHIM_CAT_URL.format(cat=cat, page=pg)
                logger.info("דרושים: %s עמוד %d (חברות עד כה: %d)", cat, pg, len(companies))
                try:
                    page.goto(url, timeout=45000, wait_until="domcontentloaded")
                    page.wait_for_timeout(5000)
                    for _ in range(3):
                        page.mouse.wheel(0, 5000)
                        page.wait_for_timeout(1200)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("דרושים נכשל עבור %s עמוד %d: %s", cat, pg, str(exc)[:100])
                    continue

                texts = page.eval_on_selector_all(
                    "div.job-item-main", "els => els.map(e => e.innerText)")
                if not texts:
                    break  # אין יותר משרות בקטגוריה
                for t in texts:
                    comp = _extract_company(t)
                    if comp and comp not in seen:
                        seen.add(comp)
                        companies.append(comp)
                        if len(companies) >= max_companies:
                            break
        browser.close()

    logger.info("נמצאו %d שמות חברה בדרושים", len(companies))
    return companies


def debug_drushim(url: str = "https://www.drushim.co.il/jobs/cat32/") -> None:
    """כלי אבחון: טוען עמוד קטגוריית דרושים, מדפיס מבנה, ושומר HTML."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright לא מותקן."); return

    with sync_playwright() as p:
        page = p.chromium.launch(args=["--no-sandbox"]).new_page()
        page.goto(url, timeout=60000, wait_until="domcontentloaded")
        page.wait_for_timeout(9000)
        for _ in range(4):
            page.mouse.wheel(0, 4000); page.wait_for_timeout(1500)

        # מיפוי כל הקטגוריות (לזיהוי קטגוריות קמעונאות)
        print("כל הקטגוריות (cat / כותרת):")
        cats = page.eval_on_selector_all(
            "a[href*='/jobs/cat']",
            "els => [...new Set(els.map(e => (e.getAttribute('href')||'')+' :: '+(e.getAttribute('title')||e.innerText||'').trim()))]")
        for c in cats[:60]:
            print("   ", c[:70])

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

        # דוגמאות קישורי משרה
        print("\n5 קישורי משרה לדוגמה:")
        for a in page.query_selector_all("a[href*='/job']")[:5]:
            print("   ", (a.get_attribute("href") or "")[:80])

        # טקסט של אלמנטי חברה
        print("\nטקסט של אלמנטי [class*='company'] (5 ראשונים):")
        for el in page.query_selector_all("[class*='company']")[:5]:
            t = (el.inner_text() or "").strip().replace("\n", " ")
            print("   >>", t[:80] if t else "(ריק)")

        # כרטיסי משרה אמיתיים (href בפורמט /job/מספר)
        cards = page.evaluate(r"""() => {
          const links = [...document.querySelectorAll("a[href*='/job/']")]
              .filter(x => /\/job\/\d+/.test(x.getAttribute('href')||''));
          const seen = new Set(); const out = [];
          for (const a of links) {
            let n = a; for (let i=0;i<6 && n.parentElement;i++) n = n.parentElement;
            if (seen.has(n)) continue; seen.add(n);
            out.push({text: n.innerText, html: n.outerHTML});
            if (out.length >= 3) break;
          }
          return out;
        }""")
        print(f"\nנמצאו {len(cards)} כרטיסי משרה אמיתיים. טקסט של 3 הראשונים:")
        for i, c in enumerate(cards):
            lines = [l.strip() for l in (c["text"] or "").split("\n") if l.strip()]
            print(f"  --- כרטיס {i+1} ---")
            for l in lines[:8]:
                print("     ", l[:70])
        if cards:
            print("\nHTML של כרטיס משרה ראשון (לזיהוי הסלקטור של שם החברה):")
            print(re.sub(r"\s+", " ", cards[0]["html"])[:2200])
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

    companies = _scrape_drushim_companies(max_companies=target * 4, delay=delay)
    summary["companies"] = len(companies)
    if not companies:
        logger.warning("לא נמצאו שמות חברה בדרושים (ייתכן שהמבנה השתנה או שאין Playwright).")
        return summary

    # סוכנויות השמה/כוח אדם — לא המעסיק האמיתי, מדלגים
    staffing = ("השמה", "השמות", "כוח אדם", "כ״א", "מנפאואר", "manpower",
                "רזומה", "staffing", "recruit", "job", "jobs", "אדם", "פלייסמנט")
    for company in companies:
        low = company.lower()
        if is_excluded_by_name(company) or any(k in low for k in staffing):
            continue
        pid = f"job_{company}"
        if storage.exists(pid):
            continue
        summary["new"] += 1

        website = _find_company_website(
            company, delay, cfg.google_search_key, cfg.google_search_cx)
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
