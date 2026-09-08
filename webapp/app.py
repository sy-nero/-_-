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
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import (Flask, request, render_template, redirect,  # noqa: E402
                   url_for, Response, flash)

from config import config  # noqa: E402
from egud_bot import pipeline, templates as mail_templates, tracking  # noqa: E402
from egud_bot.campaigns import (CampaignStore, TEXT_FIELDS, AUTO_FIELDS,  # noqa: E402
                                MANUAL_FIELDS, ALL_FIELDS)
from egud_bot.storage import Storage  # noqa: E402

app = Flask(__name__)
app.secret_key = config.flask_secret_key
store = CampaignStore()

# מיפוי שם הקמפיין ב-DB הלידים -> נתיב הקובץ
def leads_db_path(source_campaign: str) -> str:
    if not source_campaign:
        return ""
    return (config.db_path if source_campaign == "funding"
            else f"data/leads_{source_campaign}.db")


def leads_store(source_campaign: str):
    path = leads_db_path(source_campaign)
    if not path or not os.path.exists(path):
        return None
    return Storage(path, campaign=source_campaign)


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


def campaign_view(campaign) -> dict:
    """כל מה שצריך להצגת עמודת קמפיין בלוח."""
    fields = store.fields(campaign["id"])
    metrics = auto_metrics(campaign)
    fields["כמות פניות"]["value"] = str(metrics["sent"])
    fields["כמות פתיחות"]["value"] = str(metrics["opened"])
    fields["הודעה חוזרת"]["value"] = str(metrics["replied"])
    open_rate = (f"{metrics['opened'] * 100 // metrics['sent']}%"
                 if metrics["sent"] else "—")
    reply_rate = (f"{metrics['replied'] * 100 // metrics['sent']}%"
                  if metrics["sent"] else "—")
    return {"campaign": campaign, "fields": fields, "metrics": metrics,
            "open_rate": open_rate, "reply_rate": reply_rate}


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
                     variant=(request.form.get("variant") or "").strip())
        for field in ALL_FIELDS:
            if field in AUTO_FIELDS:      # נמדד אוטומטית — לא נערך ביד
                continue
            store.set_field(
                campaign_id, field,
                value=request.form.get(f"value::{field}", ""),
                note=request.form.get(f"note::{field}", ""),
                improve=request.form.get(f"improve::{field}", ""))
        flash("נשמר")
        return redirect(url_for("campaign_edit", campaign_id=campaign_id))

    view = campaign_view(campaign)
    return render_template("campaign.html", **view, text_fields=TEXT_FIELDS,
                           auto_fields=AUTO_FIELDS, manual_fields=MANUAL_FIELDS)


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

    limit = int(request.args.get("limit", 10))
    pending = st.leads_to_email(limit)
    previews = []
    for lead in pending:
        template_campaign = (f"{campaign['source_campaign']}_offer"
                             if campaign["variant"] == "b"
                             else campaign["source_campaign"])
        subject, _html, text = mail_templates.render(
            template_campaign,
            **pipeline.build_ctx(config, campaign["source_campaign"], lead))
        previews.append({"lead": lead, "subject": subject, "text": text})

    return render_template("send.html", campaign=campaign, previews=previews,
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
        limit=len(chosen), variant=campaign["variant"] or "", only=chosen)
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


@app.route("/health")
def health():
    return {"status": "ok", "tracking": bool(config.tracking_base_url)}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.app_port, debug=False)
