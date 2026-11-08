"""Gui email qua SMTP. Demo dung Mailpit (hop thu sandbox, khong gui ra ngoai): http://localhost:8025"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import settings

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


def _money(v) -> str:
    return f"{int(v):,}".replace(",", ".") + "đ"


_env.filters["money"] = _money


def render(template: str, **ctx) -> str:
    return _env.get_template(template).render(store=settings, **ctx)


def send_email(to: str, subject: str, html: str, attachments: list[tuple[str, bytes, str]] | None = None) -> str:
    msg = EmailMessage()
    msg["From"] = f"{settings.store_name} <{settings.smtp_from}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg_id = make_msgid(domain="opschest.test")
    msg["Message-ID"] = msg_id
    msg.set_content("Email này cần trình đọc hỗ trợ HTML.")
    msg.add_alternative(html, subtype="html")
    for name, data, mime in attachments or []:
        maintype, subtype = mime.split("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as s:
        s.send_message(msg)
    return msg_id
