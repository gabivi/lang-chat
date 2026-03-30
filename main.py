from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from database import Base, engine
import models  # noqa: F401 — registers all ORM models
from routers import users, chat, admin

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Companion Chat")

app.include_router(users.router)
app.include_router(chat.router)
app.include_router(admin.router)

FRONTEND = Path(__file__).parent / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")
