@echo off
rem התקנת לוח הקמפיינים על מחשב Windows. מריצים פעם אחת על כל מחשב.
rem שמים את הקובץ הזה ואת .env באותה תיקייה (למשל בדיסק און קי) ולוחצים פעמיים.
rem ההודעות באנגלית: החלון השחור של Windows מציג עברית הפוך.
chcp 65001 >nul
setlocal
set "SRC=%~dp0"
set "APP=%LOCALAPPDATA%\egud-bot"

echo === Campaign Board installer ===
echo.

rem --- 1. Python ---
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
  python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo Installing Python, this takes a few minutes...
  winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PY (
  echo.
  echo Python was not found. Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH". Then run this installer again.
  pause
  exit /b 1
)
echo Python: OK

rem --- 2. Program files ---
rem ההורדה דרך PowerShell, כלומר דרך Windows עצמו: סומך על אותן תעודות כמו
rem הדפדפן, גם ברשת מסוננת (נטפרי, רימון) או עם אנטי-וירוס שבודק HTTPS.
if not exist "%APP%" mkdir "%APP%"
echo Downloading the program...
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $z=Join-Path $env:TEMP 'egud-bot.zip'; $x=Join-Path $env:TEMP 'egud-bot-x'; Invoke-WebRequest -UseBasicParsing 'https://codeload.github.com/sy-nero/-_-/zip/refs/heads/claude/agent-profile-recruitment-bykccn' -OutFile $z; if (Test-Path $x) { Remove-Item $x -Recurse -Force }; Expand-Archive $z $x -Force; $src=(Get-ChildItem $x | Select-Object -First 1).FullName; Copy-Item (Join-Path $src '*') '%APP%' -Recurse -Force; Remove-Item $z, $x -Recurse -Force" || (echo Download failed. Check the internet connection. & pause & exit /b 1)
del "%APP%\.app_version" >nul 2>&1
if not exist "%APP%\start.bat" (echo Download failed. & pause & exit /b 1)
echo Program files: OK

rem --- 3. .env (passwords) next to this installer ---
if exist "%SRC%.env" copy /y "%SRC%.env" "%APP%\.env" >nul
if not exist "%APP%\.env" if exist "%SRC%.env.txt" copy /y "%SRC%.env.txt" "%APP%\.env" >nul
rem בלי קובץ: קוד התקנה (ה-.env בקידוד base64) שנשלח בערוץ נפרד מהמייל.
rem קוראים אותו מהלוח (Clipboard) כי חלון cmd חותך הדבקות ארוכות.
if not exist "%APP%\.env" (
  echo.
  echo No .env file next to the installer.
  echo Copy the SETUP CODE you received by text message, then press any key.
  pause >nul
  powershell -NoProfile -Command "$c=(Get-Clipboard -Raw) -replace '\s',''; try { $b=[Convert]::FromBase64String($c); $t=[Text.Encoding]::UTF8.GetString($b); if ($t -notmatch 'D1_API_TOKEN') { throw 'not a setup code' }; [IO.File]::WriteAllBytes('%APP%\.env', $b); 'Setup code: OK' } catch { 'The copied text is not a valid setup code.' }"
)
if exist "%APP%\.env" (
  echo .env: OK
) else (
  echo.
  echo WARNING: no .env. Run the installer again with the setup code copied,
  echo or put the .env file into: %APP%
)

rem --- 4. Desktop shortcut ---
powershell -NoProfile -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Campaign Board.lnk')); $s.TargetPath='%APP%\start.bat'; $s.WorkingDirectory='%APP%'; $s.IconLocation='%SystemRoot%\System32\shell32.dll,13'; $s.Save()"
echo Desktop shortcut "Campaign Board": OK
echo.
echo Done. Opening the board now. Next time, use the desktop shortcut.
echo Every launch checks GitHub and downloads updates automatically.
echo.
pause
start "" "%APP%\start.bat"
