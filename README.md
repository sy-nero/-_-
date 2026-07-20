# בוט האיגוד — סריקת עסקים ופנייה במייל

בוט שסורק עסקים מקומיים חדשים בשכונות חרדיות בירושלים דרך **Google Places API**,
מאתר את כתובת המייל שלהם, ושולח מהם פנייה מטעם האיגוד עם קישור לדף נחיתה להרשמה.

## מה הבוט עושה

1. **סורק** — עובר על רשימת שכונות חרדיות בירושלים (`data/neighborhoods.py`) ומושך
   עסקים מקומיים דרך Google Places API (New).
2. **מסנן** — משאיר רק עסקים **פעילים** עם **עד `MAX_REVIEW_COUNT` ביקורות**
   (ברירת מחדל 0). זהו הפרוקסי לעסק "חדש / עד שנה" — ראו הערה למטה.
3. **מאתר מייל** — נכנס לאתר העסק (אם יש) ומחלץ כתובת מייל מעמוד הבית / "צור קשר".
4. **שומר** — שומר כל ליד ב-SQLite כדי למנוע שליחה כפולה.
5. **שולח** — שולח מייל בעברית מטעם האיגוד עם קישור לדף נחיתה, דרך SMTP של האיגוד.
6. **דף נחיתה** — טופס הרשמה ("חזרו אליי") ששומר את הפניות לאותו DB.

## הערה חשובה על "שנת ייסוד עד שנה"

ל-Google Places **אין שדה של שנת ייסוד/הקמה** של עסק. לכן אי אפשר לסנן ישירות לפי
גיל העסק. הפרוקסי הטוב ביותר ל"עסק חדש" הוא **מספר ביקורות אפס/נמוך** — וזה גם
הקריטריון השני שהוגדר. שני התנאים מתמזגים לתנאי אחד יישים:
`review_count <= MAX_REVIEW_COUNT`.

בנוסף, Places **לא מחזיר כתובת מייל** — לכן המייל נשלף מאתר העסק. עסק ללא אתר
יסומן כ-`no_email` וניתן לייצא אותו ל-CSV לפנייה טלפונית.

## התקנה

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # ואז ערכו את .env עם הערכים שלכם
```

מלאו ב-`.env` לפחות:
- `GOOGLE_MAPS_API_KEY` — מפתח מ-Google Cloud עם **Places API (New)** מופעל + חיוב.
- פרטי ה-SMTP של האיגוד (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `FROM_EMAIL`).
- `ASSOCIATION_NAME`, `LANDING_PAGE_URL`, `UNSUBSCRIBE_URL`.

## שימוש

```bash
python main.py scan              # סריקה + איתור מיילים + שמירה ב-DB
python main.py send --dry-run    # תצוגה מקדימה של מי יקבל מייל (בלי לשלוח)
python main.py send              # שליחת המיילים בפועל
python main.py run               # scan ואז send ברצף
python main.py stats             # סטטוס הלידים ב-DB
python main.py export leads.csv  # ייצוא כל הלידים (כולל no_email) ל-CSV
```

### דף הנחיתה

```bash
python landing/app.py
# גלישה אל http://localhost:5000
```

בסביבת ייצור מומלץ להריץ מאחורי gunicorn/nginx, למשל:
```bash
gunicorn -w 2 -b 0.0.0.0:5000 landing.app:app
```

## כוונון

- **שכונות** — ערכו את `data/neighborhoods.py` (הוספה/הסרה/קואורדינטות).
- **סוגי עסקים** — `LOCAL_BUSINESS_TYPES` בקובץ `egud_bot/places.py`.
- **סף ביקורות / רדיוס / מכסת שליחה** — דרך `.env`.

## מבנה הפרויקט

```
.
├── main.py                 # CLI ראשי (scan / send / run / stats / export)
├── config.py               # טעינת הגדרות מ-.env
├── requirements.txt
├── .env.example
├── data/
│   └── neighborhoods.py    # שכונות חרדיות + קואורדינטות
├── egud_bot/
│   ├── places.py           # לקוח Google Places API (New)
│   ├── filters.py          # מודל ליד + לוגיקת סינון
│   ├── email_finder.py     # חילוץ מייל מאתר העסק
│   ├── storage.py          # SQLite (לידים + הרשמות)
│   ├── mailer.py           # שליחת SMTP
│   ├── templates.py        # תבנית המייל (עברית, RTL)
│   └── pipeline.py         # תזמור התהליך המלא
└── landing/
    ├── app.py              # שרת Flask לדף הנחיתה
    └── templates/          # index.html + thanks.html
```

## הערה משפטית (חשוב)

שליחת דיוור לעסקים בישראל כפופה ל**חוק התקשורת (תיקון 40) — איסור "ספאם"**.
מומלץ:
- לוודא שהפנייה רלוונטית ולגיטימית ומטעם גוף מזוהה (האיגוד).
- לכלול **קישור הסרה** בכל מייל (כבר מובנה בתבנית — `UNSUBSCRIBE_URL`).
- לכבד בקשות הסרה ולא לשלוח שוב.
- להיוועץ בייעוץ משפטי לגבי אופי הפנייה והיקפה.

הבוט מגביל שליחה ל-`MAX_EMAILS_PER_RUN` בהרצה ומוסיף השהיה בין בקשות, כדי
להפחית סיכון לחסימה כספאם.
