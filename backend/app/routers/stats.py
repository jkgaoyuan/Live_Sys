import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import (
    ok, now, get_current_user, require_roles, course_or_404,
    assert_course_owner, assert_enrolled,
)
from ..models import (
    User, Course, Chapter, Enrollment, Schedule, LiveRoom, Interaction,
    Vote, VoteRecord, Recording, WatchLog, Assignment, Submission, Exam,
    ExamAttempt, Notification, ExportLog, SchoolClass,
)
from .assess import attempt_total

router = APIRouter()


def _scoped_students(db: Session, course_id: int, user: User):
    """按角色返回该课程应统计的学生集合（数据范围控制）。"""
    sids = [e.student_id for e in db.query(Enrollment).filter_by(course_id=course_id)]
    students = db.query(User).filter(User.id.in_(sids), User.role == "student").all()
    if user.role == "head_teacher":
        students = [s for s in students if s.class_id == user.class_id]
    return students


def _final_submission(db: Session, aid: int, sid: int):
    subs = db.query(Submission).filter_by(assignment_id=aid, student_id=sid).all()
    return max(subs, key=lambda s: s.version) if subs else None


def build_progress_row(db: Session, course: Course, student: User) -> dict:
    chapter_ids = [c.id for c in db.query(Chapter).filter_by(course_id=course.id)]
    schedules = db.query(Schedule).filter_by(course_id=course.id).all()
    schedule_ids = [s.id for s in schedules]
    finished = [s for s in schedules if s.status == "finished"]
    rooms = db.query(LiveRoom).filter(LiveRoom.schedule_id.in_(schedule_ids)).all() if schedule_ids else []
    room_ids = [r.id for r in rooms]
    recordings = db.query(Recording).join(Schedule, Recording.schedule_id == Schedule.id).filter(
        Schedule.course_id == course.id).all()
    rec_ids = [r.id for r in recordings]

    live_secs = sum(w.seconds for w in db.query(WatchLog).filter_by(
        student_id=student.id, target_type="live").filter(WatchLog.target_id.in_(schedule_ids)))
    replay_secs = sum(w.seconds for w in db.query(WatchLog).filter_by(
        student_id=student.id, target_type="replay").filter(WatchLog.target_id.in_(rec_ids)))

    rollcalls = db.query(Interaction).filter(
        Interaction.student_id == student.id, Interaction.type == "rollcall",
        Interaction.room_id.in_(room_ids)) if room_ids else []
    rc_total = rc_present = 0
    for r in (rollcalls.all() if room_ids else []):
        rc_total += 1
        rc_present += 1 if r.status == "present" else 0

    assignments = db.query(Assignment).filter(Assignment.chapter_id.in_(chapter_ids)).all() if chapter_ids else []
    a_submitted = a_ontime = 0
    a_scores = []
    for a in assignments:
        f = _final_submission(db, a.id, student.id)
        if f:
            a_submitted += 1
            a_ontime += 0 if f.is_late else 1
            if f.status == "graded":
                a_scores.append(f.score)

    exams = db.query(Exam).filter(Exam.chapter_id.in_(chapter_ids)).all() if chapter_ids else []
    e_taken = e_passed = 0
    e_scores = []
    for e in exams:
        at = db.query(ExamAttempt).filter_by(exam_id=e.id, student_id=student.id).first()
        if at and at.status != "taking":
            e_taken += 1
        if at and at.status == "graded":
            total = attempt_total(at)
            e_scores.append(total)
            e_passed += 1 if total >= e.pass_score else 0

    watched_sched = set()
    for w in db.query(WatchLog).filter_by(student_id=student.id, target_type="live"):
        if w.target_id in schedule_ids and w.seconds > 0:
            watched_sched.add(w.target_id)
    for w in db.query(WatchLog).filter_by(student_id=student.id, target_type="replay"):
        rec = next((r for r in recordings if r.id == w.target_id), None)
        if rec and w.seconds > 0:
            watched_sched.add(rec.schedule_id)
    pct = round(100 * len([s for s in finished if s.id in watched_sched]) / len(finished), 1) if finished else 0.0

    return {
        "course_id": course.id, "course_title": course.title,
        "student_id": student.id, "real_name": student.real_name,
        "watch_minutes": round((live_secs + replay_secs) / 60, 1),
        "attendance_present": rc_present, "attendance_total": rc_total,
        "attendance_rate": round(100 * rc_present / rc_total, 1) if rc_total else None,
        "assignments_total": len(assignments), "assignments_submitted": a_submitted,
        "assignments_ontime": a_ontime,
        "assignment_avg": round(sum(a_scores) / len(a_scores), 1) if a_scores else None,
        "exams_total": len(exams), "exams_taken": e_taken,
        "exam_avg": round(sum(e_scores) / len(e_scores), 1) if e_scores else None,
        "exams_passed": e_passed,
        "progress_pct": pct,
    }


@router.get("/me/progress")
def my_progress(user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    courses = db.query(Course).join(Enrollment, Enrollment.course_id == Course.id).filter(
        Enrollment.student_id == user.id).all()
    return ok([build_progress_row(db, c, user) for c in courses])


@router.get("/courses/{cid}/progress")
def course_progress(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = course_or_404(db, cid)
    if user.role == "student":
        assert_enrolled(db, user, cid)
        return ok([build_progress_row(db, c, user)])
    if user.role == "teacher":
        assert_course_owner(user, c)
    students = _scoped_students(db, cid, user)
    return ok([build_progress_row(db, c, s) for s in students])


@router.get("/classes/{clsid}/progress")
def class_progress(clsid: int, user: User = Depends(require_roles("head_teacher", "admin")), db: Session = Depends(get_db)):
    cls = db.get(SchoolClass, clsid)
    if cls is None:
        raise HTTPException(404, "class not found")
    if user.role == "head_teacher" and cls.head_teacher_id != user.id:
        raise HTTPException(403, "not your class")
    students = db.query(User).filter_by(class_id=clsid, role="student").all()
    data = []
    for s in students:
        cids = [e.course_id for e in db.query(Enrollment).filter_by(student_id=s.id)]
        for c in db.query(Course).filter(Course.id.in_(cids)):
            data.append(build_progress_row(db, c, s))
    return ok({"class_id": clsid, "class_name": cls.name, "rows": data})


@router.get("/stats/overview")
def overview(user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    schedule_ids = [s.id for s in db.query(Schedule).all()]
    room_ids = [r.id for r in db.query(LiveRoom).all()]
    return ok({
        "users": db.query(User).count(),
        "students": db.query(User).filter_by(role="student").count(),
        "teachers": db.query(User).filter_by(role="teacher").count(),
        "courses_online": db.query(Course).filter_by(status="online").count(),
        "courses_pending": db.query(Course).filter_by(status="pending").count(),
        "schedules_finished": db.query(Schedule).filter_by(status="finished").count(),
        "live_minutes": sum(r.duration for r in db.query(Recording).all()) // 60,
        "total_watch_minutes": sum(w.seconds for w in db.query(WatchLog).all()) // 60,
        "interactions": db.query(Interaction).filter(Interaction.room_id.in_(room_ids)).count() if room_ids else 0,
    })


@router.get("/stats/courses/{cid}")
def course_stats(cid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = course_or_404(db, cid)
    if user.role == "teacher":
        assert_course_owner(user, c)
    elif user.role == "student":
        raise HTTPException(403, "students use /me/progress")
    students = _scoped_students(db, cid, user)
    rows = [build_progress_row(db, c, s) for s in students]
    schedule_ids = [s.id for s in db.query(Schedule).filter_by(course_id=cid).all()]
    rooms = db.query(LiveRoom).filter(LiveRoom.schedule_id.in_(schedule_ids)).all() if schedule_ids else []
    part = {"danmaku": 0, "question": 0, "handraise": 0, "rollcall_present": 0, "votes_cast": 0}
    for r in rooms:
        for t in ("danmaku", "question", "handraise"):
            part[t] += db.query(Interaction).filter_by(room_id=r.id, type=t).count()
        part["rollcall_present"] += db.query(Interaction).filter_by(room_id=r.id, type="rollcall", status="present").count()
    vote_ids = [v.id for v in db.query(Vote).filter(Vote.room_id.in_([r.id for r in rooms]))] if rooms else []
    part["votes_cast"] = db.query(VoteRecord).filter(VoteRecord.vote_id.in_(vote_ids)).count() if vote_ids else 0
    dist = {"0-59": 0, "60-69": 0, "70-79": 0, "80-89": 0, "90-100": 0}
    for row in rows:
        for v in (row["assignment_avg"], row["exam_avg"]):
            if v is None:
                continue
            key = ("0-59" if v < 60 else "60-69" if v < 70 else "70-79" if v < 80
                   else "80-89" if v < 90 else "90-100")
            dist[key] += 1
    return ok({
        "course_id": cid, "course_title": c.title, "students": len(students),
        "total_watch_minutes": round(sum(r["watch_minutes"] for r in rows), 1),
        "avg_progress_pct": round(sum(r["progress_pct"] for r in rows) / len(rows), 1) if rows else 0,
        "participation": part, "grade_distribution": dist,
    })


@router.get("/stats/export")
def export(report: str = Query(...), course_id: int = None, class_id: int = None,
           format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if report != "course_progress":
        raise HTTPException(422, "unsupported report")
    if course_id is None:
        raise HTTPException(422, "course_id required")
    c = course_or_404(db, course_id)
    if user.role == "teacher":
        assert_course_owner(user, c)
    elif user.role == "student":
        raise HTTPException(403, "not permitted")
    students = _scoped_students(db, course_id, user)
    if class_id:
        students = [s for s in students if s.class_id == class_id]
    rows = [build_progress_row(db, c, s) for s in students]
    headers = ["学生", "观看时长(分钟)", "出勤(次)", "出勤率(%)", "作业(交/总)", "作业均分",
               "考试(考/总)", "考试均分", "及格数", "进度(%)"]
    table = [[r["real_name"], r["watch_minutes"], r["attendance_present"], r["attendance_rate"],
              f"{r['assignments_submitted']}/{r['assignments_total']}", r["assignment_avg"],
              f"{r['exams_taken']}/{r['exams_total']}", r["exam_avg"], r["exams_passed"],
              r["progress_pct"]] for r in rows]
    db.add(ExportLog(user_id=user.id, report_type=report, params={
        "course_id": course_id, "class_id": class_id}, file_name=f"{report}_{course_id}.{format}"))
    db.commit()
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(headers)
        w.writerows(table)
        return StreamingResponse(io.BytesIO(buf.getvalue().encode("utf-8-sig")),
                                 media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=progress.csv"})
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in table:
        ws.append(row)
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return StreamingResponse(
        bio,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=progress.xlsx"})


@router.get("/stats/exports", dependencies=[Depends(require_roles("admin"))])
def export_logs(db: Session = Depends(get_db)):
    return ok([{
        "id": l.id, "user_id": l.user_id, "report_type": l.report_type,
        "params": l.params, "file_name": l.file_name, "created_at": l.created_at.isoformat(),
    } for l in db.query(ExportLog).order_by(ExportLog.id)])


@router.get("/me/notifications")
def my_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Notification).filter_by(user_id=user.id).order_by(Notification.id.desc()).all()
    return ok({
        "unread": sum(1 for n in rows if n.read_at is None),
        "items": [{"id": n.id, "type": n.type, "title": n.title, "content": n.content,
                   "read": n.read_at is not None} for n in rows],
    })


@router.post("/me/notifications/read")
def read_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.query(Notification).filter_by(user_id=user.id, read_at=None).update({"read_at": now()})
    db.commit()
    return ok({"marked_read": n})
