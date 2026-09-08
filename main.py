#!/usr/bin/env python3
"""
בוט האיגוד — כלי CLI.

שימוש:
    python main.py scan            # סריקה + איתור מיילים + שמירה ב-DB
    python main.py send            # שליחת מיילים ללידים שנמצאו
    python main.py send --dry-run  # הרצת שליחה יבשה (בלי לשלוח בפועל)
    python main.py run             # scan ואז send ברצף
    python main.py stats           # הצגת סטטיסטיקות מה-DB
    python main.py export leads.csv  # ייצוא כל הלידים ל-CSV
    python main.py preview --campaign agent   # תצוגת נוסח המייל
"""
import sys
import csv
import logging
import argparse
import sqlite3

from config import config
from egud_bot.storage import Storage
from egud_bot import pipeline


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _campaign(args) -> str:
    return getattr(args, "campaign", "funding") or "funding"


def _storage(args) -> Storage:
    c = _campaign(args)
    path = config.db_path if c == "funding" else f"data/leads_{c}.db"
    # שני הנוסחים חולקים יומן שליחות אחד, כדי שאיש לא יקבל את שניהם
    return Storage(path, campaign=c)


def cmd_scan(args) -> int:
    errors = config.validate_for_scan()
    if errors:
        print("שגיאות קונפיגורציה:\n  - " + "\n  - ".join(errors))
        return 1
    storage = _storage(args)
    summary = pipeline.scan(config, storage, campaign=_campaign(args),
                            city=getattr(args, "city", "jerusalem"),
                            target_emails=getattr(args, "target", None))
    print("\n=== סיכום סריקה ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    return 0


def _ask_before_send(lead, subject, text, index, total, rec=None) -> str:
    """מדפיס את המייל המלא בטרמינל ושואל אם לשלוח אותו."""
    print("\n" + "=" * 72)
    print(f"מייל {index} מתוך {total}")
    print(f"אל:    {lead['name']} <{lead['email']}>")
    print(f"נושא:  {subject}")
    print("-" * 72)
    print(text)
    if rec and rec.get("count"):
        print(f"[{rec['count']} ביקורות בגוגל, דירוג {rec.get('rating') or '—'}]")
    print("-" * 72)
    while True:
        try:
            answer = input(
            "לשלוח את המייל הזה? [y=כן / n=דלג / q=ביטול מלא, בלי לשלוח כלום]: "
        ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            # אין קלט (הרצה לא אינטראקטיבית) או Ctrl-C — עוצרים ולא שולחים
            print("\n  → הופסק. לא נשלח אף מייל.")
            return "quit"
        if answer in ("y", "yes", "כן", "כ"):
            return "yes"
        if answer in ("n", "no", "לא", "ל"):
            print("  → מדלג. הליד נשאר ב-DB וניתן לשלוח אליו בהרצה אחרת.")
            return "no"
        if answer in ("q", "quit", "עצור", "ע", "ביטול", "ב"):
            print("  → מבטל את ההרצה כולה. לא יישלח אף מייל, גם לא כאלה שאושרו קודם.")
            return "quit"
        print("  תשובה לא ברורה. הקלד y / n / q.")


def _confirm_batch(leads) -> bool:
    """אישור אחרון על הרשימה כולה, רגע לפני שנפתח חיבור SMTP ונשלח."""
    print("\n" + "=" * 72)
    print(f"אישרת {len(leads)} מיילים. אלה הנמענים:")
    for lead in leads:
        print(f"  • {lead['name']} <{lead['email']}>")
    print("=" * 72)
    try:
        answer = input("לשלוח אותם עכשיו? [y=שלח / כל תשובה אחרת מבטלת]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  → בוטל. לא נשלח דבר.")
        return False
    if answer in ("y", "yes", "כן", "כ"):
        return True
    print("  → בוטל. לא נשלח דבר.")
    return False


def cmd_send(args) -> int:
    if not args.dry_run:
        errors = config.validate_for_email(_campaign(args))
        if errors:
            print("שגיאות קונפיגורציה:\n  - " + "\n  - ".join(errors))
            return 1
    storage = _storage(args)
    confirm = _ask_before_send if getattr(args, "confirm", False) else None
    if confirm and not args.dry_run:
        print("\nכל מייל יוצג כאן לפני השליחה. נשלחים רק המיילים שתאשר.")
    summary = pipeline.send_emails(config, storage, dry_run=args.dry_run,
                                   campaign=_campaign(args),
                                   skip_contacted=getattr(args, "skip_contacted", False),
                                   limit=getattr(args, "limit", None),
                                   confirm=confirm,
                                   confirm_batch=_confirm_batch if confirm else None,
                                   variant=getattr(args, "variant", "") or "")
    print("\n=== סיכום שליחה ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    return 0


def cmd_run(args) -> int:
    rc = cmd_scan(args)
    if rc != 0:
        return rc
    return cmd_send(args)


def cmd_clean(args) -> int:
    storage = _storage(args)
    removed = storage.purge_non_business()
    print(f"\nהוסרו {len(removed)} מוסדות (לא עסקים):")
    for name in removed:
        print(f"  - {name}")
    if not removed:
        print("  (אין מה להסיר, הרשימה נקייה)")
    return 0


def cmd_import(args) -> int:
    from egud_bot import jobscan
    storage = _storage(args)
    added = jobscan.import_csv(storage, args.path)
    print(f"יובאו {added} עסקים מ-{args.path}")
    return 0


def cmd_jobdebug(args) -> int:
    from egud_bot import jobscan
    jobscan.debug_drushim(args.url)
    return 0


def _preview_rec(args) -> str:
    """בונה המלצה לדוגמה לתצוגה, כולל זיהוי הסימנים כמו בסריקה אמיתית."""
    if not (args.rec_quote or args.rec_count):
        return ""
    import json
    from egud_bot import recommendations
    rec = recommendations.Recommendation(
        source=args.rec_source,
        quote=args.rec_quote,
        count=args.rec_count,
        rating=args.rec_rating,
        signals=recommendations.detect_signals([args.rec_quote], args.rec_count),
    )
    return json.dumps(rec.as_dict(), ensure_ascii=False)


def cmd_preview(args) -> int:
    """מדפיס את נוסח המייל של הקמפיין (בלי DB ובלי שליחה) — לבדיקת הנוסח."""
    from egud_bot import templates
    campaign = _campaign(args)
    lead = {
        "name": args.name,
        "place_id": "preview",
        "primary_type": args.type,
        "neighborhood": args.neighborhood,
        "first_name": args.first_name,
        "intro_how": args.how,
        "intro_fact": args.fact,
        "intro_why": args.why,
        "rec_json": _preview_rec(args),
    }
    # בקמפיין הסוכנים אפשר לראות כל אחד משני הנוסחים
    template_campaign = (f"{campaign}_offer"
                         if getattr(args, "variant", None) == "b" else campaign)
    subject, html, text = templates.render(
        template_campaign, **pipeline.build_ctx(config, campaign, lead))
    if args.html:
        print(html)
        return 0
    if not args.whatsapp:          # בוואטסאפ אין שורת נושא
        print(f"נושא: {subject}\n")
    print(text)
    return 0


def cmd_check(args) -> int:
    """בודק מה מוגדר ומה חסר כדי להריץ — בלי להדפיס סיסמאות או מפתחות."""
    import os
    campaign = _campaign(args)
    from_email, from_name, smtp_user, smtp_password = config.sender_for(campaign)

    print(f"\n=== בדיקת הגדרות (קמפיין {campaign}) ===")
    print(f"  קובץ .env: {'נמצא' if os.path.exists('.env') else 'לא קיים'}")

    checks = [
        ("מפתח Google Places (לסריקה)", bool(config.google_api_key)),
        ("שרת SMTP (לשליחה)", bool(config.smtp_host)),
        ("משתמש SMTP", bool(smtp_user)),
        ("סיסמת SMTP", bool(smtp_password)),
        ("כתובת השולח", bool(from_email)),
    ]
    for label, ok in checks:
        print(f"  [{'✓' if ok else '✗'}] {label}")
    print(f"\n  המייל ייצא בשם: {from_name} <{from_email or 'לא מוגדר'}>")
    print(f"  החשבון שמתחבר ושולח בפועל (SMTP): {smtp_user or 'לא מוגדר'}")
    print(f"  שרת: {config.smtp_host or 'לא מוגדר'}:{config.smtp_port}")
    if smtp_user and from_email and smtp_user.lower() != from_email.lower():
        print("  שימו לב: הכתובת שממנה נשלח שונה מהחשבון שמתחבר — עותק המייל "
              "יישמר בתיבת ה'נשלחו' של החשבון שמתחבר.")
    if campaign == "agent":
        print(f"  טלפון בחתימה: {config.agent_sender_phone}")
        print(f"  ותק מינימלי לסוכן: {config.agent_min_reviews} ביקורות")

    # בדיקת חיבור מאובטח: תקלת תעודות במחשב מפילה כל בקשה עוד לפני Google
    print("\n  חיבור מאובטח (SSL) לשרתי Google:")
    try:
        import requests
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
            timeout=15)          # בלי מפתח — רק בדיקה שהחיבור עצמו נסגר
        print(f"  [✓] תקין (השרת ענה {resp.status_code})")
    except Exception as exc:     # noqa: BLE001
        print(f"  [✗] {type(exc).__name__}")
        try:
            import certifi
            path = certifi.where()
            size = os.path.getsize(path) if os.path.exists(path) else 0
            print(f"      קובץ התעודות: {path} ({size} בייטים)")
        except ImportError:
            print("      certifi לא מותקן")
        print("      תיקון: pip install --upgrade --force-reinstall certifi")
        print("      ואם מדובר בפייתון של Homebrew: brew reinstall ca-certificates")

    if config.tracking_base_url:
        print(f"\n  מעקב פתיחות: פעיל ({config.tracking_base_url})")
    else:
        print("\n  מעקב פתיחות: כבוי (חסר TRACKING_BASE_URL ב-.env)")

    scan_errors = config.validate_for_scan()
    send_errors = config.validate_for_email(campaign)
    print("\n  סריקה: " + ("מוכנה" if not scan_errors else "חסר — " + ", ".join(scan_errors)))
    print("  שליחה: " + ("מוכנה" if not send_errors else "חסר — " + ", ".join(send_errors)))
    if scan_errors or send_errors:
        print("\n  את הערכים החסרים מוסיפים לקובץ .env בתיקיית הפרויקט.")
        print("  רשימת כל המשתנים נמצאת ב-.env.example")
    return 0


VARIANT_NAMES = {"a": "נוסח א׳ (פנייה ראשונה)", "b": "נוסח ב׳ (ההצעה ישירות)"}


def cmd_test(args) -> int:
    """שולח מייל בדיקה אחד לכתובת שלך — לראות איך הוא באמת מגיע."""
    campaign = _campaign(args)
    errors = config.validate_for_email(campaign)
    if errors:
        print("שגיאות קונפיגורציה:\n  - " + "\n  - ".join(errors))
        return 1

    from egud_bot import templates
    from egud_bot.mailer import Mailer
    from_email, from_name, smtp_user, smtp_password = config.sender_for(campaign)
    lead = {
        "name": args.name, "place_id": "test", "primary_type": args.type,
        "neighborhood": args.neighborhood, "first_name": args.first_name,
        "intro_how": "", "intro_fact": "", "intro_why": "",
        "rec_json": _preview_rec(args),
    }
    template_campaign = (f"{campaign}_offer"
                         if getattr(args, "variant", None) == "b" else campaign)
    subject, html, text = templates.render(
        template_campaign, **pipeline.build_ctx(config, campaign, lead))

    print(f"\nשולח מייל בדיקה אחד:")
    print(f"  אל:              {args.to}")
    print(f"  שדה השולח (From): {from_name} <{from_email}>")
    print(f"  מתחבר כ:          {smtp_user}")
    print(f"  שרת:              {config.smtp_host}:{config.smtp_port}\n")
    try:
        with Mailer(host=config.smtp_host, port=config.smtp_port, user=smtp_user,
                    password=smtp_password, from_email=from_email,
                    from_name=from_name, reply_to=from_email,
                    use_ssl=config.smtp_use_ssl, logo_path="") as mailer:
            mailer.send(args.to, subject, html, text)
    except Exception as exc:  # noqa: BLE001
        print(f"השליחה נכשלה: {exc}")
        return 1
    print("נשלח. בדקי בתיבה שלך מאיזו כתובת הוא הגיע בפועל —")
    print("אם היא שונה מ'שדה השולח' למעלה, Gmail שכתב אותה כי הכתובת")
    print("אינה מאומתת אצלו כ'שלח מייל בשם' (Send mail as).")
    return 0


def cmd_enrich(args) -> int:
    """משלים כתובות מייל ללידים שנסרקו בלי אתר."""
    storage = _storage(args)
    summary = pipeline.enrich_missing_emails(config, storage, args.limit)
    print("\n=== סיכום העשרה ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print("\nמי שנמצא לו מייל נכנס אוטומטית לרשימת השליחה.")
    return 0


def cmd_report(args) -> int:
    """משפך הקמפיין והשוואה בין שני הנוסחים."""
    storage = _storage(args)
    print(f"\n=== משפך הקמפיין ({_campaign(args)}) ===")
    for label, value in storage.funnel().items():
        print(f"  {label}: {value}")

    rows = storage.variant_stats()
    print("\n=== השוואת נוסחים ===")
    if not rows:
        print("  עדיין לא נשלח אף נוסח.")
    for row in rows:
        name = VARIANT_NAMES.get(row["variant"], row["variant"])
        rate = f"{row['replied'] * 100 / row['sent']:.0f}%" if row["sent"] else "—"
        print(f"  {name}: נשלחו {row['sent']}, השיבו {row['replied']}  ({rate})")
    if len(rows) == 2 and all(r["sent"] for r in rows):
        best = max(rows, key=lambda r: r["replied"] / r["sent"])
        gap = abs(rows[0]["replied"] / rows[0]["sent"]
                  - rows[1]["replied"] / rows[1]["sent"])
        if gap > 0:
            print(f"\n  מוביל כרגע: {VARIANT_NAMES.get(best['variant'])}")
        total_replies = sum(r["replied"] for r in rows)
        if total_replies < 10:
            print("  (מעט תשובות עדיין — ההפרש בשלב הזה עוד לא מובהק)")

    replies = storage.replies()
    if replies:
        print("\n  מי השיב:")
        for r in replies:
            note = f" — {r['reply_note']}" if r["reply_note"] else ""
            print(f"    • [{r['variant'] or '?'}] {r['name']} <{r['email']}>{note}")
    else:
        print("\n  עדיין לא נרשמה תשובה. לרישום תשובה:")
        print("    python3 main.py replied --campaign agent <מייל> --note <טלפון>")
    return 0


def cmd_replied(args) -> int:
    """רישום ידני של סוכן שהשיב — זה מה שהופך את המשפך למדיד."""
    storage = _storage(args)
    updated = storage.mark_replied(args.email, args.note)
    if updated:
        print(f"נרשם: {args.email} השיב" + (f" ({args.note})" if args.note else ""))
    else:
        print(f"לא נמצא ליד עם הכתובת {args.email} ב-DB של הקמפיין.")
    return 0 if updated else 1


def cmd_stats(args) -> int:
    storage = _storage(args)
    stats = storage.stats()
    print("\n=== סטטוס לידים ב-DB ===")
    if not stats:
        print("  (אין נתונים עדיין)")
    for status, count in stats.items():
        print(f"  {status}: {count}")
    return 0


def cmd_export(args) -> int:
    c = _campaign(args)
    db_path = config.db_path if c == "funding" else f"data/leads_{c}.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM leads ORDER BY found_at").fetchall()
    conn.close()
    if not rows:
        print("אין לידים לייצוא.")
        return 0
    with open(args.path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        for r in rows:
            writer.writerow(dict(r))
    print(f"יוצאו {len(rows)} לידים אל {args.path}")
    return 0


def _add_campaign(sp):
    sp.add_argument("--campaign",
                    choices=["funding", "hr", "crm", "grant", "agent"],
                    default="funding",
                    help="funding=מימון, hr=משאבי אנוש, crm=מערכת CRM, "
                         "grant=מענק מחשוב 4.56, agent=גיוס סוכנים ממליצים")
    return sp


def _add_target(sp):
    sp.add_argument("--target", type=int, default=None,
                    help="כמה מיילים לאסוף לפני שהסריקה נעצרת "
                         "(ברירת מחדל TARGET_EMAILS מ-.env). מקטין זמן ועלות API")
    return sp


def _add_city(sp):
    sp.add_argument(
        "--city",
        choices=["jerusalem", "bnei-brak", "beitar", "modiin-illit", "elad",
                 "beit-shemesh", "ashdod", "other", "all"],
        default="jerusalem",
        help="עיר לסריקה (ברירת מחדל jerusalem). all = כל הערים החרדיות")
    return sp


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="בוט האיגוד — סריקת עסקים ושליחת מיילים")
    p.add_argument("-v", "--verbose", action="store_true", help="לוג מפורט")
    sub = p.add_subparsers(dest="command", required=True)

    _add_target(_add_city(_add_campaign(
        sub.add_parser("scan", help="סריקה + איתור מיילים")))).set_defaults(func=cmd_scan)

    sp = _add_campaign(sub.add_parser("send", help="שליחת מיילים"))
    sp.add_argument("--dry-run", action="store_true", help="בלי לשלוח בפועל")
    sp.add_argument("--skip-contacted", action="store_true",
                    help="דלג על כל מי שקיבל מייל בקמפיין אחר (לא לשלוח פעמיים לאותו עסק)")
    sp.add_argument("--limit", type=int, default=None,
                    help="כמה מיילים לשלוח בהרצה הזאת (למשל 5)")
    sp.add_argument("--confirm", action="store_true",
                    help="להציג כל מייל בטרמינל ולשאול לפני שליחה")
    sp.add_argument("--variant", choices=["a", "b"], default=None,
                    help="בדיקת A/B: a=נוסח הפנייה הראשונה, b=נוסח ההצעה. "
                         "כל נמען מקבל נוסח אחד בלבד")
    sp.set_defaults(func=cmd_send)

    rp = _add_target(_add_city(_add_campaign(sub.add_parser("run", help="scan ואז send"))))
    rp.add_argument("--dry-run", action="store_true", help="בלי לשלוח בפועל")
    rp.set_defaults(func=cmd_run)

    pv = _add_campaign(sub.add_parser("preview", help="תצוגת נוסח המייל של הקמפיין"))
    pv.add_argument("--name", default="", help="שם העסק/הסוכן (לדוגמה בתצוגה)")
    pv.add_argument("--first-name", dest="first_name", default="",
                    help="שם פרטי לפנייה (אחרת נגזר מהשם, ואם לא — 'שלום,')")
    pv.add_argument("--neighborhood", default="", help="שכונה/עיר")
    pv.add_argument("--type", default="", help="סוג העסק ב-Google (למשל accounting)")
    pv.add_argument("--how", default="",
                    help="קמפיין סוכנים: {{איך_הגעתי_אליו}}")
    pv.add_argument("--fact", default="",
                    help="קמפיין סוכנים: {{עובדה_קונקרטית_עליו}}")
    pv.add_argument("--why", default="",
                    help="קמפיין סוכנים: {{למה_דווקא_הוא}} (אחרת נגזר מההמלצות)")
    pv.add_argument("--rec-quote", dest="rec_quote", default="",
                    help="ציטוט המלצה לדוגמה (בסריקה אמיתית נשלף מגוגל/מהאתר)")
    pv.add_argument("--rec-count", dest="rec_count", type=int, default=0,
                    help="מספר ההמלצות בגוגל (לדוגמה)")
    pv.add_argument("--rec-rating", dest="rec_rating", type=float, default=None,
                    help="דירוג בגוגל (לדוגמה)")
    pv.add_argument("--rec-source", dest="rec_source", default="google",
                    choices=["google", "site", "web"],
                    help="מקור ההמלצה לדוגמה")
    pv.add_argument("--variant", choices=["a", "b"], default="a",
                    help="איזה נוסח להציג: a=פנייה ראשונה, b=ההצעה ישירות")
    pv.add_argument("--whatsapp", action="store_true",
                    help="נוסח לוואטסאפ (בלי שורת נושא)")
    pv.add_argument("--html", action="store_true", help="הדפסת ה-HTML של המייל")
    pv.set_defaults(func=cmd_preview)

    _add_campaign(sub.add_parser("clean", help="הסרת מה שאינו חנות קמעונאית")).set_defaults(func=cmd_clean)
    _add_campaign(sub.add_parser("stats", help="הצגת סטטיסטיקות")).set_defaults(func=cmd_stats)
    _add_campaign(sub.add_parser("check", help="בדיקת מה מוגדר ומה חסר להרצה")).set_defaults(func=cmd_check)
    _add_campaign(sub.add_parser("report", help="משפך הקמפיין: נשלח, המשך, תשובות")).set_defaults(func=cmd_report)

    en = _add_campaign(sub.add_parser(
        "enrich", help="חיפוש אתר ומייל ללידים שנסרקו בלי כתובת"))
    en.add_argument("--limit", type=int, default=50,
                    help="כמה לידים לנסות בהרצה אחת (ברירת מחדל 50)")
    en.set_defaults(func=cmd_enrich)

    ts = _add_campaign(sub.add_parser("test", help="שליחת מייל בדיקה אחד לכתובת שלך"))
    ts.add_argument("--to", required=True, help="הכתובת שאליה יישלח מייל הבדיקה")
    ts.add_argument("--variant", choices=["a", "b"], default="a", help="איזה נוסח")
    ts.add_argument("--name", default='רו"ח משה כהן', help="שם לדוגמה")
    ts.add_argument("--first-name", dest="first_name", default="", help="שם פרטי")
    ts.add_argument("--neighborhood", default="פרדס כץ", help="שכונה לדוגמה")
    ts.add_argument("--type", default="accounting", help="סוג העסק בגוגל")
    ts.add_argument("--rec-count", dest="rec_count", type=int, default=12)
    ts.add_argument("--rec-rating", dest="rec_rating", type=float, default=4.8)
    ts.add_argument("--rec-source", dest="rec_source", default="google")
    ts.add_argument("--rec-quote", dest="rec_quote", default="")
    ts.set_defaults(func=cmd_test)

    rep = _add_campaign(sub.add_parser("replied", help="רישום סוכן שהשיב"))
    rep.add_argument("email", help="כתובת המייל של מי שהשיב")
    rep.add_argument("--note", default="", help="טלפון שהשאיר / הערה")
    rep.set_defaults(func=cmd_replied)

    jd = sub.add_parser("jobdebug", help="אבחון מבנה דף הדרושים (לכוונון הסורק)")
    jd.add_argument("--url", default="https://www.drushim.co.il/jobs/cat32/",
                    help="כתובת עמוד קטגוריה בדרושים")
    jd.set_defaults(func=cmd_jobdebug)

    ip = _add_campaign(sub.add_parser("import", help="ייבוא רשימת עסקים מ-CSV (name,email)"))
    ip.add_argument("path", help="נתיב קובץ ה-CSV")
    ip.set_defaults(func=cmd_import)

    ep = _add_campaign(sub.add_parser("export", help="ייצוא לידים ל-CSV"))
    ep.add_argument("path", help="נתיב קובץ ה-CSV")
    ep.set_defaults(func=cmd_export)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
