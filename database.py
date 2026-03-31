import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# Use persistent disk on Render (/data), fall back to local file
_db_file = "/data/companion.db" if os.path.isdir("/data") else "./companion.db"
SQLALCHEMY_DATABASE_URL = f"sqlite:///{_db_file}"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
