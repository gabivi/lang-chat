from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import get_db
from models.feedback import Feedback

router = APIRouter(tags=["Feedback"])


class FeedbackRequest(BaseModel):
    user_id:   int | None = None
    user_name: str | None = None
    text:      str


@router.post("/feedback")
def submit_feedback(payload: FeedbackRequest, db: Session = Depends(get_db)):
    if not payload.text.strip():
        return {"ok": False}
    fb = Feedback(user_id=payload.user_id, user_name=payload.user_name, text=payload.text.strip())
    db.add(fb)
    db.commit()
    return {"ok": True}
