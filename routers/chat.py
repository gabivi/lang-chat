from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from fastapi.responses import StreamingResponse
import os
from groq import Groq
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timezone
from database import get_db
from models.conversation import Conversation, Message
from models.user import User
from services.ai import chat, get_avatar_name, get_client, get_current_holiday

router = APIRouter(tags=["Chat"])


# ── Create conversation ───────────────────────────────────────────────────────

class NewConversationRequest(BaseModel):
    user_id:       int
    language:      str = "en"
    avatar_gender: str = "female"
    user_gender:   str = "unknown"   # "male" | "female" | "unknown"


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

    # Check if this is the user's very first conversation
    existing_count = db.query(Conversation).filter(
        Conversation.user_id == user.id
    ).count()
    is_first_ever = existing_count == 0

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
    start_msg = f"__START__ My name is {user.name}."
    if is_first_ever:
        start_msg += " FIRST_TIME"

    greeting = chat(
        user_name   = user.name,
        language    = payload.language,
        gender      = payload.avatar_gender,
        user_gender = payload.user_gender,
        history     = [{"role": "user", "content": start_msg}],
    )

    msg = Message(conversation_id=conv.id, speaker="avatar", text=greeting)
    db.add(msg)
    conv.updated_at = datetime.now(timezone.utc)
    db.commit()

    hol_en, hol_he = get_current_holiday()
    return {
        "conversation_id": conv.id,
        "avatar_name":     avatar_name,
        "avatar_gender":   payload.avatar_gender,
        "language":        payload.language,
        "greeting":        greeting,
        "holiday_en":      hol_en,
        "holiday_he":      hol_he,
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
    raw_history = []
    for m in conv.messages:
        role = "user" if m.speaker == "user" else "assistant"
        raw_history.append({"role": role, "content": m.text})

    # Add current user turn
    raw_history.append({"role": "user", "content": payload.text})

    # Anthropic requires strictly alternating messages starting with 'user'
    history = []
    for msg in raw_history:
        if not history:
            if msg["role"] == "assistant":
                history.append({"role": "user", "content": "שלום" if conv.language == "he" else "Hi"})
            history.append(msg)
        else:
            if history[-1]["role"] == msg["role"]:
                history[-1]["content"] += f"\n\n{msg['content']}"
            else:
                history.append(msg)

    # Get AI response
    try:
        response_text = chat(
            user_name   = user.name,
            language    = conv.language,
            gender      = conv.avatar_gender,
            user_gender = getattr(user, "gender", "unknown"),
            history     = history,
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

    hol_en, hol_he = get_current_holiday()
    return {"text": response_text, "avatar_name": conv.avatar_name,
            "holiday_en": hol_en, "holiday_he": hol_he}


# ── Speech-to-Text (STT) ──────────────────────────────────────────────────────

@router.post("/stt")
async def stt_endpoint(file: UploadFile = File(...)):
    if "GROQ_API_KEY" not in os.environ:
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY not configured for Speech-to-Text."
        )

    try:
        client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
        
        # Read the uploaded audio file into memory
        audio_data = await file.read()
        
        # We need to send it as a tuple (filename, file_data)
        file_tuple = (file.filename, audio_data)

        # Call Groq's whisper model
        transcription = client.audio.transcriptions.create(
            file=file_tuple,
            model="whisper-large-v3",
            language="he",
            temperature=0.0,
            prompt="שלום",
        )
        return {"text": transcription.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tts")
async def generate_tts(text: str, language: str = "he", gender: str = "female"):
    import edge_tts
    
    voices = {
        ("en", "female"): "en-US-JennyNeural",
        ("en", "male"):   "en-US-GuyNeural",
        ("he", "female"): "he-IL-HilaNeural",
        ("he", "male"):   "he-IL-AvriNeural",
    }
    voice = voices.get((language, gender), "he-IL-HilaNeural")
    
    communicate = edge_tts.Communicate(text, voice)

    async def audio_generator():
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]
                
    return StreamingResponse(audio_generator(), media_type="audio/mpeg")
