import os
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime, timezone, timedelta

from database import SessionLocal
from models.conversation import Conversation

_TO = "gabivi@gmail.com"


def check_and_notify():
    since = datetime.now(timezone.utc) - timedelta(minutes=30)
    db = SessionLocal()
    try:
        count = db.query(Conversation).filter(Conversation.created_at >= since).count()
    finally:
        db.close()
    if count > 0:
        _send_email(count, since)


def _send_email(count: int, since: datetime):
    user = os.getenv("SMTP_USER")
    pwd  = os.getenv("SMTP_PASSWORD")
    if not user or not pwd:
        return

    noun = "conversation" if count == 1 else "conversations"
    msg = EmailMessage()
    msg["Subject"] = f"ChitChat2Go — {count} new {noun}"
    msg["From"]    = user
    msg["To"]      = _TO
    msg.set_content(
        f"{count} new {noun} started since {since.strftime('%H:%M UTC')}.\n\nChitChat2Go"
    )

    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(user, pwd)
        s.send_message(msg)
