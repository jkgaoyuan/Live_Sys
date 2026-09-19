from datetime import datetime, timedelta

from jose import jwt, ExpiredSignatureError, JWTError
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from .database import get_db
from .models import User, Course, Enrollment, Chapter, Schedule

JWT_SECRET = "dev-secret-change-me"
JWT_ALGO = "HS256"
ACCESS_TTL = timedelta(hours=2)
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


def hash_password(p: str) -> str:
    return pwd_ctx.hash(p)


def verify_password(p: str, h: str) -> bool:
    return pwd_ctx.verify(p, h)


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "exp": datetime.utcnow() + ACCESS_TTL,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def now():
    return datetime.utcnow()


def ok(data=None, message="ok"):
    return {"code": 0, "message": message, "data": data}


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(401, "not authenticated")
    try:
        payload = jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGO])
    except ExpiredSignatureError:
        raise HTTPException(401, "token expired")
    except JWTError:
        raise HTTPException(401, "invalid token")
    user = db.get(User, int(payload["sub"]))
    if user is None or user.status != "active":
        raise HTTPException(403, "account disabled")
    return user


def require_roles(*roles):
    def dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, f"role '{user.role}' is not permitted")
        return user
    return dep


def course_or_404(db: Session, course_id: int) -> Course:
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(404, "course not found")
    return course


def assert_course_owner(user: User, course: Course):
    if user.role == "admin":
        return
    if course.teacher_id != user.id:
        raise HTTPException(403, "not your course")


def chapter_course(db: Session, chapter_id: int) -> Course:
    ch = db.get(Chapter, chapter_id)
    if ch is None:
        raise HTTPException(404, "chapter not found")
    return course_or_404(db, ch.course_id)


def assert_enrolled(db: Session, user: User, course_id: int):
    if user.role in ("admin", "head_teacher"):
        return
    if user.role == "teacher":
        course = course_or_404(db, course_id)
        if course.teacher_id == user.id:
            return
        raise HTTPException(403, "not your course")
    en = db.query(Enrollment).filter_by(course_id=course_id, student_id=user.id).first()
    if en is None:
        raise HTTPException(403, "not enrolled in this course")


def schedule_or_404(db: Session, sid: int) -> Schedule:
    s = db.get(Schedule, sid)
    if s is None:
        raise HTTPException(404, "schedule not found")
    return s
