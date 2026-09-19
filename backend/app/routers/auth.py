from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import (
    ok, hash_password, verify_password, create_token,
    get_current_user, require_roles,
)
from ..models import User, SchoolClass

router = APIRouter()

MENUS = {
    "student": ["my-courses", "timetable", "live-room", "my-assignments", "my-exams", "my-progress"],
    "teacher": ["course-mgmt", "schedule-mgmt", "live-studio", "question-bank", "grading", "course-stats"],
    "head_teacher": ["class-dashboard", "class-timetable", "class-progress", "attendance-report"],
    "admin": ["user-mgmt", "course-review", "platform-stats", "export-logs", "schedule-all"],
}


def user_info(u: User):
    return {
        "id": u.id, "username": u.username, "real_name": u.real_name,
        "role": u.role, "class_id": u.class_id, "status": u.status,
    }


@router.post("/auth/login")
def login(body: dict, db: Session = Depends(get_db)):
    u = db.query(User).filter(User.username == body.get("username", "")).first()
    if u is None or not verify_password(body.get("password", ""), u.password_hash):
        raise HTTPException(401, "wrong username or password")
    if u.status != "active":
        raise HTTPException(403, "account disabled")
    return ok({
        "access_token": create_token(u),
        "token_type": "bearer",
        "user": user_info(u),
        "menus": MENUS[u.role],
    })


@router.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    return ok({**user_info(user), "menus": MENUS[user.role]})


@router.post("/users", dependencies=[Depends(require_roles("admin"))])
def create_user(body: dict, db: Session = Depends(get_db)):
    role = body.get("role")
    if role not in MENUS:
        raise HTTPException(422, "invalid role")
    if db.query(User).filter(User.username == body["username"]).first():
        raise HTTPException(409, "username exists")
    u = User(
        username=body["username"],
        password_hash=hash_password(body["password"]),
        real_name=body.get("real_name", body["username"]),
        role=role,
        class_id=body.get("class_id"),
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return ok(user_info(u))


@router.get("/users", dependencies=[Depends(require_roles("admin"))])
def list_users(role: str = None, class_id: int = None, db: Session = Depends(get_db)):
    q = db.query(User)
    if role:
        q = q.filter(User.role == role)
    if class_id:
        q = q.filter(User.class_id == class_id)
    return ok([user_info(u) for u in q.order_by(User.id)])


@router.post("/classes", dependencies=[Depends(require_roles("admin"))])
def create_class(body: dict, db: Session = Depends(get_db)):
    c = SchoolClass(name=body["name"], head_teacher_id=body.get("head_teacher_id"))
    db.add(c)
    db.commit()
    db.refresh(c)
    return ok({"id": c.id, "name": c.name, "head_teacher_id": c.head_teacher_id})


@router.get("/classes")
def list_classes(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok([
        {"id": c.id, "name": c.name, "head_teacher_id": c.head_teacher_id}
        for c in db.query(SchoolClass).order_by(SchoolClass.id)
    ])
