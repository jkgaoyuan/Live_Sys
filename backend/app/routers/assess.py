from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import (
    ok, now, get_current_user, require_roles, course_or_404,
    assert_course_owner, assert_enrolled, chapter_course,
)
from ..models import (
    Assignment, Submission, Question, Exam, ExamQuestion, ExamAttempt,
    AttemptAnswer, Notification, User, Enrollment, Course,
)

router = APIRouter()


def notify(db: Session, user_id: int, ntype: str, title: str, content: str = ""):
    db.add(Notification(user_id=user_id, type=ntype, title=title, content=content))


# ---------- 作业 ----------

@router.post("/assignments")
def create_assignment(body: dict, user: User = Depends(require_roles("teacher")), db: Session = Depends(get_db)):
    c = chapter_course(db, body["chapter_id"])
    assert_course_owner(user, c)
    a = Assignment(
        chapter_id=body["chapter_id"], title=body["title"],
        description=body.get("description", ""), attachment=body.get("attachment", ""),
        deadline=datetime.fromisoformat(body["deadline"]),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return ok({"id": a.id, "chapter_id": a.chapter_id, "title": a.title,
               "deadline": a.deadline.isoformat()})


@router.get("/assignments")
def list_assignments(user: User = Depends(require_roles("teacher", "admin")), db: Session = Depends(get_db)):
    from ..models import Chapter
    q = db.query(Assignment).join(Chapter, Assignment.chapter_id == Chapter.id).join(Course, Chapter.course_id == Course.id)
    if user.role == "teacher":
        q = q.filter(Course.teacher_id == user.id)
    rows = []
    for a in q.order_by(Assignment.id.desc()):
        enrolled = db.query(Enrollment).filter_by(course_id=a.chapter.course_id).count()
        submitted = {s.student_id for s in db.query(Submission).filter_by(assignment_id=a.id)}
        rows.append({"id": a.id, "chapter_id": a.chapter_id, "course_id": a.chapter.course_id,
                     "title": a.title, "deadline": a.deadline.isoformat(),
                     "enrolled": enrolled, "submitted": len(submitted)})
    return ok(rows)


@router.get("/assignments/me")
def my_assignments(user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    cids = [e.course_id for e in db.query(Enrollment).filter_by(student_id=user.id)]
    from ..models import Chapter
    rows = []
    for a in db.query(Assignment).join(Chapter, Assignment.chapter_id == Chapter.id).filter(Chapter.course_id.in_(cids)):
        subs = db.query(Submission).filter_by(assignment_id=a.id, student_id=user.id).order_by(Submission.version.desc()).all()
        latest = subs[0] if subs else None
        rows.append({
            "id": a.id, "title": a.title, "deadline": a.deadline.isoformat(),
            "status": latest.status if latest else "none",
            "is_late": latest.is_late if latest else None,
            "score": latest.score if latest else None,
            "feedback": latest.feedback if latest else None,
        })
    return ok(rows)


@router.get("/assignments/{aid}/submissions")
def assignment_submissions(aid: int, user: User = Depends(require_roles("teacher", "admin")), db: Session = Depends(get_db)):
    a = db.get(Assignment, aid)
    if a is None:
        raise HTTPException(404, "assignment not found")
    c = chapter_course(db, a.chapter_id)
    assert_course_owner(user, c)
    from ..models import Chapter
    enrolled = {e.student_id for e in db.query(Enrollment).filter_by(course_id=c.id)}
    subs = db.query(Submission).filter_by(assignment_id=aid).all()
    final = {}
    for s in subs:
        if s.student_id not in final or s.version > final[s.student_id].version:
            final[s.student_id] = s
    rows = [{
        "submission_id": s.id,
        "student_id": sid, "real_name": db.get(User, sid).real_name,
        "version": s.version, "is_late": s.is_late, "status": s.status,
        "score": s.score, "submitted_at": s.submitted_at.isoformat(),
    } for sid, s in final.items()]
    missing = [db.get(User, sid).real_name for sid in enrolled - set(final)]
    return ok({"submitted": rows, "missing": missing})


@router.post("/assignments/{aid}/remind")
def remind(aid: int, user: User = Depends(require_roles("teacher")), db: Session = Depends(get_db)):
    a = db.get(Assignment, aid)
    if a is None:
        raise HTTPException(404, "assignment not found")
    c = chapter_course(db, a.chapter_id)
    assert_course_owner(user, c)
    enrolled = {e.student_id for e in db.query(Enrollment).filter_by(course_id=c.id)}
    submitted = {s.student_id for s in db.query(Submission).filter_by(assignment_id=aid)}
    missing = enrolled - submitted
    for sid in missing:
        notify(db, sid, "assignment_remind", f"作业《{a.title}》尚未提交，请尽快完成")
    db.commit()
    return ok({"reminded": len(missing)})


@router.post("/assignments/{aid}/submissions")
def submit_assignment(aid: int, body: dict, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    a = db.get(Assignment, aid)
    if a is None:
        raise HTTPException(404, "assignment not found")
    c = chapter_course(db, a.chapter_id)
    assert_enrolled(db, user, c.id)
    if any(s.status == "graded" for s in db.query(Submission).filter_by(assignment_id=aid, student_id=user.id)):
        raise HTTPException(409, "already graded, cannot resubmit")
    versions = db.query(Submission).filter_by(assignment_id=aid, student_id=user.id).count()
    s = Submission(
        assignment_id=aid, student_id=user.id, content=body.get("content", ""),
        files=body.get("files", []), version=versions + 1, is_late=now() > a.deadline,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return ok({"submission_id": s.id, "version": s.version, "is_late": s.is_late,
               "status": s.status})


@router.put("/submissions/{sid}/grade")
def grade_submission(sid: int, body: dict, user: User = Depends(require_roles("teacher")), db: Session = Depends(get_db)):
    s = db.get(Submission, sid)
    if s is None:
        raise HTTPException(404, "submission not found")
    a = db.get(Assignment, s.assignment_id)
    assert_course_owner(user, chapter_course(db, a.chapter_id))
    score = int(body["score"])
    if not 0 <= score <= 100:
        raise HTTPException(422, "score must be 0-100")
    s.score = score
    s.feedback = body.get("feedback", "")
    s.status = "graded"
    notify(db, s.student_id, "graded", f"作业《{a.title}》已批改：{score}分", s.feedback)
    db.commit()
    return ok({"submission_id": sid, "status": "graded", "score": score})


# ---------- 题库与考试 ----------

@router.post("/questions")
def create_question(body: dict, user: User = Depends(require_roles("teacher")), db: Session = Depends(get_db)):
    c = course_or_404(db, body["course_id"])
    assert_course_owner(user, c)
    if body["type"] not in ("single", "multiple", "judge", "essay"):
        raise HTTPException(422, "invalid question type")
    q = Question(course_id=c.id, type=body["type"], stem=body["stem"],
                 options=body.get("options", []), answer=str(body["answer"]),
                 score=int(body.get("score", 5)))
    db.add(q)
    db.commit()
    db.refresh(q)
    return ok({"id": q.id, "type": q.type, "score": q.score})


@router.get("/courses/{cid}/questions")
def list_questions(cid: int, user: User = Depends(require_roles("teacher", "admin")), db: Session = Depends(get_db)):
    c = course_or_404(db, cid)
    assert_course_owner(user, c)
    rows = db.query(Question).filter_by(course_id=cid).all()
    return ok([{"id": q.id, "type": q.type, "stem": q.stem, "score": q.score} for q in rows])


@router.post("/exams")
def create_exam(body: dict, user: User = Depends(require_roles("teacher")), db: Session = Depends(get_db)):
    from datetime import datetime
    c = chapter_course(db, body["chapter_id"])
    assert_course_owner(user, c)
    qids = body.get("question_ids", [])
    questions = db.query(Question).filter(Question.id.in_(qids)).all()
    if len(questions) != len(qids):
        raise HTTPException(422, "some questions not found")
    if any(q.course_id != c.id for q in questions):
        raise HTTPException(422, "questions must belong to the same course")
    e = Exam(
        chapter_id=body["chapter_id"], title=body["title"],
        pass_score=body.get("pass_score", 60), duration=body.get("duration", 60),
        open_at=datetime.fromisoformat(body["open_at"]),
        close_at=datetime.fromisoformat(body["close_at"]),
        total_score=sum(q.score for q in questions),
    )
    db.add(e)
    db.flush()
    for i, q in enumerate(questions):
        db.add(ExamQuestion(exam_id=e.id, question_id=q.id, score=q.score, sort=i))
    db.commit()
    db.refresh(e)
    return ok({"id": e.id, "title": e.title, "total_score": e.total_score,
               "open_at": e.open_at.isoformat(), "close_at": e.close_at.isoformat()})


@router.get("/exams")
def list_exams(user: User = Depends(require_roles("teacher", "admin")), db: Session = Depends(get_db)):
    from ..models import Chapter
    q = db.query(Exam).join(Chapter, Exam.chapter_id == Chapter.id).join(Course, Chapter.course_id == Course.id)
    if user.role == "teacher":
        q = q.filter(Course.teacher_id == user.id)
    rows = []
    for e in q.order_by(Exam.id.desc()):
        ats = db.query(ExamAttempt).filter_by(exam_id=e.id).all()
        rows.append({"id": e.id, "chapter_id": e.chapter_id, "course_id": e.chapter.course_id,
                     "title": e.title, "total_score": e.total_score, "pass_score": e.pass_score,
                     "open_at": e.open_at.isoformat(), "close_at": e.close_at.isoformat(),
                     "attempts": len(ats),
                     "graded": sum(1 for a in ats if a.status == "graded"),
                     "pending_manual": sum(1 for a in ats if a.status == "submitted")})
    return ok(rows)


@router.get("/exams/me")
def my_exams(user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    from ..models import Chapter
    cids = [e.course_id for e in db.query(Enrollment).filter_by(student_id=user.id)]
    exams = db.query(Exam).join(Chapter, Exam.chapter_id == Chapter.id).filter(Chapter.course_id.in_(cids))
    rows = []
    for e in exams:
        at = db.query(ExamAttempt).filter_by(exam_id=e.id, student_id=user.id).first()
        rows.append({
            "id": e.id, "title": e.title, "total_score": e.total_score,
            "open_at": e.open_at.isoformat(), "close_at": e.close_at.isoformat(),
            "attempt_status": at.status if at else "none",
            "score": attempt_total(at) if at and at.status == "graded" else None,
        })
    return ok(rows)


def attempt_total(at: ExamAttempt) -> int:
    return at.objective_score + (at.manual_score or 0)


@router.post("/exams/{eid}/attempts/start")
def start_attempt(eid: int, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    e = db.get(Exam, eid)
    if e is None:
        raise HTTPException(404, "exam not found")
    from ..models import Chapter
    ch = db.get(Chapter, e.chapter_id)
    assert_enrolled(db, user, ch.course_id)
    at = db.query(ExamAttempt).filter_by(exam_id=eid, student_id=user.id).first()
    if at:
        if at.status != "taking":
            raise HTTPException(409, "attempt already submitted")
        return ok({"attempt_id": at.id, "resumed": True, "questions": _paper(db, eid, at)})
    if now() < e.open_at:
        raise HTTPException(409, "exam not open yet")
    if now() > e.close_at:
        raise HTTPException(409, "exam closed")
    at = ExamAttempt(exam_id=eid, student_id=user.id)
    db.add(at)
    db.commit()
    db.refresh(at)
    return ok({"attempt_id": at.id, "resumed": False,
               "deadline": (at.started_at + timedelta(minutes=e.duration)).isoformat(),
               "questions": _paper(db, eid, at)})


def _paper(db: Session, exam_id: int, attempt: ExamAttempt):
    answered = {a.exam_question_id: a.answer for a in attempt.answers}
    rows = db.query(ExamQuestion).filter_by(exam_id=exam_id).order_by(ExamQuestion.sort).all()
    return [{
        "exam_question_id": eq.id, "type": eq.question.type, "stem": eq.question.stem,
        "options": eq.question.options, "score": eq.score,
        "answered": answered.get(eq.id),
    } for eq in rows]


@router.put("/attempts/{aid}/answers")
def save_answers(aid: int, body: dict, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    at = db.get(ExamAttempt, aid)
    if at is None:
        raise HTTPException(404, "attempt not found")
    if at.student_id != user.id:
        raise HTTPException(403, "not your attempt")
    if at.status != "taking":
        raise HTTPException(409, "attempt not in taking state")
    for item in body.get("answers", []):
        eq = db.get(ExamQuestion, item["exam_question_id"])
        if eq is None or eq.exam_id != at.exam_id:
            raise HTTPException(422, "invalid exam_question_id")
        ans = db.query(AttemptAnswer).filter_by(attempt_id=aid, exam_question_id=eq.id).first()
        if ans is None:
            ans = AttemptAnswer(attempt_id=aid, exam_question_id=eq.id)
            db.add(ans)
        ans.answer = str(item.get("answer", ""))
    if body.get("switch_event"):
        at.switch_count += 1
    db.commit()
    return ok({"attempt_id": aid, "saved": len(body.get("answers", [])),
               "switch_count": at.switch_count})


@router.post("/attempts/{aid}/submit")
def submit_attempt(aid: int, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    at = db.get(ExamAttempt, aid)
    if at is None:
        raise HTTPException(404, "attempt not found")
    if at.student_id != user.id:
        raise HTTPException(403, "not your attempt")
    if at.status != "taking":
        raise HTTPException(409, "already submitted")
    e = db.get(Exam, at.exam_id)
    timed_out = now() > at.started_at + timedelta(minutes=e.duration)
    at.submitted_at = now()
    objective = 0
    has_essay = False
    for eq in db.query(ExamQuestion).filter_by(exam_id=e.id).all():
        ans = db.query(AttemptAnswer).filter_by(attempt_id=aid, exam_question_id=eq.id).first()
        correct = _is_correct(eq, ans.answer if ans else "")
        if eq.question.type == "essay":
            has_essay = True
            continue
        if ans:
            ans.is_correct = correct
        if correct:
            objective += eq.score
    at.objective_score = objective
    if has_essay:
        at.status = "submitted"
    else:
        at.status = "graded"
        at.manual_score = 0
        notify(db, user.id, "exam_result", f"考试《{e.title}》成绩已出：{objective}/{e.total_score}")
    db.commit()
    return ok({"attempt_id": aid, "status": at.status, "timed_out": timed_out,
               "objective_score": objective,
               "total": attempt_total(at) if at.status == "graded" else None,
               "total_score": e.total_score})


def _is_correct(eq: ExamQuestion, answer: str) -> bool:
    q = eq.question
    if q.type in ("single", "judge"):
        return answer.strip() == q.answer.strip()
    if q.type == "multiple":
        a = sorted(x.strip() for x in answer.split(",") if x.strip())
        b = sorted(x.strip() for x in q.answer.split(",") if x.strip())
        return a == b and len(a) > 0
    return False


@router.put("/attempts/{aid}/grade")
def grade_attempt(aid: int, body: dict, user: User = Depends(require_roles("teacher")), db: Session = Depends(get_db)):
    at = db.get(ExamAttempt, aid)
    if at is None:
        raise HTTPException(404, "attempt not found")
    e = db.get(Exam, at.exam_id)
    assert_course_owner(user, chapter_course(db, e.chapter_id))
    if at.status != "submitted":
        raise HTTPException(409, "attempt not awaiting manual grade")
    essay_max = sum(eq.score for eq in db.query(ExamQuestion).filter_by(exam_id=e.id).all()
                    if eq.question.type == "essay")
    ms = int(body["manual_score"])
    if not 0 <= ms <= essay_max:
        raise HTTPException(422, f"manual_score must be 0-{essay_max}")
    at.manual_score = ms
    at.status = "graded"
    notify(db, at.student_id, "exam_result",
           f"考试《{e.title}》成绩已出：{attempt_total(at)}/{e.total_score}")
    db.commit()
    return ok({"attempt_id": aid, "status": "graded", "score": attempt_total(at),
               "total_score": e.total_score})


@router.get("/exams/{eid}/attempts")
def exam_attempts(eid: int, user: User = Depends(require_roles("teacher", "admin")), db: Session = Depends(get_db)):
    e = db.get(Exam, eid)
    if e is None:
        raise HTTPException(404, "exam not found")
    assert_course_owner(user, chapter_course(db, e.chapter_id))
    rows = db.query(ExamAttempt).filter_by(exam_id=eid).all()
    return ok([{
        "attempt_id": a.id, "student": db.get(User, a.student_id).real_name,
        "status": a.status, "switch_count": a.switch_count,
        "score": attempt_total(a) if a.status == "graded" else None,
    } for a in rows])
