# מדריך הרצה מקומי — בוט האיגוד

מדריך קצר להרצת הבוט מהמחשב שלך (שליחת המיילים חייבת לרוץ ממחשב עם גישת SMTP,
לא מסביבת הענן).

## שלב 1 — התקנת Python

צריך **Python 3.11 ומעלה**. בדיקה:
```bash
python3 --version
```
אם אין, להוריד מ־https://www.python.org/downloads/

## שלב 2 — הורדת הקוד

```bash
git clone https://github.com/sy-nero/-_-.git egud-bot
cd egud-bot
git checkout claude/agent-profile-recruitment-bykccn
```

## שלב 3 — התקנת תלויות

```bash
python3 -m venv .venv
source .venv/bin/activate        # ב-Windows:  .venv\Scripts\activate
pip install -r requirements.txt
```

## שלב 4 — יצירת קובץ .env

צרו קובץ בשם `.env` בתיקיית הפרויקט, והדביקו בו את ההגדרות
(את הערכים המדויקים קיבלתם בנפרד — כולל מפתח Google וסיסמת האפליקציה).
ראו את `.env.example` לרשימת כל המשתנים.

> חשוב: אל תעלו את קובץ `.env` ל-Git — הוא מכיל סיסמאות. הוא כבר ב-`.gitignore`.

## שלב 5 — הרצה

```bash
# תצוגה מקדימה של מי יקבל מייל, בלי לשלוח בפועל:
python main.py scan
python main.py send --dry-run

# שליחה בפועל:
python main.py send

# או הכל ברצף (סריקה ואז שליחה):
python main.py run
```

פקודות נוספות:
```bash
python main.py stats             # כמה לידים נאספו ומה הסטטוס
python main.py export leads.csv  # ייצוא כל הלידים (כולל בלי מייל) ל-CSV
```

## קמפיין גיוס סוכנים (agent) — שליחה עם אישור

```bash
python main.py check  --campaign agent
python main.py scan   --campaign agent --city bnei-brak
python main.py stats  --campaign agent
python main.py export --campaign agent agents.csv
python main.py send   --campaign agent --limit 5 --confirm
```

0. `check` — מראה מה מוגדר ומה חסר ב-.env (בלי להדפיס סיסמאות).
1. `scan` — מוצא משרדים ותיקים, מאתר מייל, ומחפש המלצה אמיתית על כל אחד.
2. `stats` / `export` — מה נאסף, ולבדוק את ההמלצות בעיניים לפני שליחה.
3. `send --confirm` — כל מייל מוצג בטרמינל ונשלח רק אחרי אישור.

> שימו לב: אל תדביקו לטרמינל שורות הערה שיש בהן מרכאה בודדת (למשל `רו"ח`) —
> ב-zsh המרכאה פותחת מחרוזת והטרמינל נתקע ב-`dquote>`. הבלוקים כאן נקיים
> ממרכאות בכוונה, כדי שאפשר יהיה להדביק אותם כמו שהם.

בשלב 3 לכל מייל: `y` לשלוח, `n` לדלג, `q` לעצור הכול. מי שדולג נשאר ב-DB
וניתן לשלוח אליו בהרצה אחרת. לפני הכול אפשר תמיד `--dry-run` בלי לשלוח דבר.

## כמה טיפים חשובים

- **התחילו בקטן**: הריצו `python main.py send --dry-run` תחילה כדי לראות למי יישלח.
- **מגבלות Gmail**: חשבון Google Workspace מוגבל בכמות נמענים ביום. שליחת דיוור קר
  בכמות גדולה עלולה לגרום לסימון כספאם או להשעיית החשבון. מומלץ להתחיל עם כמות קטנה
  (10–20) ולראות איך זה מתנהג.
- **סף עסקים חדשים**: `MAX_REVIEW_COUNT=0` תופס רק עסקים בלי ביקורות כלל (חדשים לגמרי).
  לרובם אין אתר ולכן אין מייל. כדי למצוא יותר מיילים אפשר להעלות ל-3 עד 5 ב-.env.
- **הכפתור במייל** ("להשארת פרטים") פותח אצל הנמען מייל חדש אל `CONTACT_EMAIL`
  (כרגע cto@egud.org.il).
