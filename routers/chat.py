from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Response
from fastapi.responses import StreamingResponse
import os
import re as _re_top
from groq import Groq
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta

try:
    from zoneinfo import ZoneInfo as _ZI
    _IL_TZ = _ZI("Asia/Jerusalem")
except Exception:
    _IL_TZ = timezone(timedelta(hours=3))
from database import get_db
from models.conversation import Conversation, Message
from models.user import User
from services.ai import chat, get_avatar_name, get_client, get_current_holiday, generate_conversation_review

router = APIRouter(tags=["Chat"])


_AR = _re_top.compile(r'[\u0600-\u06FF]')   # Arabic Unicode block


def _split_arabic(text: str) -> tuple[str, str | None]:
    """Split Arabic dual-format response into (display_hebrew, tts_arabic).

    AI is instructed to output: 'Hebrew transliteration ||| Arabic script'
    but order may be reversed or separator may be missing — handle all cases.
    Always strips Arabic chars from the display part so users see only
    Hebrew-letter transliteration.
    """
    if "|||" in text:
        part_a, part_b = (p.strip() for p in text.split("|||", 1))
        a_arabic = bool(_AR.search(part_a))
        b_arabic = bool(_AR.search(part_b))

        if a_arabic and not b_arabic:
            # Reversed — swap so part_a is the Hebrew side
            part_a, part_b = part_b, part_a

        # Strip any stray Arabic chars from the display side
        display = _AR.sub('', part_a).strip()
        tts = part_b if _AR.search(part_b) else None
        return display or _AR.sub('', part_b).strip(), tts

    # No separator — strip Arabic chars for display; use full text for TTS if it contains Arabic
    display = _AR.sub('', text).strip()
    tts = text if _AR.search(text) else None
    return display or text, tts


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
    title_date  = datetime.now(_IL_TZ).strftime("%d/%m/%Y")

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
        user_level  = user.level,
        history     = [{"role": "user", "content": start_msg}],
    )

    greeting_display, greeting_tts = _split_arabic(greeting)
    msg = Message(conversation_id=conv.id, speaker="avatar", text=greeting_display)
    db.add(msg)
    conv.updated_at = datetime.now(timezone.utc)
    db.commit()

    hol_en, hol_he = get_current_holiday()
    result = {
        "conversation_id": conv.id,
        "avatar_name":     avatar_name,
        "avatar_gender":   payload.avatar_gender,
        "language":        payload.language,
        "greeting":        greeting_display,
        "holiday_en":      hol_en,
        "holiday_he":      hol_he,
    }
    if greeting_tts:
        result["tts_text"] = greeting_tts
    return result


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
            user_level  = getattr(user, "level", "intermediate"),
            history     = history,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Parse Arabic dual-format response (display ||| tts)
    display_text, tts_arabic = _split_arabic(response_text)

    # Save only the display text (Hebrew transliteration) to DB
    db.add(Message(conversation_id=conv.id, speaker="avatar", text=display_text))
    conv.updated_at = datetime.now(timezone.utc)

    # Update title after first real user message
    if not is_command and conv.title.startswith("Conversation —") and len(conv.messages) <= 4:
        snippet = payload.text[:40]
        conv.title = snippet + ("…" if len(payload.text) > 40 else "")

    db.commit()

    hol_en, hol_he = get_current_holiday()
    result = {"text": display_text, "avatar_name": conv.avatar_name,
              "holiday_en": hol_en, "holiday_he": hol_he}
    if tts_arabic:
        result["tts_text"] = tts_arabic
    return result


# ── Get conversation review ───────────────────────────────────────────────────

@router.get("/conversations/{conversation_id}/review")
def get_conversation_review(conversation_id: int, ui_lang: str = "en", db: Session = Depends(get_db)):
    """Generate a review of the conversation with mistakes and corrections."""
    conv = db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    user = db.get(User, conv.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    messages = [
        {"speaker": m.speaker, "text": m.text}
        for m in conv.messages
    ]

    if not messages:
        raise HTTPException(status_code=400, detail="No messages in conversation")

    try:
        review_text = generate_conversation_review(
            messages=messages,
            language=conv.language,
            user_level=getattr(user, "level", "intermediate"),
            ui_lang=ui_lang,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    conv.review = review_text
    db.commit()

    return {
        "conversation_id": conv.id,
        "review": review_text,
        "language": conv.language,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
    }


# ── Speech-to-Text (STT) ──────────────────────────────────────────────────────

@router.post("/stt")
async def stt_endpoint(file: UploadFile = File(...), language: str = "he"):
    if "GROQ_API_KEY" not in os.environ:
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY not configured for Speech-to-Text."
        )

    prompts = {
        "he": "שלום", "en": "Hello", "de": "Hallo",
        "es": "Hola",  "fr": "Bonjour", "hu": "Szia",
    }

    try:
        client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
        audio_data = await file.read()
        file_tuple = (file.filename, audio_data)
        transcription = client.audio.transcriptions.create(
            file=file_tuple,
            model="whisper-large-v3",
            language=language,
            temperature=0.0,
            prompt=prompts.get(language, ""),
        )
        return {"text": transcription.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tts")
async def generate_tts(text: str, language: str = "he", gender: str = "female", level: str = "intermediate"):
    import edge_tts
    import xml.sax.saxutils
    import re
    from urllib.parse import unquote

    voices = {
        ("en", "female"): "en-US-JennyNeural",
        ("en", "male"):   "en-US-GuyNeural",
        ("he", "female"): "he-IL-HilaNeural",
        ("he", "male"):   "he-IL-AvriNeural",
        ("de", "female"): "de-DE-KatjaNeural",
        ("de", "male"):   "de-DE-ConradNeural",
        ("es", "female"): "es-ES-ElviraNeural",
        ("es", "male"):   "es-ES-AlvaroNeural",
        ("fr", "female"): "fr-FR-DeniseNeural",
        ("fr", "male"):   "fr-FR-HenriNeural",
        ("hu", "female"): "hu-HU-NoemiNeural",
        ("hu", "male"):   "hu-HU-TamasNeural",
        ("ar", "female"): "ar-JO-SanaNeural",
        ("ar", "male"):   "ar-JO-TaimNeural",
    }
    voice = voices.get((language, gender), "en-US-JennyNeural")

    # Ensure text is properly decoded from URL
    text = unquote(text)

    # Arabic TTS requires Arabic script — if we got Hebrew transliteration (no Arabic chars),
    # return empty audio gracefully instead of sending unreadable text to the Arabic voice.
    if language == "ar" and not re.search(r'[\u0600-\u06FF]', text):
        from fastapi import Response as _R
        return _R(content=b"", media_type="audio/mpeg")
    
    # Debug: log incoming text
    import sys
    print(f"[TTS DEBUG] Incoming text: {repr(text)}", file=sys.stderr)

    # Adjust speaking rate based on proficiency level using SSML
    # Use named rate values instead of decimals to avoid number artifacts
    rate_map = {"beginner": "slow", "intermediate": "medium", "advanced": "fast"}
    rate = rate_map.get(level, "medium")
    # Note: We're not using SSML rate control anymore as it was causing edge_tts to speak the rate value

    # Comprehensive sanitization for TTS to prevent misinterpretation
    # Remove HTML-like tags first
    text = re.sub(r'<[^>]*>', ' ', text)  # remove HTML/XML tags
    text = text.replace("<", " less than ")  # remaining < chars
    text = text.replace(">", " greater than ")  # remaining > chars
    # Remove/replace problematic characters that edge_tts might mispronounce
    text = text.replace("—", " - ")     # em-dash
    text = text.replace("–", "-")       # en-dash
    text = text.replace("…", "...")     # ellipsis
    text = text.replace("“", '"')    # left smart quote
    text = text.replace("”", '"')    # right smart quote
    text = text.replace("‘", "'")    # left smart apostrophe
    text = text.replace("’", "'")    # right smart apostrophe
    text = text.replace("«", '"')    # left guillemet
    text = text.replace("»", '"')    # right guillemet
    # Remove zero-width characters
    text = re.sub(r'[\u200b\u200c\u200d\u200e\u200f]', '', text)
    # Remove soft hyphens and other control characters
    text = re.sub(r'[\u00ad\u061b]', '', text)
    # Remove ANY decimal/float numbers (0.75, 1.0, 1.25, any X.Y pattern)
    text = re.sub(r'\d+\.\d+', '', text)
    # Remove bracketed/parenthesized numbers
    text = re.sub(r'[\[\(]\d+[\]\)]', '', text)
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Send plain text to edge_tts without SSML (SSML may be causing the rate value to be spoken)
    communicate = edge_tts.Communicate(text, voice)

    async def audio_generator():
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]

    return StreamingResponse(audio_generator(), media_type="audio/mpeg")
