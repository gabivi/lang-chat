from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import get_db
from models.user import User
from models.conversation import Conversation, Message

router = APIRouter(prefix="/users", tags=["Users"])


class IdentifyRequest(BaseModel):
    name:   str
    gender: str = "unknown"   # "male" | "female" | "unknown"


@router.post("/identify")
def identify_user(payload: IdentifyRequest, db: Session = Depends(get_db)):
    """Find existing user by name or create a new one."""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    user = db.query(User).filter(User.name.ilike(name)).first()
    is_new = user is None
    if is_new:
        user = User(name=name, gender=payload.gender)
        db.add(user)
        db.commit()
        db.refresh(user)
    elif payload.gender != "unknown":
        # Update gender if it was unknown before
        user.gender = payload.gender
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
            "id":           c.id,
            "title":        c.title,
            "language":     c.language,
            "avatar_name":  c.avatar_name,
            "avatar_gender": c.avatar_gender,
            "updated_at":   c.updated_at.strftime("%Y-%m-%d %H:%M") if c.updated_at else "",
            "message_count": db.query(Message).filter(Message.conversation_id == c.id).count(),
        }
        for c in convs
    ]

    return {
        "id":            user.id,
        "name":          user.name,
        "gender":        user.gender,
        "is_new":        is_new,
        "conversations": conversations,
    }
