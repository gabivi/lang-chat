from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pathlib import Path
from datetime import timezone, timedelta
from database import get_db
from models.conversation import Conversation, Message
from models.user import User
from models.feedback import Feedback

try:
    from zoneinfo import ZoneInfo
    _IL_TZ = ZoneInfo("Asia/Jerusalem")
except Exception:
    _IL_TZ = timezone(timedelta(hours=3))

def _il(dt):
    if dt is None: return None
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_IL_TZ)

router = APIRouter(prefix="/admin", tags=["Admin"])

FRONTEND = Path(__file__).parent.parent / "frontend"
ADMIN_PASSWORD = "Gabi1234"


@router.get("/", include_in_schema=False)
def admin_page():
    return FileResponse(FRONTEND / "admin.html")


@router.get("/conversations")
def all_conversations(
    db: Session = Depends(get_db),
    x_admin_password: str = Header(default=None),
):
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")
    """Return all conversations with full message content."""
    convs = (
        db.query(Conversation)
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    result = []
    for conv in convs:
        user = db.get(User, conv.user_id)
        messages = [
            {
                "speaker":   m.speaker,
                "text":      m.text,
                "timestamp": _il(m.timestamp).strftime("%Y-%m-%d %H:%M:%S") if m.timestamp else "",
            }
            for m in conv.messages
        ]
        result.append({
            "conversation_id": conv.id,
            "user_name":       user.name if user else "—",
            "user_gender":     user.gender if user else "unknown",
            "avatar_name":     conv.avatar_name,
            "avatar_gender":   conv.avatar_gender,
            "language":        conv.language,
            "title":           conv.title,
            "created_at":      _il(conv.created_at).strftime("%Y-%m-%d %H:%M") if conv.created_at else "",
            "updated_at":      _il(conv.updated_at).strftime("%Y-%m-%d %H:%M") if conv.updated_at else "",
            "message_count":   len(messages),
            "messages":        messages,
            "review":          conv.review or "",
        })
    return result


@router.get("/feedback")
def all_feedback(
    db: Session = Depends(get_db),
    x_admin_password: str = Header(default=None),
):
    if x_admin_password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")
    entries = db.query(Feedback).order_by(Feedback.created_at.desc()).all()
    return [
        {
            "id":         fb.id,
            "user_name":  fb.user_name or "—",
            "text":       fb.text,
            "created_at": _il(fb.created_at).strftime("%Y-%m-%d %H:%M") if fb.created_at else "",
        }
        for fb in entries
    ]
