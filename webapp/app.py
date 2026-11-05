#!/usr/bin/env python3
"""
אפליקציית ניהול הקמפיינים — הלוח שמחליף את הגיליון.

הרצה:
    python webapp/app.py
ואז גלישה אל http://localhost:5001

מה יש כאן:
  * לוח קמפיינים במבנה הגיליון (שורות = שדות, עמודות = קמפיינים).
  * עריכת כל קמפיין: פרטים / הערות / המלצות לשיפור לכל שורה.
  * שליחת מיילים מתוך האפליקציה, עם תצוגה מקדימה לפני כל שליחה.
  * מדידה אוטומטית: נשלחו, נפתחו (פיקסל), השיבו.
"""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io
import zipfile
from functools import wraps
from datetime import datetime

from flask import (Flask, request, render_template, redirect, jsonify,  # noqa: E402
                   url_for, Response, flash, session, send_file)

from config import config  # noqa: E402
from egud_bot import db, filters, pipeline, templates as mail_templates, tracking  # noqa: E402

logger = logging.getLogger(__name__)
from webapp.jobs import runner  # noqa: E402
from egud_bot.campaigns import (CampaignStore, TEXT_FIELDS, AUTO_FIELDS,  # noqa: E402
                                MANUAL_FIELDS, ALL_FIELDS)
from egud_bot.storage import Storage, REAL_CLICK  # noqa: E402
from egud_bot import senders as sender_box  # noqa: E402
from egud_bot import importer  # noqa: E402
from egud_bot.clients import ClientStore, TX_KINDS  # noqa: E402

app = Flask(__name__)
app.secret_key = config.flask_secret_key
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

# מסד הנתונים נפתח בבקשה הראשונה ולא בטעינת הקוד: הגדרה שגויה של D1 הפילה
# את כל הפריסה, ואי אפשר היה אפילו להיכנס ולראות מה השגיאה. עכשיו השירות
# עולה, ומוצגת הודעה שמסבירה מה לתקן.
_store = None


def get_store() -> CampaignStore:
    global _store
    if _store is None:
        _store = CampaignStore()
    return _store


class _StoreProxy:
    """מפנה כל קריאה למאגר הקמפיינים, שנפתח רק כשצריך."""

    def __getattr__(self, name):
        return getattr(get_store(), name)


store = _StoreProxy()


@app.errorhandler(500)
def internal_error(exc):
    # בלי זה העמוד מציג "500 Internal Server Error" ומאשים את המסד בכל תקלה.
    # החריגה המקורית היא מה שבאמת צריך לראות כדי לתקן.
    original = getattr(exc, "original_exception", None) or exc
    return render_template("dberror.html",
                           error=f"{type(original).__name__}: {original}"), 500


# ---------------------------- הגנה בסיסמה ----------------------------
# האפליקציה מציגה לידים ושולחת מיילים בשם החברה, ולכן היא לא נשארת פתוחה
# לכל מי שמגיע לכתובת. הפיקסל ובדיקת הבריאות נשארים ציבוריים בכוונה:
# הפיקסל נטען מתוכנת המייל של הנמען, שאין לה סשן.
PUBLIC_ENDPOINTS = {"pixel", "click", "click_ping", "health", "login", "static",
                    "api_campaigns", "api_import"}   # ה-API בודק מפתח בעצמו


@app.context_processor
def _inject_mode():
    """
    table = הדפדפן הוא הטבלה בלבד. החיפוש והשליחה רצים מהטרמינל, ולכן
    הבלוקים שלהם מוסתרים -- הם רק מוסיפים רעש למי שממלאת את הטבלה ביד.
    המסלולים עצמם נשארים, כדי ש-APP_MODE=full יחזיר הכול בלי שינוי קוד.
    """
    return {"full_mode": config.app_mode == "full",
            "auth_ok": (not config.app_password) or bool(session.get("ok"))}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not config.app_password or session.get("ok"):
            return view(*args, **kwargs)
        return redirect(url_for("login", next=request.path))
    return wrapped


@app.before_request
def guard():
    if request.endpoint in PUBLIC_ENDPOINTS or not config.app_password:
        return None
    if not session.get("ok"):
        return redirect(url_for("login", next=request.path))
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    if not config.app_password:
        return redirect(url_for("board"))
    error = ""
    if request.method == "POST":
        if (request.form.get("password") or "") == config.app_password:
            session["ok"] = True
            session.permanent = True
            return redirect(request.args.get("next") or url_for("board"))
        error = "סיסמה שגויה"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# מיפוי שם הקמפיין ב-DB הלידים -> נתיב הקובץ
def leads_db_path(source_campaign: str) -> str:
    if not source_campaign:
        return ""
    return (config.db_path if source_campaign == "funding"
            else os.path.join(config.data_dir, f"leads_{source_campaign}.db"))


#: Storage לכל קמפיין, נוצר פעם אחת. האובייקט לא מחזיק חיבור פתוח — כל
#: שאילתה פותחת וסוגרת — ולכן שמירתו רק חוסכת את הכנת הסכימה מחדש.
_STORES: dict = {}


def leads_store_or_error(source_campaign: str) -> tuple[Storage | None, str]:
    """
    מאגר הלידים של הקמפיין, ואם הוא לא נגיש — הסיבה.

    בדיקת קיום הקובץ תקפה רק לאחסון מקומי. ב-D1 אין קובץ בכלל, ולכן
    הבדיקה הזאת החזירה None תמיד — והמספרים בטבלה נשארו אפס גם כשהסריקה
    כן שמרה נתונים. וכשהחיבור ל-D1 שגוי צריך לומר זאת, לא להציג אפסים.
    """
    path = leads_db_path(source_campaign)
    if not path:
        return None, ""
    if not db.d1_configured() and not os.path.exists(path):
        return None, ""       # עוד לא נסרק כלום — לא שגיאה
    cached = _STORES.get(source_campaign)
    if cached is not None:
        return cached, ""
    try:
        store_obj = Storage(path, campaign=source_campaign)
    except Exception as exc:  # noqa: BLE001 — כשל אחסון לא מפיל את העמוד
        logger.warning("מאגר הלידים %s לא נגיש: %s", source_campaign, exc)
        return None, str(exc)
    _STORES[source_campaign] = store_obj
    return store_obj, ""


def leads_store(source_campaign: str):
    return leads_store_or_error(source_campaign)[0]


# ---------- פילוח: מי נפתח, מי ענה ומי חזר, לפי תחום / עיר / ספק / קמפיין ----------
_KNOWN_CITIES = ("בני ברק", "ירושלים", "בית שמש", "ביתר עילית", "מודיעין עילית", "אלעד",
                 "אשדוד", "רכסים", "עמנואל", "קרית יערים", "צפת", "נתיבות", "טבריה",
                 "פתח תקווה", "רמת גן", "נתניה", "רחובות", "אשקלון", "חיפה", "תל אביב",
                 "חולון", "גבעתיים", "באר שבע", "כוכב יעקב", "קרית גת", "יבנה", "לוד")
_ISP_OLD = {"netvision.net.il", "inter.net.il", "barak.net.il", "013.net", "013net.net",
            "013.net.il", "017.net.il", "012.net.il", "zahav.net.il", "actcom.co.il",
            "smile.net.il", "014.net", "bezeqint.net"}


#: אותו תחום שנכתב בשמות שונים ברשימות שונות
_FIELD_ALIASES = {"אדריכלות ועיצוב פנים": "אדריכלים", "ייעוץ מס": "יועצי מס",
                  "יועצי ביטוח": "סוכני ביטוח", "תשמישי קדושה ויודאיקה": "יודאיקה",
                  "תשמישי קדושה": "יודאיקה", "מהנדסים אזרחיים": "מהנדסי בניין",
                  "הפקות דפוס": "בתי דפוס", "פרוייקטים - ניהול תיאום ופיקוח": "פיקוח בנייה",
                  "ביקורת בניה": "פיקוח בנייה"}


def _city_of(address: str) -> str:
    address = address or ""
    for city in _KNOWN_CITIES:
        if city in address:
            return city
    tail = address.rsplit(",", 1)[-1].strip()
    return tail if tail and not any(ch.isdigit() for ch in tail) and len(tail) < 20 else "לא ידוע"


def _provider_of(email: str) -> str:
    domain = (email or "").rsplit("@", 1)[-1].lower()
    if domain == "gmail.com":
        return "Gmail"
    if domain.startswith("walla."):
        return "וואלה"
    if domain in _ISP_OLD:
        return "ספק אינטרנט ותיק (בזק, נטוויז'ן, 012...)"
    if domain.split(".")[0] in ("hotmail", "outlook", "yahoo", "icloud", "live", "aol"):
        return "Hotmail / Yahoo / iCloud"
    return "דומיין של העסק"


def segment_rows(campaigns) -> list:
    """שורה לכל נמען שקיבל מייל: התחום, העיר, הספק, ומה קרה איתו."""
    from concurrent.futures import ThreadPoolExecutor

    def one(campaign):
        st = leads_store(campaign["source_campaign"]) if campaign["source_campaign"] else None
        if not st:
            return []
        with st._conn() as conn:
            rows = conn.execute(
                f"""SELECT email, primary_type, address, opened_at, replied_at, bounced_at,
                          CASE WHEN {REAL_CLICK} THEN 1 ELSE 0 END AS real_click,
                          status, error FROM {{leads}}
                   WHERE status IN ('emailed','failed') AND campaign_id=?""",
                (str(campaign["id"]),)).fetchall()
        return [{"campaign": campaign["title"], "field": _FIELD_ALIASES.get((r["primary_type"] or "").strip(),
                                            (r["primary_type"] or "").strip()) or "לא ידוע",
                 "city": _city_of(r["address"]), "provider": _provider_of(r["email"]),
                 "opened": bool(r["opened_at"]), "replied": bool(r["replied_at"]),
                 "clicked": bool(r["real_click"]),
                 "bounced": bool(r["bounced_at"]) or (
                     r["status"] == "failed" and "connect" not in (r["error"] or "").lower())}
                for r in rows]

    with ThreadPoolExecutor(max_workers=8) as pool:
        return [row for rows in pool.map(one, campaigns) for row in rows]


def segment_table(rows, key: str, min_sent: int = 1) -> list:
    groups = {}
    for r in rows:
        g = groups.setdefault(r[key], {"name": r[key], "sent": 0, "opened": 0,
                                       "clicked": 0, "replied": 0, "bounced": 0})
        g["sent"] += 1
        g["opened"] += r["opened"]
        g["replied"] += r["replied"]
        g["clicked"] += r["clicked"]
        g["bounced"] += r["bounced"]
    out = []
    for g in groups.values():
        if g["sent"] < min_sent:
            continue
        delivered = max(g["sent"] - g["bounced"], 1)
        g["open_rate"] = round(100 * g["opened"] / delivered)
        g["reply_rate"] = round(100 * g["replied"] / delivered, 1)
        g["click_rate"] = round(100 * g["clicked"] / delivered, 1)
        g["bounce_rate"] = round(100 * g["bounced"] / g["sent"])
        out.append(g)
    return sorted(out, key=lambda g: (-g["reply_rate"], -g["sent"]))


@app.route("/segments")
def segments_page():
    client = request.args.get("client", "")
    campaigns = [c for c in store.all() if c["source_campaign"]
                 and _client_of(c) == (int(client) if client.isdigit() else None)]
    chosen = request.args.get("campaign", "")
    if chosen:
        campaigns = [c for c in campaigns if str(c["id"]) == chosen]
    rows = segment_rows(campaigns)
    min_sent = int(request.args.get("min", "5") or 5)
    tables = [("תחום", segment_table(rows, "field", min_sent)),
              ("עיר", segment_table(rows, "city", min_sent)),
              ("ספק מייל", segment_table(rows, "provider", 1))]
    if not chosen:
        tables.append(("קמפיין", segment_table(rows, "campaign", 1)))
    return render_template("segments.html", tables=tables, total=segment_table(rows, "provider", 0),
                           sent=len(rows), campaigns=store.all(), chosen=chosen, min_sent=min_sent)


def _app_version() -> str:
    """הגרסה שרצה: מזהה הקומיט, כדי לדעת אם המחשב עודכן."""
    if os.getenv("VERCEL_GIT_COMMIT_SHA"):     # בענן אין git ואין .app_version
        return os.environ["VERCEL_GIT_COMMIT_SHA"][:7]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(root, ".app_version"), encoding="utf-8") as f:
            return f.read().strip()[:7]
    except OSError:
        pass
    try:
        import subprocess
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


APP_VERSION = _app_version()


@app.context_processor
def _inject_version():
    return {"app_version": APP_VERSION}


def auto_metrics(campaign) -> dict:
    """נשלחו / נפתחו / השיבו — נמדדים מ-DB הלידים, לא מוזנים ביד."""
    empty = {"sent": 0, "opened": 0, "replied": 0, "clicked": 0, "bounced": 0,
             "last_sent": ""}
    st = leads_store(campaign["source_campaign"])
    if not st:
        return empty
    try:
        return st.variant_metrics(campaign["variant"] or "",
                                  campaign_id=str(campaign["id"]))
    except Exception:  # noqa: BLE001 — DB ישן בלי עמודות המעקב
        return empty


AUTO_TO_METRIC = {"כמות פניות": "sent", "כמות פתיחות": "opened",
                  "הודעה חוזרת": "replied"}


def _as_int(text) -> int | None:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


def campaign_profession(campaign) -> str:
    """
    שם התחום של הקמפיין, לשימוש במייל כשלא ידוע התחום של הנמען עצמו.

    חייב להיות המונח שנשלף מהפרומפט ולא הפרומפט הגולמי: אחרת המשפט
    "חיפשתי ... ונתקלתי בך" מקבל לתוכו את כל מה שמירי כתבה, כולל
    "תחפש", "שיש להם ביקורות באינטרנט" ושם העיר.
    """
    terms = pipeline.parse_prompt(_col(campaign, "search_query"))["terms"]
    return terms[0] if terms else ""


def custom_of(campaign):
    """הנוסח המותאם של הקמפיין, אם נכתב לו כזה."""
    subject = _col(campaign, "subject_tpl")
    body = _col(campaign, "body_tpl")
    if not (subject or body):
        return None
    # נוסח ב' להשוואה: אם מולא, השליחה מחלקת את הנמענים חצי-חצי
    return (subject, body, campaign_profession(campaign),
            _col(campaign, "subject_b"), _col(campaign, "body_b"))


def _col(row, name: str) -> str:
    try:
        return (row[name] or "").strip()
    except (IndexError, KeyError, TypeError):
        return ""


def ready_to_send(campaign, run) -> int:
    """
    כמה נמענים יישלחו בשליחה הבאה — המספר היחיד שבאמת מעניין.

    זה מי שיצא מהסריקה האחרונה, יש לו מייל, ועדיין לא נשלח אליו.

    בלי סריקה אין מה לשלוח — ובמכוון לא נופלים אחורה לכל המאגר. המאגר
    מצטבר וקיים כדי למנוע שליחה כפולה; להציג את גודלו כ"מוכנים לשליחה"
    לפני שחיפשת בכלל זה בדיוק מה שהיה מבלבל.
    """
    if not run:
        return 0
    st, _ = leads_store_or_error(_col(campaign, "source_campaign") or "agent")
    if not st:
        return 0
    try:
        return st.pending_count_for(str(run["id"]))
    except Exception:  # noqa: BLE001 — מאגר לא נגיש לא מפיל את העמוד
        return 0


def pool_of(campaign) -> tuple[dict, str]:
    """
    מצב מאגר הלידים של הקמפיין: כמה נסרקו, לכמה יש מייל, כמה ממתינים.

    נקרא רק בעמוד הקמפיין הבודד ולא בלוח — ב-D1 כל שאילתה היא קריאת רשת,
    ובלוח זה היה מכפיל את זמן הטעינה במספר הקמפיינים.
    """
    st, error = leads_store_or_error(_col(campaign, "source_campaign") or "agent")
    if not st:
        return {}, error
    try:
        return st.funnel(), ""
    except Exception as exc:  # noqa: BLE001 — כשל אחסון לא מפיל את העמוד
        logger.warning("קריאת מאגר הלידים נכשלה: %s", exc)
        return {}, str(exc)


def derived_fields(campaign) -> dict:
    """
    שורות התיאור שהאפליקציה כבר יודעת לענות עליהן בעצמה.

    "קהל יעד", "מקום חיפוש" ו"מאפיין" נגזרים ישירות מהחיפוש שהוגדר, ואין
    סיבה להקליד אותם ביד. הם מוצגים כברירת מחדל בלבד -- לא נשמרים -- כדי
    שישתנו לבד כשמשנים את החיפוש, וכל טקסט שנכתב ידנית גובר עליהם.

    "כאב" ו"הנעה לפעולה" נשארים ריקים בכוונה: אלה שיקולים שיווקיים
    שהמערכת לא יכולה לנחש.
    """
    parsed = pipeline.parse_prompt(_col(campaign, "search_query"))
    city = dict(CITIES).get(parsed["city"] or "jerusalem", "")
    out = {}
    if parsed["terms"]:
        out["קהל יעד"] = " · ".join(parsed["terms"])
    if city:
        out["מקום חיפוש"] = f"גוגל מפות — {city}"
    if _col(campaign, "search_query"):
        reviews = parsed["min_reviews"]
        rating = parsed["min_rating"]
        out["מאפיין"] = (f"לפחות {reviews if reviews is not None else config.agent_min_reviews} "
                         f"ביקורות, דירוג "
                         f"{rating if rating is not None else config.agent_min_rating:g} ומעלה")
    subject = _col(campaign, "subject_tpl")
    if subject:
        out["נוסח"] = subject
        out["נושא המייל"] = subject
    try:
        box = sender_box.SenderStore().get(_col(campaign, "sender_id"))
    except Exception:  # noqa: BLE001
        box = None
    if box:
        out["תיבת שליחה"] = f"{box['from_email']} (בשם {box['from_name'] or box['from_email']})"
    elif _col(campaign, "variant"):
        out["נוסח"] = f"נוסח {_col(campaign, 'variant').upper()}"
    return out


def campaign_view(campaign) -> dict:
    """
    כל מה שצריך להצגת עמודת קמפיין בלוח.

    שלוש שורות המספרים נמדדות מהמיילים שנשלחו, אבל ערך שהוזן ידנית גובר
    עליהן — כך אפשר להזין נתונים של סבבים שנשלחו לפני שהאפליקציה הייתה,
    ושל קמפיינים שאינם מייל בכלל (שיחות טלפון).
    """
    fields = store.fields(campaign["id"])
    measured = auto_metrics(campaign)
    metrics = dict(measured)

    for name, key in AUTO_TO_METRIC.items():
        manual = _as_int(fields[name]["value"])
        fields[name]["measured"] = measured[key]
        fields[name]["manual"] = manual is not None
        if manual is not None:
            metrics[key] = manual          # ערך ידני גובר על הנמדד
        elif campaign["source_campaign"]:
            fields[name]["value"] = str(measured[key])
    open_pct = (metrics["opened"] * 100 // metrics["sent"]) if metrics["sent"] else 0
    reply_pct = (metrics["replied"] * 100 // metrics["sent"]) if metrics["sent"] else 0
    click_pct = (metrics.get("clicked", 0) * 100 // metrics["sent"]) if metrics["sent"] else 0

    st = leads_store(campaign["source_campaign"])
    try:
        pending = st.pending_count() if st else 0
    except Exception:  # noqa: BLE001 — מאגר ישן/לא נגיש לא מפיל את הלוח
        pending = 0

    return {"campaign": campaign, "fields": fields, "metrics": metrics,
            "derived": derived_fields(campaign),
            "open_rate": f"{open_pct}%" if metrics["sent"] else "—",
            "reply_rate": f"{reply_pct}%" if metrics["sent"] else "—",
            "click_rate": f"{click_pct}%" if metrics["sent"] else "—",
            "bounce_rate": (f"{metrics.get('bounced', 0) * 100 // metrics['sent']}%"
                            if metrics["sent"] else "—"),
            "open_pct": open_pct, "reply_pct": reply_pct, "click_pct": click_pct,
            "bounce_pct": (metrics.get("bounced", 0) * 100 // metrics["sent"]) if metrics["sent"] else 0,
            "reply_exact": round(100 * metrics["replied"] / metrics["sent"], 1) if metrics["sent"] else 0,
            "pending": pending, "status": _status(metrics["sent"], pending)}


def ab_summary(campaign):
    """
    תוצאות השוואת הנוסחים של הקמפיין, ומי מוביל. None כשאין נוסח B.
    "מוביל" לפי אחוז תשובות, ואם שווה, לפי אחוז לחיצות. מבחן z לשני
    אחוזים אומר אם ההבדל כבר מספיק גדול כדי לסמוך עליו.
    """
    import math
    if not (_col(campaign, "subject_b") or _col(campaign, "body_b")):
        return None
    st = leads_store(_col(campaign, "source_campaign"))
    try:
        data = st.ab_metrics(campaign["id"]) if st else {}
    except Exception:  # noqa: BLE001
        data = {}
    subjects = {"A": _col(campaign, "subject_tpl"),
                "B": _col(campaign, "subject_b") or _col(campaign, "subject_tpl")}
    arms = []
    for name in ("A", "B"):
        d = data.get(name, {"sent": 0, "opened": 0, "clicked": 0, "replied": 0, "bounced": 0})
        n = max(d["sent"] - d["bounced"], 0)

        def rate(k, n=n, d=d):
            return round(100 * d[k] / n, 1) if n else 0
        arms.append({"name": name, "subject": subjects[name], **d, "delivered": n,
                     "open_rate": rate("opened"), "click_rate": rate("clicked"),
                     "reply_rate": rate("replied")})
    a, b = arms
    if not (a["delivered"] and b["delivered"]):
        return {"arms": arms, "winner": "", "verdict": "עוד לא נשלח לשני הנוסחים"}

    def z(key):
        p1, p2 = a[key] / a["delivered"], b[key] / b["delivered"]
        p = (a[key] + b[key]) / (a["delivered"] + b["delivered"])
        se = math.sqrt(p * (1 - p) * (1 / a["delivered"] + 1 / b["delivered"])) if 0 < p < 1 else 0
        return (p1 - p2) / se if se else 0.0
    key = "replied" if a["replied"] != b["replied"] else "clicked"
    if a[key] == b[key]:
        return {"arms": arms, "winner": "", "verdict": "עוד אין הבדל בין הנוסחים"}
    winner = "A" if a[key] / a["delivered"] > b[key] / b["delivered"] else "B"
    sure = abs(z(key)) >= 1.96
    label = "תשובות" if key == "replied" else "לחיצות"
    verdict = (f"נוסח {winner} מוביל ב{label}, וההבדל מובהק: אפשר לסמוך עליו"
               if sure else f"נוסח {winner} מוביל ב{label}, אבל עוד מוקדם לקבוע. כדאי לשלוח לעוד נמענים")
    return {"arms": arms, "winner": winner, "verdict": verdict}


def _status(sent: int, pending: int) -> tuple[str, str]:
    """(מחלקה, תווית) למצב הקמפיין בלוח."""
    if sent and pending:
        return "sending", "בשליחה"
    if pending:
        return "ready", "מוכן לשליחה"
    if sent:
        return "done", "הסתיים"
    return "empty", "בלי נמענים"


# ---------------------------- הלוח ----------------------------
@app.route("/")
def board():
    data = _dashboard([c for c in store.all() if not _client_of(c)])
    return render_template("board.html", **data,
                           text_fields=TEXT_FIELDS, auto_fields=AUTO_FIELDS,
                           manual_fields=MANUAL_FIELDS,
                           tracking_on=bool(config.tracking_base_url))


def _client_of(campaign):
    """מספר הלקוח של הקמפיין, או None לקמפיין שלנו."""
    value = str(_col(campaign, "client_id") or "").strip()
    return int(value) if value.isdigit() else None


def _dashboard(campaigns) -> dict:
    """הנתונים של לוח בקרה: עמודות, סיכומים, הקמפיין המוביל ומה ממתין."""
    # כל קמפיין דורש כמה שאילתות ל-D1, וכל שאילתה היא קריאת רשת. במקביל
    # הלוח נטען בזמן של הקמפיין האיטי ביותר, ולא בסכום של כולם.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:
        columns = list(pool.map(campaign_view, campaigns))
    try:
        boxes = {str(b["id"]): (b["from_name"] or b["from_email"] or "")
                 for b in sender_box.SenderStore().all()}
    except Exception:  # noqa: BLE001
        boxes = {}
    for col in columns:
        col["sender"] = boxes.get(sender_box.norm_id(_col(col["campaign"], "sender_id")), "")
    mail = [c for c in columns if c["campaign"]["kind"] == "email"]
    sent = sum(c["metrics"]["sent"] for c in mail)

    def pct(key):
        return round(100 * sum(c["metrics"].get(key, 0) or 0 for c in mail) / sent, 1) if sent else 0
    totals = {"sent": sent, "pending": sum(c["pending"] for c in mail),
              "replied": sum(c["metrics"]["replied"] for c in mail),
              "clicked": sum(c["metrics"].get("clicked", 0) or 0 for c in mail),
              "bounced": sum(c["metrics"].get("bounced", 0) or 0 for c in mail),
              "open": pct("opened"), "click": pct("clicked"), "reply": pct("replied"),
              "bounce": pct("bounced"),
              "active": sum(1 for c in columns if c["status"][0] in ("sending", "ready"))}
    # הקמפיין עם אחוז התשובות הגבוה ביותר (מתוך מי שנשלחו לו לפחות 30)
    ranked = [c for c in mail if c["metrics"]["sent"] >= 30]
    best = max(ranked, key=lambda c: c["reply_exact"]) if ranked else None
    todo = sorted([c for c in columns if c["pending"]], key=lambda c: -c["pending"])
    return {"columns": columns, "totals": totals, "todo": todo,
            "best_id": best["campaign"]["id"] if best else None}


# ---------------------------- לקוחות וארנק ----------------------------
_CLIENTS = None


def client_store() -> ClientStore:
    """נוצר פעם אחת: כל יצירה מכינה את הטבלאות, וב-D1 זו קריאת רשת."""
    global _CLIENTS
    if _CLIENTS is None:
        _CLIENTS = ClientStore()
    return _CLIENTS


def wallet(client_id, campaigns=None) -> dict:
    """
    יתרת הארנק של לקוח, במיילים. מייל שחזר לא נגבה, ולכן הוא חוזר לארנק.
    campaigns: קמפיינים שכבר נטענו (חוסך שאילתות). None = נשלפים מהמאגר.
    """
    if campaigns is None:
        campaigns = [c for c in store.all(include_archived=True) if _client_of(c) == int(client_id)]
    sent = bounced = 0
    for c in campaigns:
        m = auto_metrics(c)
        sent += m.get("sent", 0) or 0
        bounced += m.get("bounced", 0) or 0
    bought = client_store().purchased(client_id)
    charged = max(sent - bounced, 0)
    return {"bought": bought["emails"], "paid": bought["paid"], "sent": sent,
            "bounced": bounced, "charged": charged,
            "balance": bought["emails"] - charged}


def _scope(campaign):
    """
    בתוך מה בודקים כפילויות כשמעלים רשימה לקמפיין: הקמפיינים של אותו לקוח
    בלבד (או רק שלנו, לקמפיין שלנו). מחזיר (מאגרים, שמות ביומן השליחות).
    """
    client = _client_of(campaign)
    keys, names = set(), set()
    for c in store.all(include_archived=True):
        src = _col(c, "source_campaign")
        if src and _client_of(c) == client:
            keys.add(importer.key_for(src, leads_db_path(src)))
            names.add(src)
    return keys, names


@app.route("/clients", methods=["GET", "POST"])
def clients_page():
    cs = client_store()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("צריך שם ללקוח")
            return redirect(url_for("clients_page"))
        cid = cs.create(name, contact=(request.form.get("contact") or "").strip(),
                        email=(request.form.get("email") or "").strip(),
                        phone=(request.form.get("phone") or "").strip())
        flash(f"נפתחה תיקייה ללקוח {name}")
        return redirect(url_for("client_page", client_id=cid))
    every = store.all(include_archived=True)
    rows = []
    for cl in cs.all():
        mine = [c for c in every if _client_of(c) == cl["id"]]
        rows.append({"client": cl, "wallet": wallet(cl["id"], mine),
                     "campaigns": len([c for c in mine if not c["archived"]])})
    return render_template("clients.html", rows=rows)


@app.route("/client/<int:client_id>", methods=["GET", "POST"])
def client_page(client_id):
    cs = client_store()
    client = cs.get(client_id)
    if not client:
        return redirect(url_for("clients_page"))
    if request.method == "POST":
        cs.update(client_id, **{k: (request.form.get(k) or "").strip()
                                for k in ("name", "contact", "email", "phone", "notes")
                                if k in request.form})
        flash("פרטי הלקוח נשמרו")
        return redirect(url_for("client_page", client_id=client_id))
    every = store.all(include_archived=True)
    mine = [c for c in every if _client_of(c) == client_id]
    data = _dashboard([c for c in mine if not c["archived"]])
    return render_template("client.html", client=client, **data,
                           wallet=wallet(client_id, mine), tx=cs.transactions(client_id),
                           kinds=TX_KINDS, packages=cs.packages(),
                           boxes=sender_box.SenderStore().for_client(client_id),
                           per_email=cs.per_email_price())


@app.route("/client/<int:client_id>/delete", methods=["POST"])
def client_delete(client_id):
    """
    מחיקת לקוח: התיקייה, הקמפיינים שלו, הארנק והתיבות שלו (כולל הסיסמאות).
    רשימות הנמענים עצמן נשארות במאגר, כדי שאם ייפתח שוב לא יישלח פעמיים.
    """
    cs = client_store()
    client = cs.get(client_id)
    if not client:
        return redirect(url_for("clients_page"))
    if (request.form.get("confirm") or "").strip() != client["name"].strip():
        flash("כדי למחוק צריך להקליד את שם הלקוח בדיוק")
        return redirect(url_for("client_page", client_id=client_id))
    removed = 0
    for c in store.all(include_archived=True):
        if _client_of(c) == client_id:
            store.delete(c["id"])
            removed += 1
    boxes = sender_box.SenderStore()
    for b in boxes.for_client(client_id):
        boxes.delete(b["id"])
    cs.delete(client_id)
    flash(f"הלקוח {client['name']} נמחק, עם {removed} קמפיינים, הארנק ותיבות השליחה שלו.")
    return redirect(url_for("clients_page"))


@app.route("/client/<int:client_id>/wallet", methods=["POST"])
def client_wallet_add(client_id):
    """רכישת חבילה, רכישה לפי מספר מיילים, או תיקון ידני."""
    cs = client_store()
    kind = request.form.get("kind", "package")
    try:
        if kind == "package":
            emails, amount = request.form.get("package", "0:0").split(":")
            emails, amount = int(emails), float(amount)
        else:
            emails = int(request.form.get("emails") or 0)
            amount = float(request.form.get("amount") or 0)
    except ValueError:
        flash("המספרים לא תקינים")
        return redirect(url_for("client_page", client_id=client_id))
    if kind == "refund":
        emails, amount = -abs(emails), -abs(amount)
    if not emails and not amount:
        flash("לא הוזן מספר מיילים או סכום")
        return redirect(url_for("client_page", client_id=client_id))
    cs.add_tx(client_id, kind, emails, amount, request.form.get("note", ""))
    flash(f"נרשם בארנק: {emails:+,} מיילים, {amount:,.0f} ש\"ח")
    return redirect(url_for("client_page", client_id=client_id))


@app.route("/client/<int:client_id>/wallet/<int:tx_id>/delete", methods=["POST"])
def client_wallet_delete(client_id, tx_id):
    client_store().delete_tx(tx_id)
    flash("התנועה נמחקה מהארנק")
    return redirect(url_for("client_page", client_id=client_id))


@app.route("/pricing", methods=["GET", "POST"])
def pricing_page():
    cs = client_store()
    if request.method == "POST":
        packages = []
        for e, p in zip(request.form.getlist("emails"), request.form.getlist("price")):
            try:
                if e.strip() and p.strip():
                    packages.append((int(e), float(p)))
            except ValueError:
                continue
        if packages:
            cs.set_packages(packages)
        try:
            cs.set_setting("per_email_price", str(float(request.form.get("per_email") or 0)))
        except ValueError:
            pass
        flash("המחירון נשמר")
        return redirect(url_for("pricing_page"))
    return render_template("pricing.html", packages=cs.packages(), per_email=cs.per_email_price())


# ---------------------------- חיבור לשיחת החיפוש ----------------------------
@app.route("/guide")
def guide_page():
    return render_template("guide.html")


@app.route("/connect", methods=["GET", "POST"])
def connect_page():
    """המפתח והכתובת שאיתם שיחת החיפוש שולחת רשימות ישר לקמפיין."""
    cs = client_store()
    if request.method == "POST":
        cs.new_api_token()
        flash("נוצר מפתח חדש. הישן כבר לא עובד: צריך להעביר את החדש לשיחת החיפוש.")
        return redirect(url_for("connect_page"))
    base = (os.getenv("PUBLIC_URL") or request.url_root).rstrip("/")
    campaigns = [c for c in store.all() if c["kind"] == "email"]
    clients = {cl["id"]: cl["name"] for cl in cs.all(include_archived=True)}
    return render_template("connect.html", token=cs.api_token(), base=base,
                           campaigns=campaigns, clients=clients,
                           client_of=_client_of)


def _api_authorized() -> bool:
    import hmac
    header = request.headers.get("Authorization", "")
    given = header[7:].strip() if header.lower().startswith("bearer ") else \
        (request.headers.get("X-Api-Key") or request.args.get("token") or "")
    token = client_store().api_token(create=False)
    return bool(token and given and hmac.compare_digest(given, token))


@app.route("/api/campaigns")
def api_campaigns():
    if not _api_authorized():
        return jsonify({"error": "מפתח חסר או שגוי"}), 401
    names = {cl["id"]: cl["name"] for cl in client_store().all(include_archived=True)}
    return jsonify([{"id": c["id"], "title": c["title"],
                     "client": names.get(_client_of(c), "") if _client_of(c) else ""}
                    for c in store.all() if c["kind"] == "email"])


@app.route("/api/import", methods=["POST"])
def api_import():
    """
    שיחת החיפוש שולחת לכאן רשימה, והיא עוברת את אותן בדיקות כמו העלאת קובץ.
    גוף הבקשה (JSON): {"campaign_id": 40, "group": "...", "rows": [{"name": ..,
    "email": .., "phone": .., "city": .., "group": .., "first_name": ..}]}
    או {"campaign_id": 40, "csv": "טקסט CSV"}.
    """
    if not _api_authorized():
        return jsonify({"error": "מפתח חסר או שגוי"}), 401
    body = request.get_json(silent=True) or {}
    campaign = store.get(int(body.get("campaign_id") or 0)) if str(body.get("campaign_id") or "").isdigit() else None
    if not campaign:
        return jsonify({"error": "campaign_id חסר או לא קיים. רשימת הקמפיינים: /api/campaigns"}), 400
    if body.get("csv"):
        rows = importer.read_table("api.csv", str(body["csv"]).encode("utf-8"))
    else:
        rows = [r for r in (body.get("rows") or []) if isinstance(r, dict)]
    if not rows or "email" not in importer.map_columns(list(rows[0].keys())):
        return jsonify({"error": "אין שורות, או שאין בהן שדה email"}), 400
    result = _run_import(campaign, rows, (body.get("group") or "").strip(), "api")
    return jsonify({"campaign": campaign["title"], "received": len(rows),
                    "added": len(result["added"]), "skipped": len(result["skipped"]),
                    "reasons": dict(result["reasons"]),
                    "skipped_list": result["skipped"][:200]})


def _run_import(campaign, rows, group: str, prefix: str) -> dict:
    """ייבוא משותף לקובץ מהדפדפן ולשיחת החיפוש."""
    source = _ensure_source(campaign)
    storage = Storage(leads_db_path(source), campaign=source)
    keys, names = _scope(store.get(campaign["id"]))
    known = importer.known_addresses(config.data_dir, own=importer.own_key(storage),
                                     scope=keys, sent_keys=names)
    result = importer.import_contacts(storage, rows, prefix=f"{prefix}{campaign['id']}",
                                      known=known, default_group=group)
    titles = importer.campaign_titles(store)
    reasons = {}
    for item in result["skipped"]:
        if item["reason"].startswith("pending:"):
            item["reason"] = "ממתין בקמפיין " + titles.get(item["reason"][8:], "אחר")
        key = item["reason"] if not item["reason"].startswith("ממתין בקמפיין") \
            else "ממתין בקמפיין אחר"
        if "ספק ישן" in key:
            key = "ספק מייל ישן"
        elif key.startswith("הדומיין"):
            key = "הדומיין לא מקבל מיילים"
        reasons[key] = reasons.get(key, 0) + 1
    result["reasons"] = sorted(reasons.items(), key=lambda kv: -kv[1])
    return result


@app.route("/campaign/new", methods=["POST"])
def campaign_new():
    title = (request.form.get("title") or "").strip()
    if not title:
        flash("צריך שם לקמפיין")
        return redirect(url_for("board"))
    cid = store.create(title,
                       kind=request.form.get("kind", "email"),
                       source_campaign=(request.form.get("source_campaign") or "").strip(),
                       variant=(request.form.get("variant") or "").strip())
    client_id = (request.form.get("client_id") or "").strip()
    if client_id.isdigit():
        store.update(cid, client_id=client_id, source_campaign=f"c{cid}")
    return redirect(url_for("campaign_edit", campaign_id=cid))


@app.route("/campaign/<int:campaign_id>", methods=["GET", "POST"])
def campaign_edit(campaign_id):
    campaign = store.get(campaign_id)
    if not campaign:
        return redirect(url_for("board"))

    if request.method == "POST":
        # רק שדות שבאמת היו בטופס. במצב "טבלה" שדות הנוסח והחיפוש מוסתרים,
        # ובלי הבדיקה הזאת כל שמירה מחקה את נושא המייל וגוף המייל של הקמפיין.
        posted = {k: (request.form.get(k) or "").strip()
                  for k in ("title", "started_on", "source_campaign", "variant",
                            "search_query", "subject_tpl", "body_tpl",
                            "subject_b", "body_b")
                  if k in request.form}
        if "kind" in request.form:
            posted["kind"] = request.form.get("kind", "email")
        store.update(campaign_id, **posted)
        # שורה נמדדת שנשלחה עם המספר שהמערכת עצמה הציגה לא נשמרת כערך ידני.
        # אחרת כל לחיצה על "שמירה" מקפיאה את המספר של אותו רגע, והפתיחות
        # והתשובות שמגיעות אחר כך לא נכנסות יותר לטבלה.
        measured = auto_metrics(campaign)
        for field in ALL_FIELDS:
            value = request.form.get(f"value::{field}", "")
            key = AUTO_TO_METRIC.get(field)
            if key and value.strip() == str(measured.get(key, "")):
                value = ""
            store.set_field(
                campaign_id, field,
                value=value,
                note=request.form.get(f"note::{field}", ""),
                improve=request.form.get(f"improve::{field}", ""))
        flash("נשמר")
        # חוזרים ישר לבלוק הסריקה — זה הצעד הבא אחרי שמירת ההגדרות
        return redirect(url_for("campaign_edit", campaign_id=campaign_id,
                                saved=1) + "#scan")

    view = campaign_view(campaign)
    pool = pool_of(campaign)
    run = store.run_of(campaign_id)
    client = client_store().get(_client_of(campaign)) if _client_of(campaign) else None
    return render_template("campaign.html", **view, text_fields=TEXT_FIELDS, client=client,
                           ab=ab_summary(campaign),
                           ready=ready_to_send(campaign, run),
                           auto_fields=AUTO_FIELDS, manual_fields=MANUAL_FIELDS,
                           cities=CITIES, pool=pool[0], pool_error=pool[1],
                           min_reviews=config.agent_min_reviews,
                           min_rating=config.agent_min_rating,
                           parsed=pipeline.parse_prompt(_col(campaign, "search_query")),
                           describe=pipeline.describe_prompt,
                           just_saved=bool(request.args.get("saved")),
                           busy=runner.busy, run=run,
                           placeholders=list(mail_templates.PLACEHOLDERS))


@app.route("/campaign/<int:campaign_id>/delete", methods=["POST"])
def campaign_delete(campaign_id):
    store.delete(campaign_id)
    return redirect(url_for("board"))


# ---------------------------- שליחה ----------------------------
@app.route("/campaign/<int:campaign_id>/send")
def send_page(campaign_id):
    campaign = store.get(campaign_id)
    st = leads_store(campaign["source_campaign"]) if campaign else None
    if not st:
        flash("לקמפיין הזה אין מאגר לידים מקושר")
        return redirect(url_for("campaign_edit", campaign_id=campaign_id))

    limit = int(request.args.get("limit", 500))
    # ברירת המחדל: רק מי שיצא מהסריקה האחרונה של הקמפיין. המאגר מצטבר
    # ותפקידו למנוע שליחה כפולה, אבל אין סיבה להציג כאן את כל מה שנאסף אי פעם.
    run = store.run_of(campaign_id)
    all_pool = request.args.get("all") == "1"
    run_id = "" if all_pool or not run else str(run["id"])
    pending = st.leads_to_email(limit, run_id=run_id)
    boxes = sender_box.SenderStore()
    own_boxes = boxes.for_client(_client_of(campaign))
    sender_id = sender_box.norm_id(_col(campaign, "sender_id"))
    if sender_id not in {str(b["id"]) for b in own_boxes}:
        # תיבה של תיקייה אחרת לא נבחרת. ללקוח עם תיבה אחת, היא נבחרת לבד.
        sender_id = str(own_boxes[0]["id"]) if _client_of(campaign) and len(own_boxes) == 1 else ""
    chosen = boxes.get(sender_id)
    sender = sender_box.as_smtp(chosen)
    previews = []
    for lead in pending:
        template_campaign = (f"{campaign['source_campaign']}_offer"
                             if campaign["variant"] == "b"
                             else campaign["source_campaign"])
        lead_custom, arm = pipeline.pick_custom(custom_of(campaign), lead["email"])
        subject, _html, text = pipeline._render(
            template_campaign,
            pipeline.build_ctx(config, campaign["source_campaign"], lead,
                               sender=sender),
            lead_custom)
        previews.append({"lead": lead, "subject": subject, "text": text, "arm": arm})
    env_from, env_name, _, _ = config.sender_for(campaign["source_campaign"])

    # ב-Vercel כל לחיצה שולחת עד SEND_BATCH, אז מסמנים מראש מנה כזו
    first_n = int(os.getenv("SEND_BATCH", "50")) if os.getenv("VERCEL") else 150
    return render_template("send.html", campaign=campaign, previews=previews,
                           first_n=first_n,
                           scan_only=bool(run_id), has_run=bool(run),
                           pool_total=st.pending_count_for(),
                           sample=previews[0] if previews else None,
                           sent=st.sent_leads(campaign["variant"] or "", 200,
                                         campaign_id=str(campaign_id)),
                           tracking_on=bool(config.tracking_base_url),
                           senders=own_boxes, sender_id=sender_id,
                           env_sender=f"{env_name} <{env_from}>" if env_from else "",
                           client=client_store().get(_client_of(campaign)) if _client_of(campaign) else None,
                           wallet=wallet(_client_of(campaign)) if _client_of(campaign) else None)


@app.route("/campaign/<int:campaign_id>/send", methods=["POST"])
def send_now(campaign_id):
    campaign = store.get(campaign_id)
    st = leads_store(campaign["source_campaign"]) if campaign else None
    if not st:
        return redirect(url_for("board"))

    chosen = set(request.form.getlist("place_id"))
    if not chosen:
        flash("לא נבחר אף נמען")
        return redirect(url_for("send_page", campaign_id=campaign_id))

    # קמפיין של לקוח: שולחים רק כמה שיש בארנק
    if _client_of(campaign):
        balance = wallet(_client_of(campaign))["balance"]
        if balance <= 0:
            flash("אין יתרה בארנק של הלקוח. אפשר להוסיף חבילה בעמוד הלקוח.")
            return redirect(url_for("send_page", campaign_id=campaign_id))
        if len(chosen) > balance:
            keep = [p for p in request.form.getlist("place_id") if p in chosen][:balance]
            flash(f"ביתרה של הלקוח יש {balance} מיילים, ולכן נשלחים רק {balance} מתוך "
                  f"{len(chosen)} שסימנת.")
            chosen = set(keep)

    # מאיזו תיבה לשלוח: נבחרת בעמוד השליחה ונזכרת לקמפיין לפעם הבאה
    sender_id = (request.form.get("sender_id") or "").strip()
    owner = str(_client_of(campaign) or "")
    if sender_id and sender_box.owner_of(sender_box.SenderStore().get(sender_id)) != owner:
        flash("התיבה שנבחרה לא שייכת לתיקייה של הקמפיין הזה")
        return redirect(url_for("send_page", campaign_id=campaign_id))
    if owner and not sender_id:
        flash("ללקוח צריך תיבת שליחה משלו. מוסיפים אותה בעמוד הלקוח, תחת 'תיבות שליחה'.")
        return redirect(url_for("send_page", campaign_id=campaign_id))
    store.update(campaign_id, sender_id=sender_id)
    sender = sender_box.as_smtp(sender_box.SenderStore().get(sender_id))
    if sender:
        errors = sender_box.missing(sender)
        if errors:
            flash("לתיבה שנבחרה חסר: " + ", ".join(errors)
                  + ". אפשר להשלים בעמוד תיבות שליחה.")
            return redirect(url_for("send_page", campaign_id=campaign_id))
    else:
        errors = config.validate_for_email(campaign["source_campaign"])
        if errors:
            flash("חסרות הגדרות שליחה: " + ", ".join(errors))
            return redirect(url_for("send_page", campaign_id=campaign_id))

    if os.getenv("VERCEL"):
        # ב-Vercel אין עבודה ברקע: התהליך נעצר כשהתשובה נשלחת, וכל בקשה
        # מוגבלת ל-300 שניות. לכן שולחים מנה שנכנסת בזמן הזה, ומי שנשאר
        # נשאר מסומן בעמוד, ולחיצה נוספת שולחת את המנה הבאה.
        batch = int(os.getenv("SEND_BATCH", "50"))
        ordered = [p for p in request.form.getlist("place_id") if p in chosen]
        now, rest = ordered[:batch], ordered[batch:]
        try:
            summary = pipeline.send_emails(
                config, st, campaign=campaign["source_campaign"],
                limit=len(now), variant=campaign["variant"] or "", only=set(now),
                custom=custom_of(campaign), campaign_id=str(campaign_id),
                sender=sender)
        except Exception as exc:  # noqa: BLE001 — סיסמה שגויה וכו' מוצגים, לא 500
            flash(f"השליחה נכשלה: {exc}")
            return redirect(url_for("send_page", campaign_id=campaign_id))
        msg = f"נשלחו {summary.get('sent', 0)} מיילים."
        if rest:
            msg += (f" נשארו {len(rest)} מאלה שסימנת: מסמנים שוב ולוחצים "
                    f"שליחה, ויוצאת המנה הבאה (עד {batch} בכל לחיצה).")
        flash(msg)
        return redirect(url_for("send_page", campaign_id=campaign_id))

    # השליחה רצה ברקע: 150 מיילים עם השהיה ביניהם לוקחים כמה דקות, יותר
    # ממה שבקשת דפדפן (ו-gunicorn בענן) מחכים. עמוד ההרצות מציג התקדמות.
    def work(job):
        return pipeline.send_emails(
            config, st, campaign=campaign["source_campaign"],
            limit=len(chosen), variant=campaign["variant"] or "", only=chosen,
            custom=custom_of(campaign), campaign_id=str(campaign_id),
            sender=sender)

    ok, msg = runner.start("send", f"שליחה: {campaign['title']} ({len(chosen)} נמענים)", work)
    flash(msg if not ok else f"השליחה התחילה ל-{len(chosen)} נמענים. "
          "אפשר לעקוב כאן, ובסוף יופיע כמה נשלחו.")
    return redirect(url_for("jobs_page"))


def _campaign_sender(campaign) -> dict:
    """התיבה שממנה יצא הקמפיין: זו שנבחרה בדפדפן, ואם אין, זו מ-.env."""
    sender = sender_box.as_smtp(sender_box.SenderStore().get(_col(campaign, "sender_id")))
    if sender:
        return sender
    from_email, _, user, password = config.sender_for(campaign["source_campaign"])
    host, _, _ = config.smtp_server_for(campaign["source_campaign"])
    return {"from_email": from_email, "smtp_user": user,
            "smtp_password": password, "smtp_host": host}


#: סימון של כתובת בדיקה פנימית (המייל של מירי שנוסף לקמפיין לבדיקה)
INTERNAL_TEST = "בדיקה פנימית"


def _is_internal_test(lead) -> bool:
    return (lead["primary_type"] or "") == INTERNAL_TEST


def _sent_subjects(items) -> dict:
    """
    {נושא שנשלח לנמען (מנורמל): הנמען}, כדי לזהות תשובה שהגיעה מכתובת אחרת.
    נושא שנשלח ליותר מנמען אחד (נושא בלי שם העסק) לא נכנס: אי אפשר לדעת
    למי מהם התשובה שייכת.
    """
    from egud_bot import replies
    seen, out = set(), {}
    for st, sent in items:
        campaign = next((c for c in store.all()
                         if c["source_campaign"] == st.campaign and c["subject_tpl"]), None)
        if not campaign:
            continue
        for lead in sent:
            if _is_internal_test(lead):
                continue
            subject = mail_templates.render_subject(
                campaign["subject_tpl"], business_name=lead["name"] or "",
                first_name=lead["first_name"] or "")
            norm, _ = replies.normalize_subject(subject)
            if not norm:
                continue
            if norm in out or norm in seen:
                out.pop(norm, None)
                seen.add(norm)
                continue
            out[norm] = (lead["email"] or "").lower()
    return out


def _check_campaigns(campaigns) -> list[str]:
    """
    בודק תשובות לכמה קמפיינים. נכנס לכל תיבה פעם אחת בלבד, גם כשכמה
    קמפיינים יצאו ממנה. מחזיר שורת סיכום לכל תיבה.
    """
    from egud_bot import replies
    by_box = {}
    for campaign in campaigns:
        st = leads_store(campaign["source_campaign"]) if campaign["source_campaign"] else None
        if not st:
            continue
        sent = st.sent_leads(campaign["variant"] or "", 2000,
                             campaign_id=str(campaign["id"]))
        if not sent:
            continue
        sender = _campaign_sender(campaign)
        key = (sender.get("from_email") or "").lower()
        box = by_box.setdefault(key, {"sender": sender, "items": []})
        box["items"].append((st, sent))
    lines = []
    for key, box in by_box.items():
        emails = [l["email"] for _, sent in box["items"] for l in sent]
        try:
            result = replies.find_replies(box["sender"], emails,
                                          subjects=_sent_subjects(box["items"]))
        except Exception as exc:  # noqa: BLE001
            lines.append(f"לא הצלחתי להיכנס לתיבה {key}: {exc}")
            continue
        found, bounces = result["replies"], result["bounces"]
        removals = result.get("unsubscribes") or set()
        # נמען שקיבל כמה קמפיינים: התשובה שייכת לשליחה האחרונה שקדמה לה,
        # ולא לכל הקמפיינים שהוא היה בהם
        sends = {}
        for st, sent in box["items"]:
            for lead in sent:
                if _is_internal_test(lead):
                    continue   # כתובת בדיקה שלנו: מה שמגיע ממנה אינו תשובה של עסק
                sends.setdefault((lead["email"] or "").lower(), []).append((st, lead))
        new = 0
        for addr, items in sends.items():
            hit = found.get(addr)
            if hit:
                when = hit[0] or "9999"
                before = [it for it in items if (it[1]["emailed_at"] or "") <= when]
                st, lead = max(before or items, key=lambda it: it[1]["emailed_at"] or "")
                if addr in removals:
                    # לא נספר כ"ענה": בקשת הסרה היא לא עניין במענק
                    st.unsubscribe(addr, f"ביקש להסיר: {hit[1]}"[:200])
                elif not lead["replied_at"]:
                    st.mark_replied(lead["email"], f"ענה: {hit[1]}"[:200])
                    new += 1
            if addr in bounces:
                for st, lead in items:
                    st.mark_bounced(lead["email"], f"המייל חזר: {bounces[addr]}"[:200])
        answered = sum(1 for addr in sends if addr in found)
        removed = sum(1 for addr in sends if addr in removals)
        lines.append(f"{key}: {answered} ענו ({new} חדשים), {len(bounces)} מיילים חזרו"
                     + (f", {removed} ביקשו להסיר" if removed else ""))
    return lines or ["אין עדיין קמפיינים שנשלחו מהם מיילים"]


@app.route("/check_replies", methods=["POST"])
def check_all_replies():
    """כפתור בלוח הראשי: בודק תשובות בכל הקמפיינים בבת אחת."""
    for line in _check_campaigns(store.all()):
        flash("בדיקת תשובות: " + line)
    return redirect(url_for("board"))


@app.route("/campaign/<int:campaign_id>/check_replies", methods=["POST"])
def check_replies(campaign_id):
    """נכנס לתיבה שממנה נשלח הקמפיין ומסמן את מי שענה."""
    campaign = store.get(campaign_id)
    if not campaign:
        return redirect(url_for("board"))
    for line in _check_campaigns([campaign]):
        flash("בדיקת תשובות: " + line)
    # חוזרים לעמוד שממנו לחצו (עמוד הקמפיין או עמוד השליחה)
    return redirect(request.referrer or url_for("send_page", campaign_id=campaign_id))


@app.route("/campaign/<int:campaign_id>/replied", methods=["POST"])
def mark_replied(campaign_id):
    campaign = store.get(campaign_id)
    st = leads_store(campaign["source_campaign"]) if campaign else None
    if st:
        st.mark_replied(request.form.get("email", ""),
                        (request.form.get("note") or "").strip())
        flash("נרשמה תשובה")
    return redirect(url_for("send_page", campaign_id=campaign_id))


# ---------------------------- פיקסל המעקב ----------------------------
@app.route("/px/<track_id>.gif")
def pixel(track_id):
    # מחפשים בכל מאגרי הלידים — המזהה ייחודי ולכן יימצא רק באחד מהם
    for campaign in {c["source_campaign"] for c in store.all()
                     if c["source_campaign"]}:
        st = leads_store(campaign)
        if st and st.mark_opened(track_id):
            break
    return Response(tracking.TRANSPARENT_GIF, mimetype="image/gif",
                    headers={"Cache-Control": "no-store, no-cache, must-revalidate",
                             "Pragma": "no-cache"})


@app.route("/c/ping")
def click_ping():
    return Response("clicks-ok", mimetype="text/plain")


@app.route("/c/<track_id>/<int:link_id>")
def click(track_id, link_id):
    """לחיצה על קישור במייל: רושמים ומפנים ליעד. משמש כשאין Worker בענן."""
    for campaign in {c["source_campaign"] for c in store.all()
                     if c["source_campaign"]}:
        st = leads_store(campaign)
        url = st.link_url(link_id) if st else ""
        if url and st.mark_clicked(track_id):
            return redirect(url)
    return Response("הקישור לא נמצא", status=404)


# ---------------------------- סריקה והעשרה ----------------------------
# תקציב הזמן של מנת סריקה אחת. חייב להיות קצר בהרבה מהמגבלה של סביבת
# הריצה (Vercel קוטע ב-300 שניות), כדי שתמיד נספיק לשמור ולחזור.
SCAN_BUDGET_SECONDS = float(os.getenv("SCAN_BUDGET_SECONDS", "40"))

CITIES = [("jerusalem", "ירושלים"), ("bnei-brak", "בני ברק"),
          ("beitar", "ביתר עילית"), ("modiin-illit", "מודיעין עילית"),
          ("elad", "אלעד"), ("beit-shemesh", "בית שמש"),
          ("ashdod", "אשדוד"), ("all", "כל הערים החרדיות")]


@app.route("/jobs")
def jobs_page():
    back = request.args.get("campaign", type=int)
    return render_template("jobs.html", job=runner.current or runner.last,
                           back_campaign=back,
                           busy=runner.busy, cities=CITIES,
                           has_key=bool(config.google_api_key))


@app.route("/jobs/scan", methods=["POST"])
def jobs_scan():
    if not config.google_api_key:
        flash("חסר GOOGLE_MAPS_API_KEY — בלעדיו אי אפשר לסרוק")
        return redirect(url_for("jobs_page"))

    campaign = (request.form.get("campaign") or "agent").strip()
    city = request.form.get("city") or "jerusalem"
    target = int(request.form.get("target") or 50)
    city_name = dict(CITIES).get(city, city)

    def work(job):
        storage = Storage(leads_db_path(campaign), campaign=campaign)
        return pipeline.scan(config, storage, campaign=campaign, city=city,
                             target_emails=target)

    ok, msg = runner.start("scan", f"סריקה: {city_name} (יעד {target})", work)
    flash(msg)
    return redirect(url_for("jobs_page"))


@app.route("/jobs/release", methods=["POST"])
def jobs_release():
    """משחרר הרצה תקועה — כשהשירות הופעל מחדש באמצע וההרצה 'רצה' לנצח."""
    flash("ההרצה שוחררה, אפשר להתחיל מחדש" if runner.release()
          else "אין הרצה תקועה לשחרר")
    campaign = request.form.get("campaign", type=int)
    return redirect(url_for("jobs_page", campaign=campaign) if campaign
                    else url_for("jobs_page"))


@app.route("/jobs/enrich", methods=["POST"])
def jobs_enrich():
    campaign = (request.form.get("campaign") or "agent").strip()
    limit = int(request.form.get("limit") or 50)

    def work(job):
        storage = Storage(leads_db_path(campaign), campaign=campaign)
        return pipeline.enrich_missing_emails(config, storage, limit)

    ok, msg = runner.start("enrich", f"השלמת מיילים ({limit} לידים)", work)
    flash(msg)
    return redirect(url_for("jobs_page"))


@app.route("/campaign/<int:campaign_id>/scan", methods=["POST"])
def campaign_scan(campaign_id):
    """פותח הרצת סריקה. העבודה עצמה נעשית במנות, מעמוד ההתקדמות."""
    campaign = store.get(campaign_id)
    query = _col(campaign, "search_query")
    source = _col(campaign, "source_campaign") or "agent"
    if not query:
        flash("צריך למלא תחום לחיפוש בהגדרות הקמפיין")
        return redirect(url_for("campaign_edit", campaign_id=campaign_id))
    if not config.google_api_key:
        flash("חסר GOOGLE_MAPS_API_KEY — בלעדיו אי אפשר לסרוק")
        return redirect(url_for("campaign_edit", campaign_id=campaign_id))

    # מה שנכתב בפרומפט גובר; מה שלא נאמר בו נשאר בברירת המחדל
    parsed = pipeline.parse_prompt(query)
    min_reviews = parsed["min_reviews"]
    if min_reviews is None:
        min_reviews = config.agent_min_reviews
    min_rating = parsed["min_rating"]
    if min_rating is None:
        min_rating = config.agent_min_rating

    store.start_run(campaign_id, source=source, query=query,
                    city=parsed["city"] or "jerusalem",
                    target=max(1, min(parsed["target"] or 50, 500)),
                    min_reviews=max(0, min(int(min_reviews), 100)),
                    min_rating=max(0.0, min(float(min_rating), 5.0)))
    return redirect(url_for("scan_progress", campaign_id=campaign_id))


@app.route("/campaign/<int:campaign_id>/scan/progress")
def scan_progress(campaign_id):
    campaign = store.get(campaign_id)
    if not campaign:
        return redirect(url_for("board"))
    run = store.run_of(campaign_id)
    if not run:
        flash("לא נמצאה סריקה לקמפיין הזה")
        return redirect(url_for("campaign_edit", campaign_id=campaign_id))
    return render_template("scan.html", campaign=campaign, run=run,
                           counters=_run_counters(run),
                           terms=(pipeline.parse_prompt(_col(run, "query"))["terms"]
                                  or pipeline.split_query(_col(run, "query"))))


def _run_counters(run) -> dict:
    try:
        return json.loads(_col(run, "counters") or "{}")
    except ValueError:
        return {}


@app.route("/campaign/<int:campaign_id>/scan/step", methods=["POST"])
def scan_step(campaign_id):
    """
    מנה אחת של סריקה, ואז חוזרים.

    זה הלב של הסריקה באפליקציה: כל קריאה עושה כמה עשרות שניות של עבודה,
    שומרת את מה שנמצא ואת מיקומה, וחוזרת. הדפדפן קורא שוב עד שנגמר. כך
    הסריקה לא תלויה בבקשת HTTP ארוכה, לא נקטעת בפריסה, ואפשר לעצור
    ולהמשיך — גם בסביבה שקוטעת כל בקשה אחרי דקות ספורות.
    """
    run = store.run_of(campaign_id)
    if not run or _col(run, "status") != "running":
        return jsonify({"done": True, "status": _col(run, "status") if run else "missing",
                        "counters": _run_counters(run) if run else {}})

    storage = Storage(leads_db_path(_col(run, "source") or "agent"),
                      campaign=_col(run, "source") or "agent")
    try:
        result = pipeline.scan_chunk(
            config, storage,
            terms=(pipeline.parse_prompt(_col(run, "query"))["terms"]
                   or pipeline.split_query(_col(run, "query"))),
            city=_col(run, "city") or "jerusalem",
            target_emails=run["target"] or 50,
            campaign=_col(run, "source") or "agent",
            min_reviews=run["min_reviews"], min_rating=run["min_rating"],
            cursor=(run["nb_index"], run["term_index"], run["place_index"]),
            counters=_run_counters(run) or pipeline.new_counters(),
            # המנה הראשונה קצרה, כדי שהעמוד יראה סימן חיים תוך שניות
            # ולא ייראה תקוע. אחריה עוברים לתקציב המלא.
            budget_seconds=(8.0 if not _run_counters(run).get("נסרקו")
                            else SCAN_BUDGET_SECONDS),
            run_id=str(run["id"]))
    except Exception as exc:  # noqa: BLE001 — מדווחים לדפדפן ולא מפילים
        logger.exception("מנת סריקה נכשלה")
        store.save_run(run["id"], (run["nb_index"], run["term_index"],
                                   run["place_index"]), _run_counters(run),
                       run["progress"] or 0, "failed", str(exc)[:300])
        return jsonify({"done": True, "status": "failed", "error": str(exc)[:300],
                        "counters": _run_counters(run)}), 200

    status = "done" if result["done"] else "running"
    store.save_run(run["id"], result["cursor"], result["counters"],
                   result["progress"], status, result["message"])
    return jsonify({"done": result["done"], "status": status,
                    "counters": result["counters"],
                    "progress": 100 if result["done"] else result["progress"],
                    "message": result["message"]})


@app.route("/campaign/<int:campaign_id>/scan/stop", methods=["POST"])
def scan_stop(campaign_id):
    run = store.run_of(campaign_id)
    if run:
        store.stop_run(run["id"])
    flash("הסריקה נעצרה. מה שנסרק עד עכשיו נשמר.")
    return redirect(url_for("campaign_edit", campaign_id=campaign_id))


def _ensure_source(campaign) -> str:
    """מאגר הלידים של הקמפיין. לקמפיין חדש בלי מאגר נפתח אחד משלו."""
    source = _col(campaign, "source_campaign")
    if not source:
        source = f"c{campaign['id']}"
        store.update(campaign["id"], source_campaign=source)
        _STORES.pop(source, None)
    return source


@app.route("/campaign/<int:campaign_id>/add")
def add_recipients_page(campaign_id):
    """עמוד הוספת נמענים: העלאת קובץ מהדפדפן, וכתובת בדיקה."""
    campaign = store.get(campaign_id)
    if not campaign:
        return redirect(url_for("board"))
    st = leads_store(_col(campaign, "source_campaign"))
    try:
        counts = st.state_counts() if st else {}
    except Exception:  # noqa: BLE001
        counts = {}
    return render_template("add_recipients.html", campaign=campaign, counts=counts,
                           columns=importer.COLUMNS)


@app.route("/campaign/<int:campaign_id>/upload", methods=["POST"])
def campaign_upload(campaign_id):
    """
    העלאת קובץ נמענים (CSV או Excel). כל כתובת עוברת את הבדיקות של
    egud_bot.importer לפני שהיא נכנסת, ומה שלא נכנס מוצג עם הסיבה.
    """
    campaign = store.get(campaign_id)
    if not campaign:
        return redirect(url_for("board"))
    upload = request.files.get("contacts")
    if not upload or not upload.filename:
        flash("צריך לבחור קובץ")
        return redirect(url_for("add_recipients_page", campaign_id=campaign_id))
    try:
        rows = importer.read_table(upload.filename, upload.stream.read())
    except ValueError as exc:
        flash(str(exc))
        return redirect(url_for("add_recipients_page", campaign_id=campaign_id))
    if not rows:
        flash("לא מצאתי שורות בקובץ")
        return redirect(url_for("add_recipients_page", campaign_id=campaign_id))
    if "email" not in importer.map_columns(list(rows[0].keys())):
        flash("לא מצאתי עמודת מייל בקובץ. צריכה להיות עמודה בשם 'מייל' או 'email'.")
        return redirect(url_for("add_recipients_page", campaign_id=campaign_id))

    result = _run_import(campaign, rows, (request.form.get("group") or "").strip(), "upload")
    groups = {}
    for item in result["added"]:
        groups[item["group"] or "ללא קבוצה"] = groups.get(item["group"] or "ללא קבוצה", 0) + 1
    return render_template("import_result.html", campaign=store.get(campaign_id),
                           filename=upload.filename, total=len(rows),
                           added=result["added"], skipped=result["skipped"],
                           reasons=result["reasons"],
                           groups=sorted(groups.items(), key=lambda kv: -kv[1]),
                           columns=result["columns"])


@app.route("/campaign/<int:campaign_id>/add_test", methods=["POST"])
def add_test_recipient(campaign_id):
    """כתובת בדיקה: נכנסת תמיד, ולא נספרת בתוצאות."""
    campaign = store.get(campaign_id)
    email = (request.form.get("email") or "").strip()
    if not campaign or "@" not in email:
        flash("צריך כתובת מייל תקינה")
        return redirect(url_for("add_recipients_page", campaign_id=campaign_id))
    source = _ensure_source(campaign)
    storage = Storage(leads_db_path(source), campaign=source)
    importer.add_test_address(storage, email,
                              (request.form.get("business") or "").strip(),
                              (request.form.get("first_name") or "").strip(), source)
    flash(f"נוספה כתובת בדיקה: {email}")
    return redirect(url_for("add_recipients_page", campaign_id=campaign_id))


@app.route("/campaign/<int:campaign_id>/duplicate", methods=["POST"])
def campaign_duplicate(campaign_id):
    """קמפיין חדש עם אותו נוסח, נושא ותיבת שליחה, ובלי נמענים."""
    src = store.get(campaign_id)
    if not src:
        return redirect(url_for("board"))
    title = (request.form.get("title") or "").strip() or f"{src['title']} (עותק)"
    cid = store.create(title, kind=_col(src, "kind") or "email")
    store.update(cid, source_campaign=f"c{cid}",
                 subject_tpl=_col(src, "subject_tpl"), body_tpl=_col(src, "body_tpl"),
                 sender_id=_col(src, "sender_id"), client_id=_col(src, "client_id") or "")
    for name, f in store.fields(campaign_id).items():
        if name in ("נוסח", "כאב", "הנעה לפעולה", "תיבת שליחה", "נושא המייל") and f["value"]:
            store.set_field(cid, name, value=f["value"])
    flash("הקמפיין שוכפל. עכשיו מוסיפים לו נמענים.")
    return redirect(url_for("add_recipients_page", campaign_id=cid))


@app.route("/campaign/<int:campaign_id>/recipients")
def recipients_page(campaign_id):
    """
    מי בדיוק נמצא במאגר, ולמה. "ממתינים לשליחה" קטן מ"עם כתובת מייל"
    כי מי שכבר נשלח אליו, מי ששויך לנוסח, וכתובות כפולות -- יורדים.
    כאן רואים את זה בשמות.
    """
    campaign = store.get(campaign_id)
    st = leads_store(_col(campaign, "source_campaign")) if campaign else None
    if not st:
        flash("לקמפיין הזה אין מאגר לידים מקושר")
        return redirect(url_for("campaign_edit", campaign_id=campaign_id))

    state = request.args.get("state", "pending")
    if state not in Storage.STATES:
        state = "pending"
    return render_template("recipients.html", campaign=campaign, state=state,
                           counts=st.state_counts(),
                           leads=st.leads_by_state(state, 500),
                           states=Storage.STATES)


@app.route("/campaign/<int:campaign_id>/cleanup", methods=["GET", "POST"])
def cleanup_page(campaign_id):
    """
    ניקוי לידים שאינם מהתחום שהקמפיין מחפש.

    מאגר הלידים מצטבר: כל סריקה מוסיפה אליו ושום דבר לא יורד ממנו. לכן
    אחרי שהוספנו סינון התאמה, המאגר עדיין מכיל תוצאות ישנות שנסרקו לפניו
    -- משרדי תיווך ברשימת עורכי דין וכדומה. כאן רואים אותן לפני שמוחקים.
    """
    campaign = store.get(campaign_id)
    st = leads_store(_col(campaign, "source_campaign")) if campaign else None
    if not st:
        flash("לקמפיין הזה אין מאגר לידים מקושר")
        return redirect(url_for("campaign_edit", campaign_id=campaign_id))

    family = filters.family_of_query(_col(campaign, "search_query"))
    if not family:
        flash("התחום של הקמפיין אינו אחד מהתחומים המזוהים, ולכן אין לפי מה לנקות")
        return redirect(url_for("campaign_edit", campaign_id=campaign_id))

    leads = st.all_leads()
    stray = [lead for lead in leads if not filters.matches_query(
        filters.BusinessLead.from_row(lead), family)]

    if request.method == "POST":
        keep = set(request.form.getlist("keep"))
        doomed = [lead["place_id"] for lead in stray if lead["place_id"] not in keep]
        removed = st.delete_leads(doomed)
        flash(f"הוסרו {removed} לידים שאינם מהתחום")
        return redirect(url_for("campaign_edit", campaign_id=campaign_id))

    return render_template("cleanup.html", campaign=campaign, stray=stray,
                           total=len(leads), family=family)


@app.route("/campaign/<int:campaign_id>/phones")
def phones_page(campaign_id):
    """רשימת טלפונים — למי שאין לו מייל, או לכל הקמפיין."""
    campaign = store.get(campaign_id)
    st = leads_store(_col(campaign, "source_campaign"))
    leads = st.leads_with_phone() if st else []
    return render_template("phones.html", campaign=campaign, leads=leads)


@app.route("/campaign/<int:campaign_id>/phones.csv")
def phones_csv(campaign_id):
    import csv
    campaign = store.get(campaign_id)
    st = leads_store(_col(campaign, "source_campaign"))
    leads = st.leads_with_phone() if st else []
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["שם", "טלפון", "אזור", "ביקורות", "דירוג", "מייל"])
    for lead in leads:
        writer.writerow([lead["name"], lead["phone"], lead["neighborhood"],
                         lead["review_count"], lead["rating"] or "",
                         lead["email"] or ""])
    data = "\ufeff" + buf.getvalue()      # BOM כדי שאקסל יציג עברית נכון
    return Response(data, mimetype="text/csv", headers={
        "Content-Disposition": f'attachment; filename="phones-{campaign_id}.csv"'})


# ---------------------------- תיבות שליחה ----------------------------
@app.route("/senders", methods=["GET", "POST"])
def senders_page():
    """תיבות השליחה שלנו, או של לקוח (?client=)."""
    boxes = sender_box.SenderStore()
    client_id = (request.values.get("client") or "").strip()
    client = client_store().get(client_id) if client_id.isdigit() else None
    back = url_for("senders_page", client=client["id"]) if client else url_for("senders_page")
    if request.method == "POST":
        if not (request.form.get("from_email") or "").strip():
            flash("חסרה כתובת מייל")
            return redirect(back)
        existing = boxes.get(request.form.get("id"))
        if existing and sender_box.owner_of(existing) != (str(client["id"]) if client else ""):
            flash("התיבה הזו שייכת לתיקייה אחרת")
            return redirect(back)
        data = request.form.to_dict()
        data["client_id"] = str(client["id"]) if client else ""
        boxes.save(request.form.get("id") or None, **data)
        flash("התיבה נשמרה")
        return redirect(back)
    edit = boxes.get(request.args.get("edit"))
    if edit and sender_box.owner_of(edit) != (str(client["id"]) if client else ""):
        edit = None
    return render_template("senders.html", senders=boxes.for_client(client["id"] if client else None),
                           edit=edit, client=client)


def _box_back(sender_id):
    owner = sender_box.owner_of(sender_box.SenderStore().get(sender_id))
    return url_for("senders_page", client=owner) if owner else url_for("senders_page")


@app.route("/senders/<int:sender_id>/delete", methods=["POST"])
def sender_delete(sender_id):
    back = _box_back(sender_id)
    sender_box.SenderStore().delete(sender_id)
    flash("התיבה נמחקה")
    return redirect(back)


@app.route("/senders/<int:sender_id>/test", methods=["POST"])
def sender_test(sender_id):
    """בודק שאפשר להתחבר לתיבה, בלי לשלוח כלום."""
    from egud_bot.mailer import Mailer
    back = _box_back(sender_id)
    sender = sender_box.as_smtp(sender_box.SenderStore().get(sender_id))
    if not sender:
        return redirect(back)
    try:
        with Mailer(host=sender["smtp_host"], port=sender["smtp_port"],
                    user=sender["smtp_user"], password=sender["smtp_password"],
                    from_email=sender["from_email"], use_ssl=sender["use_ssl"]):
            pass
        flash(f"החיבור ל-{sender['from_email']} עובד")
    except Exception as exc:  # noqa: BLE001
        flash(f"החיבור ל-{sender['from_email']} נכשל: {exc}")
    return redirect(back)


# ---------------------------- גיבוי ושחזור ----------------------------
def _data_files() -> list:
    """קובצי הנתונים: מאגרי הלידים, הקמפיינים, ויומני השליחה."""
    if not os.path.isdir(config.data_dir):
        return []
    return sorted(f for f in os.listdir(config.data_dir)
                  if f.endswith(".db") or f.startswith("sent_"))


@app.route("/backup")
def backup_page():
    files = [(f, os.path.getsize(os.path.join(config.data_dir, f)))
             for f in _data_files()]
    return render_template("backup.html", files=files, data_dir=config.data_dir,
                           on_d1=db.d1_configured())


@app.route("/backup/download")
def backup_download():
    """מוריד את כל הנתונים כקובץ zip אחד."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in _data_files():
            z.write(os.path.join(config.data_dir, name), name)
    buf.seek(0)
    stamp = datetime.now().strftime("%Y-%m-%d")
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"sy-nero-data-{stamp}.zip")


@app.route("/backup/upload", methods=["POST"])
def backup_upload():
    """
    משחזר נתונים מקובץ zip. כך מעבירים את המאגר מהמחשב לענן: מורידים
    גיבוי מהמחשב, ומעלים אותו כאן. קבצים קיימים נדרסים.
    """
    upload = request.files.get("archive")
    if not upload or not upload.filename.endswith(".zip"):
        flash("צריך לבחור קובץ zip")
        return redirect(url_for("backup_page"))

    os.makedirs(config.data_dir, exist_ok=True)
    restored = 0
    with zipfile.ZipFile(upload.stream) as z:
        for info in z.infolist():
            name = os.path.basename(info.filename)
            # רק קובצי נתונים, ורק בשם קובץ נקי — בלי נתיבים מהארכיון
            if info.is_dir() or not name:
                continue
            if not (name.endswith(".db") or name.startswith("sent_")):
                continue
            with z.open(info) as src, \
                    open(os.path.join(config.data_dir, name), "wb") as dst:
                dst.write(src.read())
            restored += 1
    flash(f"שוחזרו {restored} קבצים")
    return redirect(url_for("board"))



@app.route("/health")
def health():
    """
    בדיקת חיים — חייבת להיות זולה ומיידית.

    היא משמשת את בדיקת התקינות של Render, ולכן אסור לה לגעת באחסון: עם
    הגדרות D1 שגויות כל שאילתה ממתינה עד 30 שניות לתשובה מ-Cloudflare,
    בדיקת התקינות נכשלת בטיים-אאוט, ו-Render מפסיק לנתב תעבורה לשירות —
    כלומר הכתובת פשוט לא נפתחת. בדיקת האחסון עברה ל-/status.
    """
    return {"status": "ok", "tracking": bool(config.tracking_base_url),
            "storage": "d1" if db.d1_configured() else "local",
            "password": bool(config.app_password), "version": APP_VERSION}


@app.route("/status")
def status():
    """בדיקה מעמיקה — נוגעת באחסון, ולכן עלולה להיות איטית. לא לבדיקת תקינות."""
    info = {"storage": "d1" if db.d1_configured() else "local",
            "password": bool(config.app_password)}
    try:
        info["campaigns"] = len(store.all())
        info["storage_ok"] = True
    except Exception as exc:  # noqa: BLE001 — זה בדיוק מה שהבדיקה מדווחת
        info.update(storage_ok=False, storage_error=str(exc)[:300])
    return info


if __name__ == "__main__":
    # מאזינים רק למחשב עצמו. הרצה על 0.0.0.0 חושפת את הלוח -- ואיתו את כל
    # רשימת הלידים -- לכל מי שנמצא באותה רשת, למשל wifi של בית קפה, ובלי
    # סיסמה. מי שכן צריך גישה מבחוץ יגדיר APP_HOST=0.0.0.0 במודע.
    app.run(host=os.getenv("APP_HOST", "127.0.0.1"),
            port=config.app_port, debug=False)
