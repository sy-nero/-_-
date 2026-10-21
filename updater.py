"""
עדכון אוטומטי: רץ בכל הפעלה, לפני שהלוח עולה.

בודק בגיטהאב אם יש גרסה חדשה בענף, ואם יש מוריד אותה ומחליף את קבצי
הקוד. כך כל שינוי שנדחף לגיט מגיע לכל המחשבים בהפעלה הבאה, בלי git ובלי
להוריד ZIP ידנית.

מה לא נוגעים בו: .env (הסיסמאות של המחשב), data/ (קבצים מקומיים),
וקובצי ההפעלה עצמם. קובץ .bat שרץ כרגע נקרא שורה אחרי שורה, והחלפה שלו
באמצע הריצה שוברת אותו.

אין אינטרנט, או שגיטהאב לא עונה? ממשיכים עם הגרסה הקיימת. עדכון שנכשל
לא אמור למנוע מהלוח לעלות.
"""
import io
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

REPO = os.getenv("UPDATE_REPO", "sy-nero/-_-")
BRANCH = os.getenv("UPDATE_BRANCH", "claude/agent-profile-recruitment-bykccn")
ROOT = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(ROOT, ".app_version")
KEEP = {".env", "data", ".git", ".app_version"}
#: קובצי הפעלה: מורידים רק אם חסרים (התקנה ראשונה), ולא מחליפים בזמן שהם רצים
LAUNCHERS = {"start.bat", "start.command", "install.bat"}


def _context():
    """
    הקשר TLS שסומך על מה שמערכת ההפעלה סומכת עליו, כמו הדפדפן.

    ברשת מסוננת (נטפרי, רימון) או עם אנטי-וירוס שבודק HTTPS, התעודה שמגיעה
    חתומה על ידי הסינון, והתעודה שלו מותקנת במאגר של Windows ולא ב-certifi.
    Python 3.13 גם פוסל תעודות כאלה בבדיקה המחמירה (VERIFY_X509_STRICT,
    "Missing Authority Key Identifier"). האימות עצמו נשאר: השרשרת חייבת
    להגיע לתעודה שמותקנת במחשב.
    """
    cafile = os.getenv("SSL_CERT_FILE") or os.getenv("REQUESTS_CA_BUNDLE")
    if cafile and os.path.isfile(cafile):
        ctx = ssl.create_default_context(cafile=cafile)
    else:
        try:
            import truststore   # מאגר התעודות של Windows / Mac עצמם
            return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except ImportError:
            pass
        ctx = ssl.create_default_context()   # ב-Windows: טוען את מאגר המערכת
        if sys.platform == "darwin":
            try:
                import certifi   # ב-Mac פייתון לא קורא את מאגר המערכת
                ctx.load_verify_locations(certifi.where())
            except ImportError:
                pass
    ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    return ctx


def _get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "egud-bot-updater"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_context()) as resp:
            return resp.read()
    except (ssl.SSLError, urllib.error.URLError) as exc:
        if sys.platform != "win32" or "CERTIFICATE" not in str(exc).upper():
            raise
        return _get_windows(url, timeout)


def _get_windows(url: str, timeout: int) -> bytes:
    """
    הורדה דרך PowerShell, כלומר דרך Windows עצמו. ברשת מסוננת זה עובד גם
    כשפייתון פוסל את תעודת הסינון, כי Windows בודק אותה כמו הדפדפן.
    """
    fd, path = tempfile.mkstemp(prefix="egud-bot-")
    os.close(fd)
    try:
        cmd = ("$ErrorActionPreference='Stop'; "
               "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; "
               f"Invoke-WebRequest -UseBasicParsing -TimeoutSec {timeout} "
               f"-Headers @{{'User-Agent'='egud-bot-updater'}} '{url}' -OutFile '{path}'")
        subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       check=True, capture_output=True, timeout=timeout + 30)
        with open(path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _latest_sha() -> str:
    branch = urllib.request.quote(BRANCH, safe="")
    data = json.loads(_get(f"https://api.github.com/repos/{REPO}/commits/{branch}"))
    return data["sha"]


def _update_git() -> None:
    """תיקייה שהורדה עם git clone (כמו ב-Mac): פשוט git pull."""
    try:
        out = subprocess.run(["git", "pull", "--ff-only"], cwd=ROOT,
                             capture_output=True, text=True, timeout=60)
        print("update:", (out.stdout or out.stderr).strip().splitlines()[-1:] or "ok")
    except (OSError, subprocess.SubprocessError) as exc:
        print("update skipped:", exc)


def _update_zip() -> None:
    sha = _latest_sha()
    current = ""
    if os.path.exists(VERSION_FILE):
        with open(VERSION_FILE, encoding="utf-8") as f:
            current = f.read().strip()
    if sha == current:
        print("up to date:", sha[:7])
        return
    print("downloading new version:", sha[:7])
    archive = zipfile.ZipFile(io.BytesIO(
        _get(f"https://codeload.github.com/{REPO}/zip/{sha}", timeout=120)))
    names = archive.namelist()
    prefix = names[0].split("/")[0] + "/"       # התיקייה העליונה בתוך ה-ZIP
    for name in names:
        rel = name[len(prefix):]
        if not rel or rel.split("/")[0] in KEEP:
            continue
        target = os.path.join(ROOT, *rel.split("/"))
        if rel in LAUNCHERS and os.path.exists(target):
            continue
        if name.endswith("/"):
            os.makedirs(target, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with archive.open(name) as src, open(target + ".tmp", "wb") as dst:
            shutil.copyfileobj(src, dst)
        os.replace(target + ".tmp", target)
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        f.write(sha)
    print("updated to", sha[:7])


def main() -> int:
    if os.getenv("NO_AUTO_UPDATE"):
        return 0
    try:
        if os.path.isdir(os.path.join(ROOT, ".git")):
            _update_git()
        else:
            _update_zip()
    except Exception as exc:  # noqa: BLE001 — עדכון שנכשל לא עוצר את הלוח
        print("update skipped:", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
