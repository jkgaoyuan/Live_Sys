from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .database import engine, SessionLocal
from .models import Base, User
from .deps import hash_password, ok, UPLOAD_DIR
from . import media, recording
from .routers import auth, courses, live, assess, stats


@asynccontextmanager
async def lifespan(app: FastAPI):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:  # 项目未引入迁移框架，旧库补列
        conn.execute(text(
            "ALTER TABLE recordings ADD COLUMN IF NOT EXISTS error_message VARCHAR(256)"))
    db = SessionLocal()
    if not db.query(User).filter(User.username == "admin").first():
        db.add(User(username="admin", password_hash=hash_password("admin123"),
                    real_name="平台管理员", role="admin"))
        db.commit()
    db.close()
    recording.start_worker()
    yield


app = FastAPI(title="Live_Sys 在线课堂平台 API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(UPLOAD_DIR.parent)), name="static")

for r in (auth, courses, live, assess, stats):
    app.include_router(r.router, prefix="/api/v1")


@app.exception_handler(StarletteHTTPException)
async def http_exc(request, exc):
    return JSONResponse(status_code=exc.status_code,
                        content={"code": exc.status_code, "message": str(exc.detail), "data": None})


@app.exception_handler(RequestValidationError)
async def val_exc(request, exc):
    return JSONResponse(status_code=422,
                        content={"code": 422, "message": str(exc.errors()[:2]), "data": None})


@app.get("/health")
def health():
    return ok({"status": "up"})
