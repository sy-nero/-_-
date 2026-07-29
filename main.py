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
    path = config.db_path if c == "funding" else "data/leads_hr.db"
    return Storage(path, campaign=c)


def cmd_scan(args) -> int:
    errors = config.validate_for_scan()
    if errors:
        print("שגיאות קונפיגורציה:\n  - " + "\n  - ".join(errors))
        return 1
    storage = _storage(args)
    summary = pipeline.scan(config, storage, campaign=_campaign(args))
    print("\n=== סיכום סריקה ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    return 0


def cmd_send(args) -> int:
    if not args.dry_run:
        errors = config.validate_for_email()
        if errors:
            print("שגיאות קונפיגורציה:\n  - " + "\n  - ".join(errors))
            return 1
    storage = _storage(args)
    summary = pipeline.send_emails(config, storage, dry_run=args.dry_run,
                                   campaign=_campaign(args))
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
    db_path = config.db_path if _campaign(args) == "funding" else "data/leads_hr.db"
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
    sp.add_argument("--campaign", choices=["funding", "hr"], default="funding",
                    help="funding=מימון (ברירת מחדל), hr=משאבי אנוש (קורס וכנס)")
    return sp


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="בוט האיגוד — סריקת עסקים ושליחת מיילים")
    p.add_argument("-v", "--verbose", action="store_true", help="לוג מפורט")
    sub = p.add_subparsers(dest="command", required=True)

    _add_campaign(sub.add_parser("scan", help="סריקה + איתור מיילים")).set_defaults(func=cmd_scan)

    sp = _add_campaign(sub.add_parser("send", help="שליחת מיילים"))
    sp.add_argument("--dry-run", action="store_true", help="בלי לשלוח בפועל")
    sp.set_defaults(func=cmd_send)

    rp = _add_campaign(sub.add_parser("run", help="scan ואז send"))
    rp.add_argument("--dry-run", action="store_true", help="בלי לשלוח בפועל")
    rp.set_defaults(func=cmd_run)

    _add_campaign(sub.add_parser("clean", help="הסרת מה שאינו חנות קמעונאית")).set_defaults(func=cmd_clean)
    _add_campaign(sub.add_parser("stats", help="הצגת סטטיסטיקות")).set_defaults(func=cmd_stats)

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
