from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .database import engine, SessionLocal
from .models import Base, User
from .deps import hash_password, ok
from .routers import auth, courses, live, assess, stats


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    db = SessionLocal()
    if not db.query(User).filter(User.username == "admin").first():
        db.add(User(username="admin", password_hash=hash_password("admin123"),
                    real_name="平台管理员", role="admin"))
        db.commit()
    db.close()
    yield


app = FastAPI(title="Live_Sys 在线课堂平台 API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
