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
from egud_bot.storage import Storage  # noqa: E402

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
    return render_template("dberror.html", error=str(exc)), 500


# ---------------------------- הגנה בסיסמה ----------------------------
# האפליקציה מציגה לידים ושולחת מיילים בשם החברה, ולכן היא לא נשארת פתוחה
# לכל מי שמגיע לכתובת. הפיקסל ובדיקת הבריאות נשארים ציבוריים בכוונה:
# הפיקסל נטען מתוכנת המייל של הנמען, שאין לה סשן.
PUBLIC_ENDPOINTS = {"pixel", "health", "login", "static"}


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


def auto_metrics(campaign) -> dict:
    """נשלחו / נפתחו / השיבו — נמדדים מ-DB הלידים, לא מוזנים ביד."""
    empty = {"sent": 0, "opened": 0, "replied": 0}
    st = leads_store(campaign["source_campaign"])
    if not st:
        return empty
    try:
        return st.variant_metrics(campaign["variant"] or "")
    except Exception:  # noqa: BLE001 — DB ישן בלי עמודות המעקב
        return empty


AUTO_TO_METRIC = {"כמות פניות": "sent", "כמות פתיחות": "opened",
                  "הודעה חוזרת": "replied"}


def _as_int(text) -> int | None:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return None


def custom_of(campaign):
    """הנוסח המותאם של הקמפיין, אם נכתב לו כזה."""
    subject = _col(campaign, "subject_tpl")
    body = _col(campaign, "body_tpl")
    query = _col(campaign, "search_query")
    return (subject, body, query) if (subject or body) else None


def _col(row, name: str) -> str:
    try:
        return (row[name] or "").strip()
    except (IndexError, KeyError, TypeError):
        return ""


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

    st = leads_store(campaign["source_campaign"])
    try:
        pending = st.pending_count() if st else 0
    except Exception:  # noqa: BLE001 — מאגר ישן/לא נגיש לא מפיל את הלוח
        pending = 0

    return {"campaign": campaign, "fields": fields, "metrics": metrics,
            "open_rate": f"{open_pct}%" if metrics["sent"] else "—",
            "reply_rate": f"{reply_pct}%" if metrics["sent"] else "—",
            "open_pct": open_pct, "reply_pct": reply_pct, "pending": pending}


# ---------------------------- הלוח ----------------------------
@app.route("/")
def board():
    columns = [campaign_view(c) for c in store.all()]
    return render_template("board.html", columns=columns,
                           text_fields=TEXT_FIELDS, auto_fields=AUTO_FIELDS,
                           manual_fields=MANUAL_FIELDS,
                           tracking_on=bool(config.tracking_base_url))


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
    return redirect(url_for("campaign_edit", campaign_id=cid))


@app.route("/campaign/<int:campaign_id>", methods=["GET", "POST"])
def campaign_edit(campaign_id):
    campaign = store.get(campaign_id)
    if not campaign:
        return redirect(url_for("board"))

    if request.method == "POST":
        store.update(campaign_id,
                     title=(request.form.get("title") or "").strip(),
                     kind=request.form.get("kind", "email"),
                     started_on=(request.form.get("started_on") or "").strip(),
                     source_campaign=(request.form.get("source_campaign") or "").strip(),
                     variant=(request.form.get("variant") or "").strip(),
                     search_query=(request.form.get("search_query") or "").strip(),
                     subject_tpl=(request.form.get("subject_tpl") or "").strip(),
                     body_tpl=(request.form.get("body_tpl") or "").strip())
        for field in ALL_FIELDS:
            store.set_field(
                campaign_id, field,
                value=request.form.get(f"value::{field}", ""),
                note=request.form.get(f"note::{field}", ""),
                improve=request.form.get(f"improve::{field}", ""))
        flash("נשמר")
        # חוזרים ישר לבלוק הסריקה — זה הצעד הבא אחרי שמירת ההגדרות
        return redirect(url_for("campaign_edit", campaign_id=campaign_id,
                                saved=1) + "#scan")

    view = campaign_view(campaign)
    pool = pool_of(campaign)
    return render_template("campaign.html", **view, text_fields=TEXT_FIELDS,
                           auto_fields=AUTO_FIELDS, manual_fields=MANUAL_FIELDS,
                           cities=CITIES, pool=pool[0], pool_error=pool[1],
                           min_reviews=config.agent_min_reviews,
                           min_rating=config.agent_min_rating,
                           terms=pipeline.split_query(_col(campaign, "search_query")),
                           just_saved=bool(request.args.get("saved")),
                           busy=runner.busy, run=store.run_of(campaign_id),
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

    limit = int(request.args.get("limit", 50))
    pending = st.leads_to_email(limit)
    previews = []
    for lead in pending:
        template_campaign = (f"{campaign['source_campaign']}_offer"
                             if campaign["variant"] == "b"
                             else campaign["source_campaign"])
        subject, _html, text = pipeline._render(
            template_campaign,
            pipeline.build_ctx(config, campaign["source_campaign"], lead),
            custom_of(campaign))
        previews.append({"lead": lead, "subject": subject, "text": text})

    return render_template("send.html", campaign=campaign, previews=previews,
                           sample=previews[0] if previews else None,
                           sent=st.sent_leads(campaign["variant"] or "", 200),
                           tracking_on=bool(config.tracking_base_url))


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

    errors = config.validate_for_email(campaign["source_campaign"])
    if errors:
        flash("חסרות הגדרות שליחה: " + ", ".join(errors))
        return redirect(url_for("send_page", campaign_id=campaign_id))

    summary = pipeline.send_emails(
        config, st, campaign=campaign["source_campaign"],
        limit=len(chosen), variant=campaign["variant"] or "", only=chosen,
        custom=custom_of(campaign))
    flash(f"נשלחו {summary.get('sent', 0)} מיילים")
    return redirect(url_for("send_page", campaign_id=campaign_id))


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

    min_reviews = _as_int(request.form.get("min_reviews"))
    if min_reviews is None:
        min_reviews = config.agent_min_reviews
    try:
        min_rating = float(request.form.get("min_rating") or config.agent_min_rating)
    except ValueError:
        min_rating = config.agent_min_rating

    store.start_run(campaign_id, source=source, query=query,
                    city=request.form.get("city") or "jerusalem",
                    target=max(1, min(_as_int(request.form.get("target")) or 50, 500)),
                    min_reviews=max(0, min(min_reviews, 100)),
                    min_rating=max(0.0, min(min_rating, 5.0)))
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
                           terms=pipeline.split_query(_col(run, "query")))


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
            terms=pipeline.split_query(_col(run, "query")),
            city=_col(run, "city") or "jerusalem",
            target_emails=run["target"] or 50,
            campaign=_col(run, "source") or "agent",
            min_reviews=run["min_reviews"], min_rating=run["min_rating"],
            cursor=(run["nb_index"], run["term_index"], run["place_index"]),
            counters=_run_counters(run) or pipeline.new_counters(),
            budget_seconds=SCAN_BUDGET_SECONDS)
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


@app.route("/campaign/<int:campaign_id>/upload", methods=["POST"])
def campaign_upload(campaign_id):
    """
    העלאת קובץ אנשי קשר (CSV) לקמפיין. עמודות מזוהות: name/שם,
    email/מייל, phone/טלפון, first_name, city/עיר.
    """
    import csv
    from egud_bot.jobscan import import_rows

    campaign = store.get(campaign_id)
    source = _col(campaign, "source_campaign") or "agent"
    upload = request.files.get("contacts")
    if not upload or not upload.filename:
        flash("צריך לבחור קובץ")
        return redirect(url_for("campaign_edit", campaign_id=campaign_id))
    if not upload.filename.lower().endswith(".csv"):
        flash("כרגע נתמך CSV בלבד. באקסל: קובץ → שמירה בשם → CSV UTF-8")
        return redirect(url_for("campaign_edit", campaign_id=campaign_id))

    text = upload.stream.read().decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    storage = Storage(leads_db_path(source), campaign=source)
    summary = import_rows(storage, rows, prefix=f"c{campaign_id}")
    flash("ייבוא: " + " · ".join(f"{k} {v}" for k, v in summary.items()))
    return redirect(url_for("campaign_edit", campaign_id=campaign_id))


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
            "password": bool(config.app_password)}


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
