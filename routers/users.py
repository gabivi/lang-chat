from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import timezone, timedelta
from database import get_db
from models.user import User
from models.conversation import Conversation, Message

try:
    from zoneinfo import ZoneInfo
    _IL_TZ = ZoneInfo("Asia/Jerusalem")
except Exception:
    _IL_TZ = timezone(timedelta(hours=3))

def _il(dt):
    if dt is None: return None
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_IL_TZ)

router = APIRouter(prefix="/users", tags=["Users"])


class IdentifyRequest(BaseModel):
    name:   str
    gender: str = "unknown"   # "male" | "female" | "unknown"
    language: str = "he"      # "he" | "en" | "de" | "es" | "fr"
    level: str = "intermediate"  # "beginner" | "intermediate" | "advanced"


@router.post("/identify")
def identify_user(payload: IdentifyRequest, db: Session = Depends(get_db)):
    """Find existing user by name or create a new one."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    user = db.query(User).filter(User.name.ilike(name)).first()
    is_new = user is None
    if is_new:
        user = User(name=name, gender=payload.gender, language=payload.language, level=payload.level)
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # Update fields if they were not set or have changed
        if payload.gender != "unknown":
            user.gender = payload.gender
        if payload.language != "he":  # Only update if not default
            user.language = payload.language
        if payload.level != "intermediate":  # Only update if not default
            user.level = payload.level
        db.commit()

    # Last 5 conversations with message count
    convs = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
        .limit(5)
        .all()
    )
    conversations = [
        {
            "id":            c.id,
            "title":         c.title,
            "language":      c.language,
            "avatar_name":   c.avatar_name,
            "avatar_gender": c.avatar_gender,
            "updated_at":    _il(c.updated_at).strftime("%Y-%m-%d %H:%M") if c.updated_at else "",
            "message_count": db.query(Message).filter(Message.conversation_id == c.id).count(),
            "review":        c.review or "",
        }
        for c in convs
    ]

    return {
        "id":            user.id,
        "name":          user.name,
        "gender":        user.gender,
        "language":      user.language,
        "level":         user.level,
        "is_new":        is_new,
        "conversations": conversations,
    }
