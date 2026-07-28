"""
שליחת מיילים דרך שרת SMTP של האיגוד.
"""
import os
import ssl
import smtplib
import logging
import mimetypes
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.utils import formataddr

logger = logging.getLogger(__name__)


class Mailer:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        from_email: str,
        from_name: str = "",
        reply_to: str = "",
        use_ssl: bool = False,
        logo_path: str = "",
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.from_email = from_email
        self.from_name = from_name
        self.reply_to = reply_to or from_email
        self.use_ssl = use_ssl
        self.logo_path = logo_path if logo_path and os.path.isfile(logo_path) else ""
        self._server: smtplib.SMTP | None = None

    def __enter__(self) -> "Mailer":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def connect(self) -> None:
        context = ssl.create_default_context()
        if self.use_ssl:
            self._server = smtplib.SMTP_SSL(self.host, self.port, context=context, timeout=30)
        else:
            self._server = smtplib.SMTP(self.host, self.port, timeout=30)
            self._server.ehlo()
            self._server.starttls(context=context)
            self._server.ehlo()
        self._server.login(self.user, self.password)
        logger.info("התחברות ל-SMTP הצליחה: %s:%s", self.host, self.port)

    def close(self) -> None:
        if self._server:
            try:
                self._server.quit()
            except Exception:
                pass
            self._server = None

    def _attach_logo(self, root: MIMEMultipart) -> None:
        """מטמיע את הלוגו כתמונה מוטבעת (cid:logo) שאליה מפנה ה-HTML."""
        if not self.logo_path:
            return
        ctype, _ = mimetypes.guess_type(self.logo_path)
        subtype = (ctype or "image/png").split("/")[-1]
        with open(self.logo_path, "rb") as f:
            img = MIMEImage(f.read(), _subtype=subtype)
        img.add_header("Content-ID", "<logo>")
        img.add_header("Content-Disposition", "inline", filename="logo")
        root.attach(img)

    def send(self, to_email: str, subject: str, html_body: str, text_body: str) -> None:
        if not self._server:
            raise RuntimeError("Mailer לא מחובר — יש לקרוא ל-connect() תחילה")

        # מבנה: related( alternative(text, html), logo-image )
        root = MIMEMultipart("related")
        root["Subject"] = subject
        root["From"] = formataddr((self.from_name, self.from_email))
        root["To"] = to_email
        root["Reply-To"] = self.reply_to

        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(text_body, "plain", "utf-8"))
        alt.attach(MIMEText(html_body, "html", "utf-8"))
        root.attach(alt)

        # מטמיעים לוגו רק אם ה-HTML מפנה אליו (mail אישי הוא ללא לוגו)
        if "cid:logo" in html_body:
            self._attach_logo(root)

        self._server.sendmail(self.from_email, [to_email], root.as_string())
        logger.info("מייל נשלח אל %s", to_email)
