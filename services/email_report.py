import os
import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime, timezone, timedelta

from database import SessionLocal
from models.conversation import Conversation
from models.user import User

_TO = "gabivi@gmail.com"


def check_and_notify():
    since = datetime.now(timezone.utc) - timedelta(minutes=30)
    db = SessionLocal()
    try:
        rows = (
            db.query(Conversation, User)
            .join(User, Conversation.user_id == User.id)
            .filter(Conversation.created_at >= since)
            .order_by(Conversation.created_at)
            .all()
        )
        if not rows:
            return

        lines = []
        for conv, user in rows:
            prior = (
                db.query(Conversation)
                .filter(
                    Conversation.user_id == user.id,
                    Conversation.created_at < since,
                )
                .count()
            )
            tag = "returning" if prior > 0 else "new user"
            lines.append(f"  • {user.name} ({tag}, {conv.language})")

        _send_email(len(rows), since, lines)
    finally:
        db.close()


def _send_email(count: int, since: datetime, lines: list[str]):
    smtp_user = os.getenv("SMTP_USER")
    pwd       = os.getenv("SMTP_PASSWORD")
    if not smtp_user or not pwd:
        return

    noun = "conversation" if count == 1 else "conversations"
    msg = EmailMessage()
    msg["Subject"] = f"ChitChat2Go — {count} new {noun}"
    msg["From"]    = smtp_user
    msg["To"]      = _TO
    msg.set_content(
        f"{count} new {noun} since {since.strftime('%H:%M UTC')}:\n\n"
        + "\n".join(lines)
        + "\n\nChitChat2Go"
    )

    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(smtp_user, pwd)
        s.send_message(msg)
