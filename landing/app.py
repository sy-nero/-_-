#!/usr/bin/env python3
"""
דף נחיתה להרשמה — Flask.

הרצה:
    python landing/app.py
ואז גלישה אל http://localhost:5000

הטופס נשמר לאותו DB (registrations) שאליו המייל מפנה עם פרמטר ref.
"""
import os
import sys

# מאפשר ייבוא של config ו-egud_bot מהשורש
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, request, render_template, redirect, url_for  # noqa: E402
from config import config  # noqa: E402
from egud_bot.storage import Storage  # noqa: E402

app = Flask(__name__)
app.secret_key = config.flask_secret_key
storage = Storage(config.db_path)


@app.route("/", methods=["GET"])
@app.route("/register", methods=["GET"])
def index():
    ref = request.args.get("ref", "")
    return render_template(
        "index.html",
        ref=ref,
        association_name=config.association_name,
    )


@app.route("/register", methods=["POST"])
def register():
    full_name = (request.form.get("full_name") or "").strip()
    phone = (request.form.get("phone") or "").strip()

    # ולידציה בסיסית — שם וטלפון חובה
    if not full_name or not phone:
        return render_template(
            "index.html",
            ref=request.form.get("ref", ""),
            association_name=config.association_name,
            error="נא למלא לפחות שם וטלפון.",
        ), 400

    storage.add_registration({
        "ref": request.form.get("ref", ""),
        "full_name": full_name,
        "business": (request.form.get("business") or "").strip(),
        "phone": phone,
        "email": (request.form.get("email") or "").strip(),
        "message": (request.form.get("message") or "").strip(),
        "callback": request.form.get("callback") == "on",
    })
    return redirect(url_for("thanks"))


@app.route("/thanks", methods=["GET"])
def thanks():
    return render_template("thanks.html", association_name=config.association_name)


@app.route("/health", methods=["GET"])
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.landing_port, debug=False)
