"""חבילת הבוט של האיגוד — סריקת עסקים ושליחת מיילים."""
import sys

__version__ = "1.0.0"

# במחשבים (Windows / Mac): סומכים על מאגר התעודות של המערכת, כמו הדפדפן.
# ברשת מסוננת (נטפרי, רימון) או עם אנטי-וירוס שבודק HTTPS, החיבור ל-D1,
# ל-Gmail ולגיטהאב עובר דרך תעודה של הסינון, שמותקנת ב-Windows ולא ב-certifi.
# בשרת (Linux) לא נוגעים: שם המאגר הרגיל עובד.
if sys.platform in ("win32", "darwin"):
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass
