from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timezone
from database import get_db
from models.conversation import Conversation, Message
from models.user import User
from services.ai import chat, get_avatar_name, get_client

router = APIRouter(tags=["Chat"])


# ── Create conversation ───────────────────────────────────────────────────────

class NewConversationRequest(BaseModel):
    user_id:       int
    language:      str = "en"
    avatar_gender: str = "female"


@router.post("/conversations")
def create_conversation(payload: NewConversationRequest, db: Session = Depends(get_db)):
    user = db.get(User, payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not get_client():
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY is not configured. Please set it in your environment."
        )

    avatar_name = get_avatar_name(payload.language, payload.avatar_gender)
    title_date  = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    conv = Conversation(
        user_id       = user.id,
        language      = payload.language,
        avatar_gender = payload.avatar_gender,
        avatar_name   = avatar_name,
        title         = f"Conversation — {title_date}",
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)

    # Generate opening greeting from the avatar
    greeting = chat(
        user_name = user.name,
        language  = payload.language,
        gender    = payload.avatar_gender,
        history   = [{"role": "user", "content": f"__START__ My name is {user.name}."}],
    )

    msg = Message(conversation_id=conv.id, speaker="avatar", text=greeting)
    db.add(msg)
    conv.updated_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "conversation_id": conv.id,
        "avatar_name":     avatar_name,
        "avatar_gender":   payload.avatar_gender,
        "language":        payload.language,
        "greeting":        greeting,
    }


# ── Load conversation history ─────────────────────────────────────────────────

@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = [
        {"speaker": m.speaker, "text": m.text,
         "timestamp": m.timestamp.strftime("%H:%M") if m.timestamp else ""}
        for m in conv.messages
    ]
    return {
        "conversation_id": conv.id,
        "avatar_name":     conv.avatar_name,
        "avatar_gender":   conv.avatar_gender,
        "language":        conv.language,
        "title":           conv.title,
        "messages":        messages,
    }


# ── Send message ──────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    text: str


@router.post("/conversations/{conversation_id}/chat")
def send_message(conversation_id: int, payload: ChatRequest, db: Session = Depends(get_db)):
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    user = db.get(User, conv.user_id)

    # Save user message (skip saving internal commands)
    is_command = payload.text.startswith("__")
    if not is_command:
        db.add(Message(conversation_id=conv.id, speaker="user", text=payload.text))
        db.commit()

    # Build history for Claude (user/assistant alternating)
    history = []
    for m in conv.messages:
        role = "user" if m.speaker == "user" else "assistant"
        history.append({"role": role, "content": m.text})

    # Add current user turn
    history.append({"role": "user", "content": payload.text})

    # Get AI response
    try:
        response_text = chat(
            user_name = user.name,
            language  = conv.language,
            gender    = conv.avatar_gender,
            history   = history,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Save avatar response
    db.add(Message(conversation_id=conv.id, speaker="avatar", text=response_text))
    conv.updated_at = datetime.now(timezone.utc)

    # Update title after first real user message
    if not is_command and conv.title.startswith("Conversation —") and len(conv.messages) <= 4:
        snippet = payload.text[:40]
        conv.title = snippet + ("…" if len(payload.text) > 40 else "")

    db.commit()

    return {"text": response_text, "avatar_name": conv.avatar_name}
