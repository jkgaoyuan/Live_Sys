from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import (
    ok, now, get_current_user, require_roles, course_or_404,
    assert_course_owner, assert_enrolled, schedule_or_404,
)
from ..models import (
    Schedule, LiveRoom, Interaction, Vote, VoteRecord, Recording,
    Enrollment, User, WatchLog,
)

router = APIRouter()


def _room_schedule(db: Session, room_id: int):
    room = db.get(LiveRoom, room_id)
    if room is None:
        raise HTTPException(404, "room not found")
    s = schedule_or_404(db, room.schedule_id)
    return room, s


def _assert_room_access(user: User, db: Session, room_id: int, owner_ok: bool = True):
    room, s = _room_schedule(db, room_id)
    c = course_or_404(db, s.course_id)
    if user.role in ("head_teacher", "admin"):
        return room, s  # 巡课只读
    if user.role == "teacher":
        if not owner_ok or c.teacher_id != user.id:
            raise HTTPException(403, "not your room")
        return room, s
    assert_enrolled(db, user, s.course_id)
    return room, s


def touch_watch(db: Session, student_id: int, target_type: str, target_id: int,
                add_seconds: int, position: int = None):
    today = now().date()
    log = db.query(WatchLog).filter_by(
        student_id=student_id, target_type=target_type,
        target_id=target_id, log_date=today).first()
    if log is None:
        log = WatchLog(student_id=student_id, target_type=target_type,
                       target_id=target_id, seconds=0, log_date=today)
        db.add(log)
    log.seconds += add_seconds
    if position is not None:
        log.last_position = position
    return log


@router.get("/schedules/{sid}/room")
def schedule_room(sid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = schedule_or_404(db, sid)
    assert_enrolled(db, user, s.course_id)
    room = db.query(LiveRoom).filter_by(schedule_id=sid).first()
    if room is None:
        return ok(None)
    return ok({"room_id": room.id, "schedule_id": sid, "status": room.status,
               "online_count": room.online_count})


@router.post("/schedules/{sid}/start")
def start_live(sid: int, user: User = Depends(require_roles("teacher", "admin")), db: Session = Depends(get_db)):
    s = schedule_or_404(db, sid)
    c = course_or_404(db, s.course_id)
    assert_course_owner(user, c)
    if s.status != "planned":
        raise HTTPException(409, f"schedule status '{s.status}' cannot start")
    if c.status != "online":
        raise HTTPException(409, "course not online")
    key = uuid4().hex[:16]
    room = LiveRoom(schedule_id=s.id, stream_key=key)
    s.status = "living"
    db.add(room)
    db.commit()
    db.refresh(room)
    return ok({
        "room_id": room.id, "schedule_id": s.id, "status": "living",
        "push_url": f"webrtc://srs.local/live/{key}",
        "pull_url": f"webrtc://srs.local/live/{key}",
        "hls_backup": f"http://srs.local/live/{key}.m3u8",
    })


@router.post("/rooms/{rid}/stop")
def stop_live(rid: int, user: User = Depends(require_roles("teacher", "admin")), db: Session = Depends(get_db)):
    room, s = _room_schedule(db, rid)
    c = course_or_404(db, s.course_id)
    assert_course_owner(user, c)
    if room.status != "living":
        raise HTTPException(409, "room is not living")
    room.status = "ended"
    room.ended_at = now()
    s.status = "finished"
    rec = Recording(
        schedule_id=s.id,
        file_path=f"/media/recordings/{s.id}_{uuid4().hex[:8]}.mp4",
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return ok({"room_id": room.id, "status": "ended",
               "recording_id": rec.id, "recording_status": rec.status})


@router.get("/rooms/{rid}")
def room_detail(rid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    room, s = _assert_room_access(user, db, rid)
    c = db.get(Schedule, s.id).course
    counts = {}
    for t in ("danmaku", "question", "handraise", "rollcall"):
        counts[t] = db.query(Interaction).filter_by(room_id=rid, type=t).count()
    return ok({
        "room_id": room.id, "schedule_id": s.id, "course_title": c.title,
        "status": room.status, "online_count": room.online_count,
        "started_at": room.started_at.isoformat(), "interaction_counts": counts,
    })


@router.post("/rooms/{rid}/messages")
def post_message(rid: int, body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    room, s = _room_schedule(db, rid)
    if room.status != "living":
        raise HTTPException(409, "live not running")
    mtype = body.get("type")
    if mtype not in ("danmaku", "question"):
        raise HTTPException(422, "type must be danmaku|question")
    if user.role != "student":
        raise HTTPException(403, "only students interact")
    assert_enrolled(db, user, s.course_id)
    content = (body.get("content") or "").strip()
    if not content or len(content) > 200:
        raise HTTPException(422, "content required, max 200 chars")
    msg = Interaction(room_id=rid, student_id=user.id, type=mtype, content=content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return ok({"id": msg.id, "type": mtype, "from": user.real_name,
               "content": content, "status": msg.status})


@router.get("/rooms/{rid}/messages")
def list_messages(rid: int, types: str = "danmaku,question", after_id: int = 0,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    room, s = _assert_room_access(user, db, rid)
    q = db.query(Interaction).filter(
        Interaction.room_id == rid,
        Interaction.type.in_(types.split(",")),
        Interaction.id > after_id,
    ).order_by(Interaction.id)
    if user.role != "teacher":
        q = q.filter(Interaction.status != "recalled")
    return ok([{
        "id": m.id, "type": m.type, "student": db.get(User, m.student_id).real_name,
        "content": m.content, "status": m.status, "ts": m.ts.isoformat(),
    } for m in q.limit(200)])


@router.post("/rooms/{rid}/messages/{mid}/recall")
def recall(rid: int, mid: int, user: User = Depends(require_roles("teacher", "admin")), db: Session = Depends(get_db)):
    room, s = _room_schedule(db, rid)
    assert_course_owner(user, course_or_404(db, s.course_id))
    msg = db.get(Interaction, mid)
    if msg is None or msg.room_id != rid:
        raise HTTPException(404, "message not found")
    msg.status = "recalled"
    db.commit()
    return ok({"id": mid, "status": "recalled"})


@router.post("/rooms/{rid}/messages/{mid}/answer")
def answer_question(rid: int, mid: int, user: User = Depends(require_roles("teacher")), db: Session = Depends(get_db)):
    room, s = _room_schedule(db, rid)
    assert_course_owner(user, course_or_404(db, s.course_id))
    msg = db.get(Interaction, mid)
    if msg is None or msg.type != "question":
        raise HTTPException(404, "question not found")
    msg.status = "answered"
    db.commit()
    return ok({"id": mid, "status": "answered"})


@router.post("/rooms/{rid}/handraises")
def hand_raise(rid: int, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    room, s = _room_schedule(db, rid)
    if room.status != "living":
        raise HTTPException(409, "live not running")
    assert_enrolled(db, user, s.course_id)
    hr = Interaction(room_id=rid, student_id=user.id, type="handraise", status="waiting")
    db.add(hr)
    db.commit()
    db.refresh(hr)
    return ok({"id": hr.id, "student": user.real_name, "status": "waiting"})


@router.get("/rooms/{rid}/handraises")
def list_handraises(rid: int, user: User = Depends(require_roles("teacher")), db: Session = Depends(get_db)):
    room, s = _room_schedule(db, rid)
    assert_course_owner(user, course_or_404(db, s.course_id))
    rows = db.query(Interaction).filter_by(room_id=rid, type="handraise").all()
    return ok([{"id": r.id, "student": db.get(User, r.student_id).real_name,
                "status": r.status} for r in rows])


@router.post("/rooms/{rid}/handraises/{iid}/handle")
def handle_handraise(rid: int, iid: int, body: dict,
                     user: User = Depends(require_roles("teacher")), db: Session = Depends(get_db)):
    room, s = _room_schedule(db, rid)
    assert_course_owner(user, course_or_404(db, s.course_id))
    hr = db.get(Interaction, iid)
    if hr is None or hr.type != "handraise" or hr.room_id != rid:
        raise HTTPException(404, "handraise not found")
    action = body.get("action")
    if action not in ("accept", "decline"):
        raise HTTPException(422, "action must be accept|decline")
    hr.status = "accepted" if action == "accept" else "declined"
    db.commit()
    return ok({"id": iid, "status": hr.status})


@router.post("/rooms/{rid}/rollcall")
def start_rollcall(rid: int, user: User = Depends(require_roles("teacher")), db: Session = Depends(get_db)):
    room, s = _room_schedule(db, rid)
    assert_course_owner(user, course_or_404(db, s.course_id))
    batch = uuid4().hex[:8]
    students = db.query(Enrollment).filter_by(course_id=s.course_id).all()
    for e in students:
        db.add(Interaction(room_id=rid, student_id=e.student_id,
                           type="rollcall", status="pending", content=f"batch:{batch}"))
    db.commit()
    return ok({"batch": batch, "called": len(students)})


@router.post("/rooms/{rid}/rollcall/respond")
def respond_rollcall(rid: int, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    room, s = _room_schedule(db, rid)
    pending = db.query(Interaction).filter_by(
        room_id=rid, student_id=user.id, type="rollcall", status="pending"
    ).order_by(Interaction.id.desc()).first()
    if pending is None:
        raise HTTPException(409, "no pending rollcall for you")
    pending.status = "present"
    db.commit()
    return ok({"batch": pending.content, "status": "present"})


@router.post("/rooms/{rid}/rollcall/close")
def close_rollcall(rid: int, body: dict, user: User = Depends(require_roles("teacher")), db: Session = Depends(get_db)):
    room, s = _room_schedule(db, rid)
    assert_course_owner(user, course_or_404(db, s.course_id))
    batch = body.get("batch")
    rows = db.query(Interaction).filter_by(room_id=rid, type="rollcall")
    if batch:
        rows = rows.filter(Interaction.content == f"batch:{batch}")
    present = absent = 0
    for r in rows:
        if r.status == "pending":
            r.status = "absent"
        if r.status == "present":
            present += 1
        else:
            absent += 1
    db.commit()
    return ok({"present": present, "absent": absent})


@router.get("/rooms/{rid}/votes")
def room_votes(rid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    room, s = _assert_room_access(user, db, rid)
    out = []
    for v in db.query(Vote).filter_by(room_id=rid).order_by(Vote.id.desc()).all():
        records = db.query(VoteRecord).filter_by(vote_id=v.id).all()
        counts = [0] * len(v.options)
        mine = None
        for r in records:
            for i in r.selected:
                counts[i] += 1
            if r.student_id == user.id:
                mine = r.selected
        if now() > v.deadline and v.status == "open":
            v.status = "closed"
            db.commit()
        out.append({"id": v.id, "title": v.title, "options": v.options, "status": v.status,
                    "deadline": v.deadline.isoformat(),
                    "result": dict(zip(v.options, counts)), "participants": len(records),
                    "mine": mine})
    return ok(out)


@router.post("/rooms/{rid}/votes")
def create_vote(rid: int, body: dict, user: User = Depends(require_roles("teacher")), db: Session = Depends(get_db)):
    room, s = _room_schedule(db, rid)
    assert_course_owner(user, course_or_404(db, s.course_id))
    options = body.get("options", [])
    if len(options) < 2 or len(options) > 6:
        raise HTTPException(422, "vote needs 2-6 options")
    v = Vote(room_id=rid, title=body["title"], options=options,
             deadline=now() + timedelta(seconds=body.get("duration_seconds", 60)))
    db.add(v)
    db.commit()
    db.refresh(v)
    return ok({"id": v.id, "title": v.title, "options": v.options,
               "deadline": v.deadline.isoformat()})


@router.post("/votes/{vid}/cast")
def cast_vote(vid: int, body: dict, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    v = db.get(Vote, vid)
    if v is None:
        raise HTTPException(404, "vote not found")
    if v.status != "open" or now() > v.deadline:
        v.status = "closed"
        db.commit()
        raise HTTPException(409, "vote closed")
    _, s = _room_schedule(db, v.room_id)
    assert_enrolled(db, user, s.course_id)
    if db.query(VoteRecord).filter_by(vote_id=vid, student_id=user.id).first():
        raise HTTPException(409, "already voted")
    selected = body.get("selected", [])
    if any(i < 0 or i >= len(v.options) for i in selected):
        raise HTTPException(422, "invalid option index")
    db.add(VoteRecord(vote_id=vid, student_id=user.id, selected=selected))
    db.commit()
    return ok({"vote_id": vid, "student": user.real_name, "selected": selected})


@router.get("/votes/{vid}/result")
def vote_result(vid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    v = db.get(Vote, vid)
    if v is None:
        raise HTTPException(404, "vote not found")
    if now() > v.deadline:
        v.status = "closed"
        db.commit()
    records = db.query(VoteRecord).filter_by(vote_id=vid).all()
    counts = [0] * len(v.options)
    for r in records:
        for i in r.selected:
            counts[i] += 1
    return ok({"title": v.title, "status": v.status,
               "result": dict(zip(v.options, counts)), "participants": len(records)})


@router.post("/rooms/{rid}/heartbeat")
def heartbeat(rid: int, body: dict, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    room, s = _room_schedule(db, rid)
    if room.status != "living":
        raise HTTPException(409, "live not running")
    assert_enrolled(db, user, s.course_id)
    secs = int(body.get("seconds", 30))
    if secs <= 0 or secs > 60:
        raise HTTPException(422, "seconds must be in (0,60]")
    log = touch_watch(db, user.id, "live", s.id, secs)
    db.commit()
    return ok({"date": str(log.log_date), "total_seconds": log.seconds})


@router.get("/schedules/{sid}/recording")
def get_recording(sid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = schedule_or_404(db, sid)
    assert_enrolled(db, user, s.course_id)
    rec = db.query(Recording).filter_by(schedule_id=sid).first()
    if rec is None:
        raise HTTPException(404, "recording not generated")
    mine = db.query(WatchLog).filter_by(student_id=user.id, target_type="replay",
                                        target_id=rec.id).first()
    return ok({"id": rec.id, "schedule_id": sid, "status": rec.status,
               "duration": rec.duration, "hls_url": rec.hls_url,
               "my_seconds": mine.seconds if mine else 0,
               "last_position": mine.last_position if mine else 0})


@router.post("/recordings/{rid}/transcode")
def finish_transcode(rid: int, body: dict, user: User = Depends(require_roles("teacher", "admin")), db: Session = Depends(get_db)):
    rec = db.get(Recording, rid)
    if rec is None:
        raise HTTPException(404, "recording not found")
    s = schedule_or_404(db, rec.schedule_id)
    assert_course_owner(user, course_or_404(db, s.course_id))
    if rec.status != "transcoding":
        raise HTTPException(409, f"recording status '{rec.status}'")
    rec.status = "ready"
    rec.duration = int(body.get("duration", 0))
    rec.hls_url = f"/hls/rec_{rec.id}/index.m3u8"
    db.commit()
    return ok({"id": rec.id, "status": "ready", "hls_url": rec.hls_url})


@router.put("/recordings/{rid}/heartbeat")
def replay_heartbeat(rid: int, body: dict, user: User = Depends(require_roles("student")), db: Session = Depends(get_db)):
    rec = db.get(Recording, rid)
    if rec is None:
        raise HTTPException(404, "recording not found")
    if rec.status != "ready":
        raise HTTPException(409, "replay not ready")
    s = schedule_or_404(db, rec.schedule_id)
    assert_enrolled(db, user, s.course_id)
    secs = int(body.get("seconds", 30))
    if secs <= 0 or secs > 60:
        raise HTTPException(422, "seconds must be in (0,60]")
    log = touch_watch(db, user.id, "replay", rec.id, secs,
                      position=int(body.get("position", 0)))
    db.commit()
    return ok({"total_seconds": log.seconds, "last_position": log.last_position})
