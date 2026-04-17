from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String, nullable=False, index=True)
    gender     = Column(String, default="unknown")  # "male" | "female" | "unknown"
    language   = Column(String, default="he")       # "he" | "en" | "de" | "es" | "fr"
    level      = Column(String, default="beginner") # "beginner" | "intermediate" | "advanced"
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    conversations = relationship("Conversation", back_populates="user", order_by="Conversation.updated_at.desc()")
