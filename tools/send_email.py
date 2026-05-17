"""Send the briefing via SMTP. bleach sanitizes HTML; login happens here, not in health check."""
from __future__ import annotations
import os
import smtplib
from datetime import date
from email.message import EmailMessage

import bleach
import markdown as md_lib
from dotenv import load_dotenv

from tools.logging_config import get_logger
from tools.tz import today_ct

load_dotenv()
log = get_logger("email")

ALLOWED_TAGS = ["p", "br", "strong", "em", "a", "code", "pre", "h1", "h2", "h3",
                "h4", "ul", "ol", "li", "blockquote", "hr", "table", "thead",
                "tbody", "tr", "th", "td"]
ALLOWED_ATTRS = {"a": ["href", "title"]}


def send(markdown_body: str, on: date | None = None) -> None:
    on = on or today_ct()
    msg = EmailMessage()
    msg["Subject"] = f"[CTI] Daily Briefing — {on.isoformat()}"
    msg["From"] = os.environ["SMTP_USER"]
    msg["To"] = os.environ["EMAIL_TO"]

    html_raw = md_lib.markdown(markdown_body, extensions=["tables", "fenced_code"])
    html_clean = bleach.clean(html_raw, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)

    msg.set_content(markdown_body)
    msg.add_alternative(f"<html><body>{html_clean}</body></html>", subtype="html")

    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"]), timeout=30) as s:
        s.starttls()
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(msg)
    log.info(f"Email sent to {os.environ['EMAIL_TO']} for {on.isoformat()}")
