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
    return Storage(path, campaign=c)


def cmd_scan(args) -> int:
    errors = config.validate_for_scan()
    if errors:
        print("שגיאות קונפיגורציה:\n  - " + "\n  - ".join(errors))
        return 1
    storage = _storage(args)
    summary = pipeline.scan(config, storage, campaign=_campaign(args),
                            city=getattr(args, "city", "jerusalem"))
    print("\n=== סיכום סריקה ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    return 0


def cmd_send(args) -> int:
    if not args.dry_run:
        errors = config.validate_for_email(_campaign(args))
        if errors:
            print("שגיאות קונפיגורציה:\n  - " + "\n  - ".join(errors))
            return 1
    storage = _storage(args)
    summary = pipeline.send_emails(config, storage, dry_run=args.dry_run,
                                   campaign=_campaign(args),
                                   skip_contacted=getattr(args, "skip_contacted", False))
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
    }
    subject, html, text = templates.render(
        campaign, **pipeline.build_ctx(config, campaign, lead))
    if args.html:
        print(html)
        return 0
    if not args.whatsapp:          # בוואטסאפ אין שורת נושא
        print(f"נושא: {subject}\n")
    print(text)
    return 0


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

    _add_city(_add_campaign(sub.add_parser("scan", help="סריקה + איתור מיילים"))).set_defaults(func=cmd_scan)

    sp = _add_campaign(sub.add_parser("send", help="שליחת מיילים"))
    sp.add_argument("--dry-run", action="store_true", help="בלי לשלוח בפועל")
    sp.add_argument("--skip-contacted", action="store_true",
                    help="דלג על כל מי שקיבל מייל בקמפיין אחר (לא לשלוח פעמיים לאותו עסק)")
    sp.set_defaults(func=cmd_send)

    rp = _add_city(_add_campaign(sub.add_parser("run", help="scan ואז send")))
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
    pv.add_argument("--whatsapp", action="store_true",
                    help="נוסח לוואטסאפ (בלי שורת נושא)")
    pv.add_argument("--html", action="store_true", help="הדפסת ה-HTML של המייל")
    pv.set_defaults(func=cmd_preview)

    _add_campaign(sub.add_parser("clean", help="הסרת מה שאינו חנות קמעונאית")).set_defaults(func=cmd_clean)
    _add_campaign(sub.add_parser("stats", help="הצגת סטטיסטיקות")).set_defaults(func=cmd_stats)

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
