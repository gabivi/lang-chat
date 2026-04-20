from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from database import Base, engine
import models  # noqa: F401 — registers all ORM models
from routers import users, chat, admin, feedback
from sqlalchemy import text

Base.metadata.create_all(bind=engine)

# Add new columns to existing tables if they don't exist yet
with engine.connect() as _conn:
    for _col, _ddl in [
        ("review", "ALTER TABLE conversations ADD COLUMN review TEXT"),
    ]:
        _cols = [r[1] for r in _conn.execute(text("PRAGMA table_info(conversations)"))]
        if _col not in _cols:
            _conn.execute(text(_ddl))
            _conn.commit()

app = FastAPI(title="Companion Chat")

app.include_router(users.router)
app.include_router(chat.router)
app.include_router(admin.router)
app.include_router(feedback.router)

FRONTEND = Path(__file__).parent / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    from fastapi import Response
    return Response(status_code=204)
