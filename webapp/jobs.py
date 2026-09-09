"""
הרצת סריקה והעשרה מתוך האפליקציה, ברקע.

סריקה נמשכת דקות ארוכות, ולכן היא לא יכולה לרוץ בתוך בקשת HTTP — הדפדפן
היה נתקע והשרת היה מנתק. במקום זה כל הרצה מתבצעת ב-thread נפרד, והעמוד
מציג את ההתקדמות ומתרענן לבד.

מגבלה שחשוב להכיר: זה תהליך בתוך אותו שרת. אם השירות נכבה או נרדם באמצע
(מה שקורה בתוכנית החינמית של Render אחרי חוסר פעילות), ההרצה נקטעת. מה
שכבר נשמר ב-DB נשאר; מה שלא הספיק — לא.
"""
import logging
import threading
from collections import deque
from datetime import datetime, timezone

MAX_LINES = 400


class Job:
    """הרצה אחת: סריקה או העשרה."""

    def __init__(self, kind: str, title: str):
        self.kind = kind
        self.title = title
        self.status = "running"        # running | done | failed
        self.lines: deque = deque(maxlen=MAX_LINES)
        self.summary: dict = {}
        self.error = ""
        self.started_at = datetime.now(timezone.utc)
        self.finished_at = None

    @property
    def elapsed(self) -> int:
        end = self.finished_at or datetime.now(timezone.utc)
        return int((end - self.started_at).total_seconds())


class _LogCollector(logging.Handler):
    """אוסף את שורות הלוג של הסריקה כדי להציג אותן בעמוד."""

    def __init__(self, job: Job):
        super().__init__(level=logging.INFO)
        self.job = job

    def emit(self, record):
        try:
            self.job.lines.append(record.getMessage())
        except Exception:  # noqa: BLE001 — לוג לא מפיל הרצה
            pass


class Runner:
    """מריץ עבודה אחת בכל רגע. הרצה מקבילה של שתי סריקות רק תאט את שתיהן."""

    def __init__(self):
        self.current: Job | None = None
        self.last: Job | None = None
        self._lock = threading.Lock()

    @property
    def busy(self) -> bool:
        return self.current is not None and self.current.status == "running"

    def start(self, kind: str, title: str, work) -> tuple[bool, str]:
        """
        work — פונקציה שמקבלת את ה-Job ומחזירה מילון סיכום.
        מחזיר (התחיל?, הודעה).
        """
        with self._lock:
            if self.busy:
                return False, f"כבר רצה עכשיו הרצה אחרת: {self.current.title}"
            job = Job(kind, title)
            self.current = job

        def run():
            handler = _LogCollector(job)
            logger = logging.getLogger("egud_bot")
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            try:
                job.summary = work(job) or {}
                job.status = "done"
            except Exception as exc:  # noqa: BLE001
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                job.lines.append(f"ההרצה נכשלה: {job.error}")
            finally:
                job.finished_at = datetime.now(timezone.utc)
                logger.removeHandler(handler)
                self.last = job

        threading.Thread(target=run, daemon=True).start()
        return True, "ההרצה התחילה"


runner = Runner()
