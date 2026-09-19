from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Date, ForeignKey, JSON,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utcnow():
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    real_name = Column(String(64), nullable=False)
    role = Column(String(16), nullable=False)  # student|teacher|head_teacher|admin
    class_id = Column(ForeignKey("classes.id", name="fk_users_class_id", use_alter=True))
    status = Column(String(16), default="active")  # active|disabled
    created_at = Column(DateTime, default=utcnow)


class SchoolClass(Base):
    __tablename__ = "classes"
    id = Column(Integer, primary_key=True)
    name = Column(String(64), nullable=False)
    head_teacher_id = Column(ForeignKey("users.id"))


class Course(Base):
    __tablename__ = "courses"
    id = Column(Integer, primary_key=True)
    title = Column(String(128), nullable=False)
    intro = Column(Text, default="")
    teacher_id = Column(ForeignKey("users.id"), nullable=False)
    cover_url = Column(String(256), default="")
    audience = Column(String(128), default="")
    status = Column(String(16), default="draft")  # draft|pending|online|rejected|offline
    created_at = Column(DateTime, default=utcnow)
    teacher = relationship(User, foreign_keys=[teacher_id])


class Chapter(Base):
    __tablename__ = "chapters"
    id = Column(Integer, primary_key=True)
    course_id = Column(ForeignKey("courses.id"), nullable=False)
    parent_id = Column(ForeignKey("chapters.id"))
    title = Column(String(128), nullable=False)
    sort = Column(Integer, default=0)


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("course_id", "student_id"),)
    id = Column(Integer, primary_key=True)
    course_id = Column(ForeignKey("courses.id"), nullable=False)
    student_id = Column(ForeignKey("users.id"), nullable=False)
    source = Column(String(16), default="manual")  # manual|class
    enrolled_at = Column(DateTime, default=utcnow)


class Schedule(Base):
    __tablename__ = "schedules"
    id = Column(Integer, primary_key=True)
    course_id = Column(ForeignKey("courses.id"), nullable=False)
    chapter_id = Column(ForeignKey("chapters.id"), nullable=False)
    teacher_id = Column(ForeignKey("users.id"), nullable=False)
    title = Column(String(128), default="")
    start_at = Column(DateTime, nullable=False)
    end_at = Column(DateTime, nullable=False)
    mode = Column(String(16), default="video")  # video|screen|whiteboard
    status = Column(String(16), default="planned")  # planned|living|finished|canceled
    course = relationship(Course)


class LiveRoom(Base):
    __tablename__ = "live_rooms"
    id = Column(Integer, primary_key=True)
    schedule_id = Column(ForeignKey("schedules.id"), unique=True, nullable=False)
    stream_key = Column(String(64), unique=True, nullable=False)
    status = Column(String(16), default="living")  # living|ended
    online_count = Column(Integer, default=0)
    started_at = Column(DateTime, default=utcnow)
    ended_at = Column(DateTime)


class Interaction(Base):
    __tablename__ = "interactions"
    id = Column(Integer, primary_key=True)
    room_id = Column(ForeignKey("live_rooms.id"), nullable=False)
    student_id = Column(ForeignKey("users.id"), nullable=False)
    type = Column(String(16), nullable=False)  # danmaku|question|handraise|rollcall
    content = Column(Text, default="")
    status = Column(String(16), default="normal")
    # danmaku: normal|recalled ; question: normal|answered
    # handraise: waiting|accepted|declined ; rollcall: pending|present|absent
    ts = Column(DateTime, default=utcnow)


class Vote(Base):
    __tablename__ = "votes"
    id = Column(Integer, primary_key=True)
    room_id = Column(ForeignKey("live_rooms.id"), nullable=False)
    title = Column(String(128), nullable=False)
    options = Column(JSON, nullable=False)  # ["A","B",...]
    deadline = Column(DateTime, nullable=False)
    status = Column(String(16), default="open")  # open|closed


class VoteRecord(Base):
    __tablename__ = "vote_records"
    __table_args__ = (UniqueConstraint("vote_id", "student_id"),)
    id = Column(Integer, primary_key=True)
    vote_id = Column(ForeignKey("votes.id"), nullable=False)
    student_id = Column(ForeignKey("users.id"), nullable=False)
    selected = Column(JSON, nullable=False)  # [idx,...]
    ts = Column(DateTime, default=utcnow)


class Recording(Base):
    __tablename__ = "recordings"
    id = Column(Integer, primary_key=True)
    schedule_id = Column(ForeignKey("schedules.id"), unique=True, nullable=False)
    file_path = Column(String(256), default="")
    hls_url = Column(String(256), default="")
    duration = Column(Integer, default=0)  # seconds
    status = Column(String(16), default="transcoding")  # transcoding|ready|failed


class WatchLog(Base):
    __tablename__ = "watch_logs"
    __table_args__ = (
        UniqueConstraint("student_id", "target_type", "target_id", "log_date"),
    )
    id = Column(Integer, primary_key=True)
    student_id = Column(ForeignKey("users.id"), nullable=False)
    target_type = Column(String(8), nullable=False)  # live|replay
    target_id = Column(Integer, nullable=False)  # schedule_id for live, recording_id for replay
    seconds = Column(Integer, default=0)
    last_position = Column(Integer, default=0)
    log_date = Column(Date, nullable=False)


class Assignment(Base):
    __tablename__ = "assignments"
    id = Column(Integer, primary_key=True)
    chapter_id = Column(ForeignKey("chapters.id"), nullable=False)
    title = Column(String(128), nullable=False)
    description = Column(Text, default="")
    attachment = Column(String(256), default="")
    deadline = Column(DateTime, nullable=False)
    chapter = relationship(Chapter)


class Submission(Base):
    __tablename__ = "submissions"
    id = Column(Integer, primary_key=True)
    assignment_id = Column(ForeignKey("assignments.id"), nullable=False)
    student_id = Column(ForeignKey("users.id"), nullable=False)
    content = Column(Text, default="")
    files = Column(JSON, default=list)
    submitted_at = Column(DateTime, default=utcnow)
    is_late = Column(Boolean, default=False)
    version = Column(Integer, default=1)
    status = Column(String(16), default="submitted")  # submitted|graded
    score = Column(Integer)
    feedback = Column(Text, default="")


class Question(Base):
    __tablename__ = "question_bank"
    id = Column(Integer, primary_key=True)
    course_id = Column(ForeignKey("courses.id"), nullable=False)
    type = Column(String(16), nullable=False)  # single|multiple|judge|essay
    stem = Column(Text, nullable=False)
    options = Column(JSON, default=list)
    answer = Column(Text, nullable=False)
    score = Column(Integer, default=5)


class Exam(Base):
    __tablename__ = "exams"
    id = Column(Integer, primary_key=True)
    chapter_id = Column(ForeignKey("chapters.id"), nullable=False)
    title = Column(String(128), nullable=False)
    total_score = Column(Integer, default=0)
    pass_score = Column(Integer, default=60)
    duration = Column(Integer, default=60)  # minutes
    open_at = Column(DateTime, nullable=False)
    close_at = Column(DateTime, nullable=False)
    publish_result = Column(Boolean, default=True)
    chapter = relationship(Chapter)


class ExamQuestion(Base):
    __tablename__ = "exam_questions"
    __table_args__ = (UniqueConstraint("exam_id", "question_id"),)
    id = Column(Integer, primary_key=True)
    exam_id = Column(ForeignKey("exams.id"), nullable=False)
    question_id = Column(ForeignKey("question_bank.id"), nullable=False)
    score = Column(Integer, default=5)
    sort = Column(Integer, default=0)
    question = relationship(Question)


class ExamAttempt(Base):
    __tablename__ = "exam_attempts"
    __table_args__ = (UniqueConstraint("exam_id", "student_id"),)
    id = Column(Integer, primary_key=True)
    exam_id = Column(ForeignKey("exams.id"), nullable=False)
    student_id = Column(ForeignKey("users.id"), nullable=False)
    started_at = Column(DateTime, default=utcnow)
    submitted_at = Column(DateTime)
    switch_count = Column(Integer, default=0)
    objective_score = Column(Integer, default=0)
    manual_score = Column(Integer)
    status = Column(String(16), default="taking")  # taking|submitted|graded
    answers = relationship("AttemptAnswer", back_populates="attempt", cascade="all, delete-orphan")


class AttemptAnswer(Base):
    __tablename__ = "attempt_answers"
    __table_args__ = (UniqueConstraint("attempt_id", "exam_question_id"),)
    id = Column(Integer, primary_key=True)
    attempt_id = Column(ForeignKey("exam_attempts.id"), nullable=False)
    exam_question_id = Column(ForeignKey("exam_questions.id"), nullable=False)
    answer = Column(Text, default="")
    is_correct = Column(Boolean)
    attempt = relationship(ExamAttempt, back_populates="answers")


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(ForeignKey("users.id"), nullable=False)
    type = Column(String(32), default="system")
    title = Column(String(128), default="")
    content = Column(Text, default="")
    created_at = Column(DateTime, default=utcnow)
    read_at = Column(DateTime)


class ExportLog(Base):
    __tablename__ = "export_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(ForeignKey("users.id"), nullable=False)
    report_type = Column(String(32), nullable=False)
    params = Column(JSON, default=dict)
    file_name = Column(String(128), default="")
    created_at = Column(DateTime, default=utcnow)
