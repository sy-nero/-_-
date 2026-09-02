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
pip install -r requirements.txt   # playwright נפרד: requirements-hr.txt (רק לקמפיין hr)
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
python main.py preview --campaign agent   # תצוגת נוסח המייל של קמפיין
python main.py check --campaign agent     # מה מוגדר ומה חסר ב-.env
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
├── landing/
│   ├── app.py              # שרת Flask לדף הנחיתה
│   └── templates/          # index.html + thanks.html
└── docs/
    └── agents.md           # פרופיל הסוכנים הממליצים + נוסח מייל הגיוס
```

## גיוס סוכנים ממליצים (קמפיין `agent`)

מעבר לפניות לבעלי עסקים, יש קמפיין נפרד לגיוס **סוכנים ממליצים** — רואי חשבון,
מאמנים עסקיים ובעלי מקצוע שכבר יש להם יחסי אמון עם בעלי עסקים מה-ICP שלנו.
פרופיל הסוכן המתאים, נוסח מייל הגיוס והמשתנים האישיים שבו מתועדים ב-
**[docs/agents.md](docs/agents.md)**.

```bash
python main.py preview --campaign agent            # תצוגת הנוסח
python main.py preview --campaign agent --whatsapp # אותו נוסח לוואטסאפ
python main.py scan   --campaign agent --city bnei-brak
python main.py import --campaign agent agents.csv  # רשימה ידנית (מאמנים וכו')
python main.py send   --campaign agent --dry-run
python main.py send   --campaign agent --limit 5 --confirm   # אישור לכל מייל
```

`--confirm` מדפיס כל מייל במלואו בטרמינל (כולל קישור לאימות ההמלצה) ושואל
`y` / `n` / `q` לפני שליחה. `q` מבטל את ההרצה כולה ולא נשלח דבר, גם לא מה
שאושר קודם. בסוף מוצגת רשימת הנמענים ונדרש אישור אחרון לפני השליחה בפועל.
`--limit` קובע כמה מיילים ייכנסו להרצה. אין קלט או Ctrl-C — לא נשלח כלום.

בניגוד לשאר הקמפיינים, כאן מחפשים משרד **ותיק** ולא חדש: הסינון דורש
מספר ביקורות **מעל** `AGENT_MIN_REVIEWS` (ברירת מחדל 3), והמייל נשלח אישית
בשם מירי מסינרו (`AGENT_FROM_EMAIL`) ולא בשם האיגוד.

הפנייה מפוצלת לשתי הודעות: הראשונה פותחת שיחה ("חיפשתי רואה חשבון באזור
ירושלים ונתקלתי בך"), והשנייה — רק למי שקיבל את הראשונה — מציגה את התנאים
(CRM ל-3 חודשים במתנה + 10% עמלה). שתיהן מבקשות דבר אחד: להשאיר טלפון.
המדידה דרך `report`, וכל תשובה נרשמת עם `replied`.

## הערה משפטית (חשוב)

שליחת דיוור לעסקים בישראל כפופה ל**חוק התקשורת (תיקון 40) — איסור "ספאם"**.
מומלץ:
- לוודא שהפנייה רלוונטית ולגיטימית ומטעם גוף מזוהה (האיגוד).
- לכלול **קישור הסרה** בכל מייל (כבר מובנה בתבנית — `UNSUBSCRIBE_URL`).
- לכבד בקשות הסרה ולא לשלוח שוב.
- להיוועץ בייעוץ משפטי לגבי אופי הפנייה והיקפה.

הבוט מגביל שליחה ל-`MAX_EMAILS_PER_RUN` בהרצה ומוסיף השהיה בין בקשות, כדי
להפחית סיכון לחסימה כספאם.
