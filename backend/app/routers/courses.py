from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import (
    ok, get_current_user, require_roles, course_or_404, assert_course_owner,
    assert_enrolled, now,
)
from ..models import Course, Chapter, Enrollment, Schedule, User

router = APIRouter()


def _course_dict(c: Course, chapter_count: int = None):
    d = {
        "id": c.id, "title": c.title, "intro": c.intro, "teacher_id": c.teacher_id,
        "cover_url": c.cover_url, "audience": c.audience, "status": c.status,
    }
    if chapter_count is not None:
        d["chapter_count"] = chapter_count
    return d


@router.post("/courses")
def create_course(body: dict, user: User = Depends(require_roles("teacher")), db: Session = Depends(get_db)):
    c = Course(
        title=body["title"], intro=body.get("intro", ""), teacher_id=user.id,
        cover_url=body.get("cover_url", ""), audience=body.get("audience", ""),
    )
    db.add(c)
    db.flush()
    for i, ch in enumerate(body.get("chapters", [])):
        parent = Chapter(course_id=c.id, title=ch["title"], sort=ch.get("sort", i))
        db.add(parent)
        db.flush()
        for j, sub in enumerate(ch.get("children", [])):
            db.add(Chapter(course_id=c.id, parent_id=parent.id,
                          title=sub["title"], sort=sub.get("sort", j)))
    db.commit()
    db.refresh(c)
    return ok(_course_dict(c))


@router.post("/courses/{cid}/submit-review")
def submit_review(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = course_or_404(db, cid)
    assert_course_owner(user, c)
    if c.status not in ("draft", "rejected"):
        raise HTTPException(409, f"course status '{c.status}' cannot submit for review")
    c.status = "pending"
    db.commit()
    return ok(_course_dict(c))


@router.put("/courses/{cid}/review")
def review(cid: int, body: dict, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    c = course_or_404(db, cid)
    if c.status != "pending":
        raise HTTPException(409, "course is not pending review")
    decision = body.get("decision")
    if decision not in ("approve", "reject"):
        raise HTTPException(422, "decision must be approve|reject")
    c.status = "online" if decision == "approve" else "rejected"
    db.commit()
    return ok(_course_dict(c))


@router.get("/courses")
def list_courses(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Course)
    if user.role == "teacher":
        q = q.filter(Course.teacher_id == user.id)
    elif user.role == "student":
        ids = [e.course_id for e in db.query(Enrollment).filter_by(student_id=user.id)]
        q = q.filter(Course.id.in_(ids), Course.status == "online")
    # head_teacher / admin see all
    out = []
    for c in q.order_by(Course.id):
        cnt = db.query(Chapter).filter_by(course_id=c.id, parent_id=None).count()
        out.append(_course_dict(c, cnt))
    return ok(out)


@router.get("/courses/{cid}")
def course_detail(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = course_or_404(db, cid)
    if user.role == "student":
        assert_enrolled(db, user, cid)
    chapters = db.query(Chapter).filter_by(course_id=cid).order_by(Chapter.sort, Chapter.id).all()
    tree = [
        {"id": ch.id, "title": ch.title, "parent_id": ch.parent_id, "sort": ch.sort}
        for ch in chapters
    ]
    d = _course_dict(c)
    d["teacher_name"] = c.teacher.real_name
    d["chapters"] = tree
    return ok(d)


@router.post("/courses/{cid}/enroll")
def enroll(cid: int, body: dict, user: User = Depends(require_roles("teacher", "admin")), db: Session = Depends(get_db)):
    c = course_or_404(db, cid)
    assert_course_owner(user, c)
    if c.status != "online":
        raise HTTPException(409, "only online courses can be enrolled")
    if body.get("class_id"):
        sids = [u.id for u in db.query(User).filter_by(class_id=body["class_id"], role="student")]
    else:
        sids = body.get("student_ids", [])
    added = 0
    for sid in sids:
        if db.query(Enrollment).filter_by(course_id=cid, student_id=sid).first():
            continue
        db.add(Enrollment(course_id=cid, student_id=sid,
                          source="class" if body.get("class_id") else "manual"))
        added += 1
    db.commit()
    return ok({"course_id": cid, "enrolled": added})


@router.get("/courses/{cid}/students")
def course_students(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = course_or_404(db, cid)
    assert_course_owner(user, c)
    ens = db.query(Enrollment).filter_by(course_id=cid).all()
    rows = [{"student_id": e.student_id, "real_name": db.get(User, e.student_id).real_name,
             "enrolled_at": e.enrolled_at.isoformat()} for e in ens]
    return ok(rows)


def _schedule_dict(s: Schedule):
    return {
        "id": s.id, "course_id": s.course_id, "chapter_id": s.chapter_id,
        "teacher_id": s.teacher_id, "title": s.title,
        "start_at": s.start_at.isoformat(), "end_at": s.end_at.isoformat(),
        "mode": s.mode, "status": s.status,
    }


@router.post("/schedules")
def create_schedule(body: dict, user: User = Depends(require_roles("teacher", "admin")), db: Session = Depends(get_db)):
    ch = db.get(Chapter, body["chapter_id"])
    if ch is None:
        raise HTTPException(404, "chapter not found")
    c = course_or_404(db, ch.course_id)
    assert_course_owner(user, c)
    if c.status != "online":
        raise HTTPException(409, "course not online")
    start = datetime.fromisoformat(body["start_at"])
    end = datetime.fromisoformat(body["end_at"])
    if end <= start:
        raise HTTPException(422, "end_at must be after start_at")
    teacher_id = c.teacher_id
    clash = db.query(Schedule).filter(
        Schedule.teacher_id == teacher_id,
        Schedule.status.in_(["planned", "living"]),
        Schedule.start_at < end, Schedule.end_at > start,
    ).first()
    if clash:
        raise HTTPException(409, f"time conflict with schedule {clash.id}")
    s = Schedule(
        course_id=c.id, chapter_id=ch.id, teacher_id=teacher_id,
        title=body.get("title", ch.title), start_at=start, end_at=end,
        mode=body.get("mode", "video"),
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return ok(_schedule_dict(s))


@router.get("/schedules/timetable")
def timetable(date_from: str = None, date_to: str = None,
              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Schedule)
    if user.role == "student":
        cids = [e.course_id for e in db.query(Enrollment).filter_by(student_id=user.id)]
        q = q.filter(Schedule.course_id.in_(cids))
    elif user.role == "teacher":
        q = q.filter(Schedule.teacher_id == user.id)
    if date_from:
        q = q.filter(Schedule.start_at >= datetime.fromisoformat(date_from))
    if date_to:
        q = q.filter(Schedule.start_at <= datetime.fromisoformat(date_to))
    return ok([_schedule_dict(s) for s in q.order_by(Schedule.start_at)])


@router.get("/schedules/{sid}")
def schedule_detail(sid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = db.get(Schedule, sid)
    if s is None:
        raise HTTPException(404, "schedule not found")
    assert_enrolled(db, user, s.course_id)
    return ok(_schedule_dict(s))
