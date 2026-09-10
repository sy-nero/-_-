#!/bin/bash
# הפעלת לוח הקמפיינים על המחשב.
#
# לחיצה כפולה על הקובץ הזה מספיקה — הוא מכין את הסביבה בפעם הראשונה,
# מתקין מה שחסר, מפעיל את השרת ופותח את הדפדפן.
#
# הנתונים נשמרים ב-Cloudflare D1 בענן (לא על המחשב), ולכן הכל נשאר גם
# כשסוגרים, וגם אם תריצי מאוחר יותר ממחשב אחר.

cd "$(dirname "$0")" || exit 1

if [ ! -f .env ]; then
  echo "❌ אין קובץ .env — בלעדיו אין מפתחות ואין חיבור למאגר."
  echo "   העתיקי את .env.example ל-.env ומלאי את הערכים."
  read -r -p "Enter לסגירה" _; exit 1
fi

if [ ! -d .venv ]; then
  echo "מכין סביבה בפעם הראשונה, זה לוקח דקה…"
  python3 -m venv .venv || { echo "❌ אין python3 במחשב"; read -r _; exit 1; }
fi

source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt || {
  echo "❌ ההתקנה נכשלה"; read -r -p "Enter לסגירה" _; exit 1; }

PORT="${APP_PORT:-5001}"
echo
echo "─────────────────────────────────────────"
echo "  הלוח נפתח בכתובת:  http://127.0.0.1:$PORT"
echo "  לעצירה: Ctrl+C, או פשוט לסגור את החלון"
echo "─────────────────────────────────────────"
echo

( sleep 2 && open "http://127.0.0.1:$PORT" ) &
python3 -m webapp.app
