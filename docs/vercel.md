# פריסה ב-Vercel

## למה זה דרש שינוי בקוד

ב-Render האפליקציה היא שרת שרץ כל הזמן, והסריקה רצה בתוכו כ-thread ברקע.
ב-Vercel אין דבר כזה: כל בקשה מקבלת תהליך שנסגר ברגע שהתשובה נשלחת, ויש
מגבלת זמן קשיחה של **300 שניות** בתוכנית החינמית. סריקה שנמשכת עשר דקות
פשוט לא יכולה לרוץ שם.

לכן הסריקה חולקה ל**מנות**: כל קריאה ל-`/campaign/<id>/scan/step` עושה
כ-40 שניות של עבודה, שומרת את מה שנמצא ואת המקום שאליו הגיעה, וחוזרת.
עמוד ההתקדמות בדפדפן קורא שוב ושוב עד שנגמר.

היתרון חורג מ-Vercel: אין יותר "הסריקה נקטעה והכל אבד". סגירת לשונית,
פריסה מחדש או נפילת שרת רק **משהות** — הסריקה ממשיכה מהמקום שבו עצרה.

## קבצי ההגדרה

| קובץ | מה הוא עושה |
| --- | --- |
| `pyproject.toml` | מצביע על נקודת הכניסה `webapp.app:app`. בלעדיו Vercel היה מנסה את `main.py` שבשורש, שהוא ה-CLI ואין בו אובייקט `app` |
| `.python-version` | 3.12 |
| `vercel.json` | `maxDuration` ורשימת קבצים שלא נכנסים לחבילה |
| `.vercelignore` | מה לא להעלות בכלל |

רשימת התלויות מופיעה גם ב-`pyproject.toml` (משם Vercel מתקין) וגם
ב-`requirements.txt` (משם Render מתקין). **שתיהן חייבות להישאר זהות.**

## אחסון

ב-Vercel אין דיסק לכתיבה. לכן **חובה** להגדיר את Cloudflare D1 — הוא כבר
בשימוש ועובד. שלושת המשתנים הם `D1_ACCOUNT_ID` (32 תווים בלי מקפים),
`D1_DATABASE_ID` (UUID עם מקפים) ו-`D1_API_TOKEN`.

## משתני הסביבה שצריך להעביר

ב-Vercel: Project → Settings → Environment Variables.

```
APP_PASSWORD
FLASK_SECRET_KEY
TRACKING_BASE_URL
GOOGLE_MAPS_API_KEY
SMTP_HOST
SMTP_PORT
AGENT_FROM_EMAIL
AGENT_SMTP_USER
AGENT_SMTP_PASSWORD
D1_ACCOUNT_ID
D1_DATABASE_ID
D1_API_TOKEN
```

`TRACKING_BASE_URL` צריך להיות הכתובת החדשה ב-Vercel, אחרת מעקב הפתיחות
ימשיך להצביע על Render.

`DATA_DIR` לא נחוץ — הוא רלוונטי רק לאחסון מקומי.

## מה לא עובד ב-Vercel

עמוד `/jobs` (סריקה כללית והשלמת מיילים) עדיין מריץ thread ברקע, ולכן
לא יעבוד שם. הסריקה מתוך עמוד הקמפיין — כן.
