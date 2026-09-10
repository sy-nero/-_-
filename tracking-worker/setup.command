#!/bin/bash
# הקמת ה-Worker של מעקב הפתיחות, בלחיצה כפולה.
#
# מה הוא עושה:
#   1. קורא את D1_DATABASE_ID מקובץ .env של הפרויקט
#   2. ממלא אותו ב-wrangler.toml (במקום לערוך ידנית)
#   3. מפרס את ה-Worker ל-Cloudflare
#   4. כותב את הכתובת שהתקבלה חזרה ל-.env כ-TRACKING_BASE_URL
#
# להרצה חוזרת אין נזק -- היא פשוט מעדכנת את ה-Worker.

set -u
cd "$(dirname "$0")" || exit 1
ENV_FILE="../.env"

say() { printf '%s\n' "$1"; }
die() { printf '\n❌ %s\n' "$1"; read -r -p "Enter לסגירה" _; exit 1; }

[ -f "$ENV_FILE" ] || die "לא נמצא קובץ .env בתיקיית הפרויקט."

# קריאת ערך מ-.env בלי להריץ אותו כקוד
read_env() {
  sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" \
    | tail -n 1 | tr -d '"'\''[:space:]'
}

DB_ID="$(read_env D1_DATABASE_ID)"
[ -n "$DB_ID" ] || die "אין D1_DATABASE_ID בקובץ .env. בלעדיו ה-Worker לא יידע לאיזה מסד לכתוב."

# בדיקת שפיות: מזהה מסד הוא UUID עם מקפים. מזהה חשבון הוא 32 תווים בלי
# מקפים -- וההחלפה ביניהם היא טעות שכבר עלתה לנו שעות.
case "$DB_ID" in
  *-*-*-*-*) : ;;
  *) die "ה-D1_DATABASE_ID לא נראה כמו UUID עם מקפים.
   ייתכן ששמת שם את D1_ACCOUNT_ID (32 תווים בלי מקפים). תבדקי ב-Cloudflare." ;;
esac

command -v npx >/dev/null 2>&1 || die "אין Node.js במחשב. להתקין מ-https://nodejs.org ואז להריץ שוב."

say "מכניס את מזהה המסד ל-wrangler.toml…"
TMP="$(mktemp)"
sed "s|^database_id = .*|database_id = \"$DB_ID\"|" wrangler.toml > "$TMP" && mv "$TMP" wrangler.toml

say ""
say "מפרס את ה-Worker. אם זו הפעם הראשונה — ייפתח דפדפן להתחברות ל-Cloudflare."
say ""
npx --yes wrangler@latest deploy 2>&1 | tee /tmp/wrangler-deploy.log
grep -q "Uploaded\|Deployed\|workers.dev" /tmp/wrangler-deploy.log || die "הפריסה נכשלה. הפלט למעלה."

URL="$(grep -o 'https://[a-z0-9.-]*\.workers\.dev' /tmp/wrangler-deploy.log | tail -n 1)"
[ -n "$URL" ] || die "הפריסה הצליחה אבל לא הצלחתי לזהות את הכתובת. חפשי אותה בפלט למעלה."

say ""
say "בודק שהכתובת עונה…"
CODE="$(curl -s -o /dev/null -w '%{http_code}' -m 20 "$URL/px/setupcheck123.gif")"
[ "$CODE" = "200" ] && say "  ✅ הפיקסל עונה" || say "  ⚠️  הפיקסל החזיר $CODE — כדאי לבדוק"

# כתיבת הכתובת ל-.env (מחליף שורה קיימת, או מוסיף)
if grep -q '^[[:space:]]*TRACKING_BASE_URL[[:space:]]*=' "$ENV_FILE"; then
  TMP="$(mktemp)"
  sed "s|^[[:space:]]*TRACKING_BASE_URL[[:space:]]*=.*|TRACKING_BASE_URL=$URL|" "$ENV_FILE" > "$TMP" \
    && mv "$TMP" "$ENV_FILE"
else
  printf '\nTRACKING_BASE_URL=%s\n' "$URL" >> "$ENV_FILE"
fi

say ""
say "─────────────────────────────────────────"
say "  ✅ הכל מוכן."
say "  כתובת המעקב: $URL"
say "  היא נשמרה ב-.env, ולא צריך לעשות איתה כלום."
say ""
say "  עכשיו: לסגור את החלון, ולהפעיל את start.command"
say "─────────────────────────────────────────"
read -r -p "Enter לסגירה" _
