@echo off
rem הפעלת לוח הקמפיינים על Windows. לחיצה כפולה על הקובץ מספיקה:
rem בפעם הראשונה הוא מכין סביבה ומתקין, ואז מפעיל את השרת ופותח דפדפן.
chcp 65001 >nul
setlocal
cd /d "%~dp0"
rem קבצים ופלט בעברית: בלי זה Windows קורא אותם בקידוד הישן (cp1255)
set PYTHONUTF8=1

rem Windows מוסיף לפעמים סיומת בשקט (.env.txt), או שהנקודה נופלת בהורדה (env)
if not exist ".env" if exist ".env.txt" ren ".env.txt" ".env"
if not exist ".env" if exist "env.txt" ren "env.txt" ".env"
if not exist ".env" if exist "env" ren "env" ".env"
if not exist ".env" (
  echo אין קובץ .env בתיקייה. צריך להעתיק אותו מהמחשב הראשון.
  echo Missing .env in: %CD%
  pause
  exit /b 1
)

rem מוצאים פייתון: קודם py (המתקין הרשמי), אחר כך python
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
  python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo לא נמצא Python במחשב.
  echo מתקינים מ- https://www.python.org/downloads/ ומסמנים "Add python.exe to PATH".
  pause
  exit /b 1
)

rem הסביבה יושבת מחוץ לתיקיית הפרויקט, כמו ב-Mac, כדי שסנכרון ענן לא ישבור אותה
set "VENV=%USERPROFILE%\.egud-bot-venv"
if not exist "%VENV%\Scripts\python.exe" (
  echo מכין סביבה בפעם הראשונה, זה לוקח דקה...
  %PY% -m venv "%VENV%" || (echo יצירת הסביבה נכשלה & pause & exit /b 1)
)

rem עדכון אוטומטי מגיטהאב: כל שינוי שנדחף מגיע לכאן בהפעלה הבאה
"%VENV%\Scripts\python.exe" updater.py
"%VENV%\Scripts\python.exe" -m pip install --quiet --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install --quiet -r requirements.txt || (echo ההתקנה נכשלה & pause & exit /b 1)

if not defined APP_PORT set APP_PORT=5001
echo.
echo -----------------------------------------
echo   הלוח נפתח בכתובת:  http://127.0.0.1:%APP_PORT%
echo   לעצירה: Ctrl+C, או לסגור את החלון
echo -----------------------------------------
echo.
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:%APP_PORT%"
"%VENV%\Scripts\python.exe" -m webapp.app
pause
