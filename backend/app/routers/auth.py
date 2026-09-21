from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import (
    ok, hash_password, verify_password, create_token,
    get_current_user, require_roles,
)
from ..models import User, SchoolClass, Course, Enrollment, Course, Enrollment

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


@router.patch("/users/{uid}/status")
def set_user_status(uid: int, body: dict, admin: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    status = body.get("status")
    if status not in ("active", "disabled"):
        raise HTTPException(422, "status 只能为 active 或 disabled")
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "用户不存在")
    if u.role == "admin":
        raise HTTPException(403, "管理员账号不可被禁用或删除")
    u.status = status
    db.commit()
    return ok(user_info(u))


@router.post("/classes", dependencies=[Depends(require_roles("admin"))])
def create_class(body: dict, db: Session = Depends(get_db)):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "班级名称不能为空")
    if len(name) > 10:
        raise HTTPException(422, "班级名称不能超过 10 个中文字符")
    c = SchoolClass(name=name, head_teacher_id=body.get("head_teacher_id"))
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


@router.delete("/classes/{cid}", dependencies=[Depends(require_roles("admin"))])
def delete_class(cid: int, db: Session = Depends(get_db)):
    c = db.get(SchoolClass, cid)
    if c is None:
        raise HTTPException(404, "班级不存在")
    member_ids = [u.id for u in db.query(User).filter(User.class_id == cid)]
    if member_ids:
        bound = (db.query(Course)
                 .join(Enrollment, Enrollment.course_id == Course.id)
                 .filter(Enrollment.student_id.in_(member_ids),
                         Enrollment.source == "class").distinct().all())
        if bound:
            titles = "、".join(f"《{x.title}》" for x in bound)
            raise HTTPException(409, f"该班级已绑定课程 {titles}，请先解除关联后再删除")
        raise HTTPException(409, f"该班级下还有 {len(member_ids)} 名学生，请先移出后再删除")
    db.delete(c)
    db.commit()
    return ok({"deleted": cid})
