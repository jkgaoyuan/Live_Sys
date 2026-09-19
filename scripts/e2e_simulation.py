# -*- coding: utf-8 -*-
"""Live_Sys 端到端业务流程模拟：按 PRD 主链路真实调用 REST API（PostgreSQL）。"""
import io
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.main import app
from app.database import engine
from app.models import Base

BASE = "/api/v1"
PASS, FAIL = [], []
MEASURED = {}


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f"  <- {detail}" if detail and not cond else ""))


def api(client, method, path, token=None, **kw):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = client.request(method, BASE + path, headers=headers, **kw)
    ok_status = r.status_code == 200
    body = None
    if ok_status and "application/json" in r.headers.get("content-type", ""):
        body = r.json()
        ok_status = body.get("code") == 0
    if not ok_status:
        raise AssertionError(f"{method} {path} -> HTTP {r.status_code} {r.text[:300]}")
    return body["data"] if body is not None else r


def expect_status(client, method, path, token, status, **kw):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = client.request(method, BASE + path, headers=headers, **kw)
    return r.status_code


def login(client, username, password="Test@123"):
    return api(client, "post", "/auth/login", json={"username": username, "password": password})["access_token"]


def utc(minute_offset=0):
    return (datetime.utcnow() + timedelta(minutes=minute_offset)).isoformat()


def main():
    print("== 重置数据库（DROP/CREATE SCHEMA public 后重建全部业务表）==")
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    Base.metadata.create_all(engine)

    with TestClient(app) as client:  # 触发 lifespan：建表 + 引导 admin
        run(client)

    print("\n== 实测业务数据 ==")
    for k, v in MEASURED.items():
        print(f"  {k}: {v}")
    total = len(PASS) + len(FAIL)
    print(f"\n== 结果: {len(PASS)}/{total} 项断言通过 ==")
    if FAIL:
        print("失败项:")
        for f in FAIL:
            print("  -", f)
        sys.exit(1)


def run(client):
    # ---------- 阶段1：登录与权限 ----------
    print("\n[阶段1] 用户登录与 RBAC")
    admin_login = api(client, "post", "/auth/login",
                      json={"username": "admin", "password": "admin123"})
    admin = admin_login["access_token"]
    check("管理员 bootstrap 登录成功(信封code=0已校验)", bool(admin_login["access_token"])
          and "menus" in admin_login)
    st = expect_status(client, "post", "/auth/login", None, 401,
                       json={"username": "admin", "password": "wrong"})
    check("错误密码被拒绝(401)", st == 401)

    api(client, "post", "/users", token=admin, json={
        "username": "teacher_wang", "password": "Test@123", "real_name": "王讲师", "role": "teacher"})
    api(client, "post", "/users", token=admin, json={
        "username": "teacher_li", "password": "Test@123", "real_name": "李讲师", "role": "teacher"})
    head = api(client, "post", "/users", token=admin, json={
        "username": "head1", "password": "Test@123", "real_name": "赵班主任", "role": "head_teacher"})
    cls = api(client, "post", "/classes", token=admin,
              json={"name": "高三1班", "head_teacher_id": head["id"]})
    students = [api(client, "post", "/users", token=admin, json={
        "username": f"stu{i}", "password": "Test@123", "real_name": f"学生{i}", "role": "student",
        "class_id": cls["id"]}) for i in (1, 2, 3)]
    outsider = api(client, "post", "/users", token=admin, json={
        "username": "stu_out", "password": "Test@123", "real_name": "旁听生", "role": "student"})
    # 班主任归属本班（建档后由班级 head_teacher_id 关联）
    t1 = login(client, "teacher_wang")
    tl = login(client, "teacher_li")
    htok = login(client, "head1")
    s1, s2, s3 = [login(client, f"stu{i}") for i in (1, 2, 3)]
    s_out = login(client, "stu_out")

    st_menus = api(client, "get", "/auth/me", token=s1)["menus"]
    ad_menus = api(client, "get", "/auth/me", token=admin)["menus"]
    check("学生/管理员菜单按角色隔离", st_menus != ad_menus and "user-mgmt" in ad_menus)
    check("无 token 访问返回 401", expect_status(client, "get", "/courses", None, 401) == 401)
    check("学生建号被拒(403)",
          expect_status(client, "post", "/users", s1, 403,
                        json={"username": "x", "password": "y", "role": "admin"}) == 403)

    # ---------- 阶段2：建课 → 审核 → 选课 ----------
    print("\n[阶段2] 课程管理（建课/审核/选课）")
    course = api(client, "post", "/courses", token=t1, json={
        "title": "Python数据分析实战", "intro": "pandas/numpy 入门", "audience": "高三理科",
        "cover_url": "/img/c1.png",
        "chapters": [
            {"title": "第一章 数据准备", "children": [{"title": "1.1 环境搭建"}, {"title": "1.2 数据清洗"}]},
            {"title": "第二章 可视化", "children": [{"title": "2.1 图表"}]},
        ]})
    chapters = api(client, "get", f"/courses/{course['id']}", token=t1)["chapters"]
    check("讲师建课(2章3节共5条目)", course["status"] == "draft" and len(chapters) == 5)
    check("他人讲师不能审核(403)",
          expect_status(client, "put", f"/courses/{course['id']}/review", tl, 403,
                        json={"decision": "approve"}) == 403)
    check("未过审课程不能选课(409)",
          expect_status(client, "post", f"/courses/{course['id']}/enroll", t1, 409,
                        json={"class_id": cls["id"]}) == 409)
    api(client, "post", f"/courses/{course['id']}/submit-review", token=t1)
    reviewed = api(client, "put", f"/courses/{course['id']}/review", token=admin, json={"decision": "approve"})
    check("管理员审核通过 -> online", reviewed["status"] == "online")
    enrolled = api(client, "post", f"/courses/{course['id']}/enroll", token=t1, json={"class_id": cls["id"]})
    check("按班级批量选课 3 人（旁听生不选）", enrolled["enrolled"] == 3)
    check("未选课学生看课详情(403)",
          expect_status(client, "get", f"/courses/{course['id']}", s_out, 403) == 403)

    # ---------- 阶段3：排课与课表 ----------
    print("\n[阶段3] 直播排课")
    leaves = [c["id"] for c in chapters if c["parent_id"]]
    t_start = datetime.utcnow() + timedelta(days=1)
    sched = api(client, "post", "/schedules", token=t1, json={
        "chapter_id": leaves[0], "start_at": t_start.isoformat(),
        "end_at": (t_start + timedelta(hours=1)).isoformat(), "mode": "screen"})
    check("排课成功", sched["status"] == "planned")
    check("讲师时间冲突被拒(409)",
          expect_status(client, "post", "/schedules", t1, 409, json={
              "chapter_id": leaves[1],
              "start_at": (t_start + timedelta(minutes=30)).isoformat(),
              "end_at": (t_start + timedelta(hours=2)).isoformat()}) == 409)
    tt = api(client, "get", "/schedules/timetable", token=s1)
    check("学生课表可见已选课程直播", len(tt) == 1 and tt[0]["id"] == sched["id"])
    check("未选课学生课表为空", len(api(client, "get", "/schedules/timetable", token=s_out)) == 0)

    # ---------- 阶段4：直播 + 互动 ----------
    print("\n[阶段4] 直播授课与互动")
    room = api(client, "post", f"/schedules/{sched['id']}/start", token=t1)
    MEASURED["推流地址(SRS占位)"] = room["push_url"]
    check("开播生成直播间", room["status"] == "living")

    api(client, "post", f"/rooms/{room['room_id']}/messages", token=s1,
        json={"type": "danmaku", "content": "老师好"})
    q = api(client, "post", f"/rooms/{room['room_id']}/messages", token=s2,
            json={"type": "question", "content": "DataFrame去重怎么做？"})
    api(client, "post", f"/rooms/{room['room_id']}/messages/{q['id']}/answer", token=t1)
    msgs = api(client, "get", f"/rooms/{room['room_id']}/messages", token=t1)
    answered = [m for m in msgs if m["id"] == q["id"]][0]
    check("提问进入队列并被标记解答", answered["status"] == "answered")
    dm = [m for m in msgs if m["type"] == "danmaku"][0]
    api(client, "post", f"/rooms/{room['room_id']}/messages/{dm['id']}/recall", token=t1)
    msgs2 = api(client, "get", f"/rooms/{room['room_id']}/messages", token=s3)
    check("撤回的弹幕学生端不可见", all(m["id"] != dm["id"] for m in msgs2))
    check("未选课学生发弹幕被拒(403)",
          expect_status(client, "post", f"/rooms/{room['room_id']}/messages", s_out, 403,
                        json={"type": "danmaku", "content": "闯入"}) == 403)

    hr = api(client, "post", f"/rooms/{room['room_id']}/handraises", token=s2)
    api(client, "post", f"/rooms/{room['room_id']}/handraises/{hr['id']}/handle", token=t1,
        json={"action": "accept"})
    hrs = api(client, "get", f"/rooms/{room['room_id']}/handraises", token=t1)
    check("举手-接受连麦", hrs[0]["status"] == "accepted")

    rc = api(client, "post", f"/rooms/{room['room_id']}/rollcall", token=t1)
    api(client, "post", f"/rooms/{room['room_id']}/rollcall/respond", token=s1)
    api(client, "post", f"/rooms/{room['room_id']}/rollcall/respond", token=s2)
    rclose = api(client, "post", f"/rooms/{room['room_id']}/rollcall/close", token=t1,
                 json={"batch": rc["batch"]})
    MEASURED["点名"] = f"应到{rc['called']} 实到{rclose['present']} 缺{rclose['absent']}"
    check("点名：3应到2实到1缺", rc["called"] == 3 and rclose["present"] == 2 and rclose["absent"] == 1)

    vote = api(client, "post", f"/rooms/{room['room_id']}/votes", token=t1, json={
        "title": "讲解节奏满意度", "options": ["太快", "适中", "太慢"], "duration_seconds": 120})
    api(client, "post", f"/votes/{vote['id']}/cast", token=s1, json={"selected": [1]})
    api(client, "post", f"/votes/{vote['id']}/cast", token=s2, json={"selected": [2]})
    vr = api(client, "get", f"/votes/{vote['id']}/result", token=t1)
    MEASURED["投票"] = vr["result"]
    check("投票统计 2 人参与", vr["participants"] == 2 and vr["result"]["适中"] == 1
          and vr["result"]["太慢"] == 1)
    check("重复投票被拒(409)",
          expect_status(client, "post", f"/votes/{vote['id']}/cast", s1, 409,
                        json={"selected": [0]}) == 409)

    for _ in range(4):
        api(client, "post", f"/rooms/{room['room_id']}/heartbeat", token=s1, json={"seconds": 30})
    for _ in range(2):
        api(client, "post", f"/rooms/{room['room_id']}/heartbeat", token=s2, json={"seconds": 30})
    check("心跳单次时长上限校验(422)",
          expect_status(client, "post", f"/rooms/{room['room_id']}/heartbeat", s1, 422,
                        json={"seconds": 90}) == 422)

    stopped = api(client, "post", f"/rooms/{room['room_id']}/stop", token=t1)
    check("停播自动生成录制任务", stopped["recording_status"] == "transcoding")
    check("停播后心跳被拒(409)",
          expect_status(client, "post", f"/rooms/{room['room_id']}/heartbeat", s1, 409,
                        json={"seconds": 30}) == 409)

    # 第二场直播（无人观看，用于完课率计算）
    sched2 = api(client, "post", "/schedules", token=t1, json={
        "chapter_id": leaves[1], "start_at": utc(24 * 60 * 2), "end_at": utc(24 * 60 * 2 + 60),
        "mode": "video"})
    room2 = api(client, "post", f"/schedules/{sched2['id']}/start", token=t1)
    api(client, "post", f"/rooms/{room2['room_id']}/heartbeat", token=s2, json={"seconds": 30})
    stopped2 = api(client, "post", f"/rooms/{room2['room_id']}/stop", token=t1)
    check("第二场直播完成并生成录制", stopped2["recording_status"] == "transcoding")

    # ---------- 阶段5：录播回放 ----------
    print("\n[阶段5] 课程录播与回放")
    api(client, "post", f"/recordings/{stopped['recording_id']}/transcode", token=t1, json={"duration": 3600})
    rec = api(client, "get", f"/schedules/{sched['id']}/recording", token=s3)
    check("转码完成 HLS 就绪", rec["status"] == "ready" and rec["hls_url"])
    api(client, "put", f"/recordings/{rec['id']}/heartbeat", token=s3, json={"seconds": 30, "position": 900})
    rp = api(client, "put", f"/recordings/{rec['id']}/heartbeat", token=s3,
             json={"seconds": 30, "position": 1800})
    MEASURED["学生3回放"] = f"{rp['total_seconds']}s 断点{rp['last_position']}s"
    check("回放累计时长+断点续播", rp["total_seconds"] == 60 and rp["last_position"] == 1800)
    check("未选课学生拉回放被拒(403)",
          expect_status(client, "put", f"/recordings/{rec['id']}/heartbeat", s_out, 403,
                        json={"seconds": 30}) == 403)

    # ---------- 阶段6：作业 ----------
    print("\n[阶段6] 作业布置/提交/批改")
    as_future = api(client, "post", "/assignments", token=t1, json={
        "chapter_id": leaves[0], "title": "课后作业：清洗数据", "deadline": utc(24 * 60)})
    as_past = api(client, "post", "/assignments", token=t1, json={
        "chapter_id": leaves[0], "title": "补交练习", "deadline": utc(-60)})
    sub1 = api(client, "post", f"/assignments/{as_future['id']}/submissions", token=s1,
               json={"content": "清洗代码见附件"})
    sub2 = api(client, "post", f"/assignments/{as_past['id']}/submissions", token=s2,
               json={"content": "迟交内容"})
    check("按时提交标记为准时", sub1["is_late"] is False)
    check("逾期提交标记为补交", sub2["is_late"] is True)
    subs = api(client, "get", f"/assignments/{as_future['id']}/submissions", token=t1)
    check("未交名单 = 学生2/学生3", sorted(subs["missing"]) == sorted(["学生2", "学生3"]))
    reminded = api(client, "post", f"/assignments/{as_future['id']}/remind", token=t1)
    check("一键催发 2 人", reminded["reminded"] == 2)
    api(client, "put", f"/submissions/{subs['submitted'][0]['submission_id']}/grade", token=t1,
        json={"score": 90, "feedback": "清洗逻辑清晰"})
    check("已批改作业不可重交(409)",
          expect_status(client, "post", f"/assignments/{as_future['id']}/submissions", s1, 409,
                        json={"content": "再改一次"}) == 409)
    mine = api(client, "get", "/assignments/me", token=s1)
    check("学生端可见成绩与评语", any(a["score"] == 90 and a["feedback"] for a in mine))

    # ---------- 阶段7：考试 ----------
    print("\n[阶段7] 在线考试（组卷/答卷/自动判分/人工批改）")
    q_specs = [
        ("single", "pandas读取csv的函数?", ["read_csv", "read_json", "read_excel", "read_sql"], "0", 10),
        ("multiple", "哪些属于缺失值处理?", ["dropna", "fillna", "describe", "interpolate"], "0,1,3", 10),
        ("judge", "DataFrame是二维结构?", [], "T", 10),
        ("essay", "简述数据清洗流程", [], "", 20),
    ]
    qids = [api(client, "post", "/questions", token=t1, json={
        "course_id": course["id"], "type": tp, "stem": stem, "options": opts,
        "answer": ans, "score": sc})["id"] for tp, stem, opts, ans, sc in q_specs]
    exam = api(client, "post", "/exams", token=t1, json={
        "chapter_id": leaves[0], "title": "阶段测验一", "pass_score": 30, "duration": 45,
        "open_at": utc(-60), "close_at": utc(24 * 60), "question_ids": qids})
    check("组卷总分=50(10+10+10+20)", exam["total_score"] == 50)

    def answer_all(client, token, at, mapping):
        api(client, "put", f"/attempts/{at['attempt_id']}/answers", token=token,
            json={"answers": [{"exam_question_id": q["exam_question_id"],
                               "answer": mapping.get(q["type"], "")}
                              for q in at["questions"] if q["type"] in mapping]})

    # 学生1：客观全对+论述 -> 待批改
    at1 = api(client, "post", f"/exams/{exam['id']}/attempts/start", token=s1)
    answer_all(client, s1, at1, {"single": "0", "multiple": "0,1,3", "judge": "T", "essay": "缺失->异常->标准化"})
    sub_at1 = api(client, "post", f"/attempts/{at1['attempt_id']}/submit", token=s1)
    check("含主观题 -> 待人工批改", sub_at1["status"] == "submitted")

    # 学生2：只答对判断题
    at2 = api(client, "post", f"/exams/{exam['id']}/attempts/start", token=s2)
    answer_all(client, s2, at2, {"single": "1", "multiple": "1,2", "judge": "T"})
    sub_at2 = api(client, "post", f"/attempts/{at2['attempt_id']}/submit", token=s2)
    check("客观题自动判分：仅答对判断题得10分", sub_at2["objective_score"] == 10)

    # 学生3：客观全对
    at3 = api(client, "post", f"/exams/{exam['id']}/attempts/start", token=s3)
    answer_all(client, s3, at3, {"single": "0", "multiple": "0,1,3", "judge": "T", "essay": "完整流程论述"})
    sub_at3 = api(client, "post", f"/attempts/{at3['attempt_id']}/submit", token=s3)
    check("学生3客观满分30", sub_at3["objective_score"] == 30)

    check("重复开考被拒(409)",
          expect_status(client, "post", f"/exams/{exam['id']}/attempts/start", s1, 409) == 409)
    check("代答他人试卷被拒(403)",
          expect_status(client, "put", f"/attempts/{at2['attempt_id']}/answers", s1, 403,
                        json={"answers": []}) == 403)

    atts = api(client, "get", f"/exams/{exam['id']}/attempts", token=t1)
    graded = {}
    for a in atts:
        if a["status"] == "submitted":
            manual = 15 if a["student"] == "学生1" else 18
            g = api(client, "put", f"/attempts/{a['attempt_id']}/grade", token=t1,
                    json={"manual_score": manual})
            graded[a["student"]] = g["score"]
    MEASURED["考试成绩"] = f"学生1={graded.get('学生1')} 学生2={graded.get('学生2')} 学生3={graded.get('学生3')}"
    check("人工批改后成绩=客观+主观", graded.get("学生1") == 45 and graded.get("学生3") == 48)
    check("学生不能改分(403)",
          expect_status(client, "put", f"/attempts/{at3['attempt_id']}/grade", s1, 403,
                        json={"manual_score": 5}) == 403)

    # ---------- 阶段8：学习进度 ----------
    print("\n[阶段8] 学习进度跟踪")
    prog1 = api(client, "get", "/me/progress", token=s1)[0]
    MEASURED["学生1进度"] = {k: prog1[k] for k in
                             ("watch_minutes", "attendance_rate", "assignments_submitted",
                              "assignment_avg", "exam_avg", "progress_pct")}
    check("学生1观看时长=2.0分钟(120s直播)", prog1["watch_minutes"] == 2.0)
    check("学生1出勤率 100%", prog1["attendance_rate"] == 100.0)
    check("学生1考试45分/完课率50%(1/2节)", prog1["exam_avg"] == 45 and prog1["progress_pct"] == 50.0)
    prog2 = [p for p in api(client, "get", "/courses/%s/progress" % course["id"], token=t1)
             if p["real_name"] == "学生2"][0]
    check("学生2观看1.5分钟/完课100%", prog2["watch_minutes"] == 1.5 and prog2["progress_pct"] == 100.0)
    prog_all = api(client, "get", f"/courses/{course['id']}/progress", token=t1)
    check("教师可见3名选课学生进度", len(prog_all) == 3)
    # 班主任需 class 关联：修正 head_teacher 数据范围（按本班选课学生）
    cls_prog = api(client, "get", f"/classes/{cls['id']}/progress", token=htok)
    check("班主任本班进度 3 名学生", len(cls_prog["rows"]) == 3)
    check("其他讲师不可见该课数据(403)",
          expect_status(client, "get", f"/courses/{course['id']}/progress", tl, 403) == 403)

    # ---------- 阶段9：统计与导出 ----------
    print("\n[阶段9] 统计看板与报表导出")
    statsd = api(client, "get", f"/stats/courses/{course['id']}", token=t1)
    MEASURED["课程统计"] = {"participation": statsd["participation"],
                        "grade_distribution": statsd["grade_distribution"],
                        "watch_minutes": statsd["total_watch_minutes"]}
    check("参与度：弹幕1/提问1/举手1/投票2",
          statsd["participation"]["danmaku"] == 1 and statsd["participation"]["question"] == 1
          and statsd["participation"]["handraise"] == 1 and statsd["participation"]["votes_cast"] == 2)
    check("成绩分布非空", sum(statsd["grade_distribution"].values()) > 0)
    ov = api(client, "get", "/stats/overview", token=admin)
    MEASURED["平台总览"] = {k: ov[k] for k in ("courses_online", "schedules_finished", "live_minutes",
                                    "total_watch_minutes", "interactions")}
    check("总览：2场已完成直播/4名学生", ov["schedules_finished"] == 2 and ov["students"] == 4)
    check("学生访问课程统计被拒(403)",
          expect_status(client, "get", f"/stats/courses/{course['id']}", s1, 403) == 403)

    r_x = client.get(BASE + f"/stats/export?report=course_progress&course_id={course['id']}&format=xlsx",
                     headers={"Authorization": f"Bearer {t1}"})
    check("导出 xlsx HTTP 200", r_x.status_code == 200)
    ws = load_workbook(io.BytesIO(r_x.content)).active
    MEASURED["xlsx行数"] = ws.max_row
    check("xlsx 含表头+3行学生", ws.max_row == 4 and ws.cell(2, 1).value in ("学生1", "学生2", "学生3"))
    r_c = client.get(BASE + f"/stats/export?report=course_progress&course_id={course['id']}&format=csv",
                     headers={"Authorization": f"Bearer {t1}"})
    text = r_c.content.decode("utf-8-sig")
    check("csv 4 行且带 BOM(Excel兼容)", len(text.strip().splitlines()) == 4
          and r_c.content[:3] == b"\xef\xbb\xbf")
    logs = api(client, "get", "/stats/exports", token=admin)
    check("导出留痕 2 条", len(logs) == 2)
    check("未授权导出被拒(403)",
          expect_status(client, "get",
                        f"/stats/export?report=course_progress&course_id={course['id']}", s_out, 403) == 403)

    # ---------- 阶段10：通知 ----------
    print("\n[阶段10] 消息通知")
    n3 = api(client, "get", "/me/notifications", token=s3)
    MEASURED["学生3未读通知"] = n3["unread"]
    check("学生3收到催交通知", n3["unread"] >= 1)
    api(client, "post", "/me/notifications/read", token=s3)
    check("全部已读生效", api(client, "get", "/me/notifications", token=s3)["unread"] == 0)


if __name__ == "__main__":
    main()
