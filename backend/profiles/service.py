"""Lesson-one HTTP application; public auth and private assessment are separate."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time

from .coze import UpstreamError
from .scoring import (ENTRY_QUESTIONS, MAIN_BOT_ID, Questionnaire,
                      ValidationError, identity, needs_model, pending_review, score, score_semantic)


class HTTPError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


class ProfileApplication:
    def __init__(self, store, assessor, auth, identity_secret, admin_key, plugin_key,
                 origin="https://test.homura.cn", school="caitian", clock=time.time, variable_writer=None):
        keys = (identity_secret, admin_key) + ((plugin_key,) if plugin_key is not None else ())
        if any(not isinstance(key, str) or len(key) < 32 for key in keys):
            raise ValueError("Independent server secrets of at least 32 characters are required")
        if len(set(keys)) != len(keys):
            raise ValueError("Keys must have separate purposes")
        self.store, self.assessor, self.auth = store, assessor, auth
        self.identity_secret = identity_secret.encode()
        self.admin_key, self.plugin_key = admin_key, plugin_key
        self.origin, self.school, self.clock = origin, school, clock
        self.variable_writer = variable_writer

    def learner_key(self, class_no, student_no):
        value = f"{self.school}:{class_no}:{student_no}".encode()
        return hmac.new(self.identity_secret, value, hashlib.sha256).hexdigest()

    @staticmethod
    def check_key(headers, name, expected):
        supplied = headers.get(name, "")
        if not isinstance(supplied, str) or not hmac.compare_digest(supplied, expected):
            raise HTTPError(401, "UNAUTHORIZED", "未授权")

    @staticmethod
    def ticket_key(ticket):
        if not isinstance(ticket, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", ticket):
            raise HTTPError(401, "INVALID_PROFILE_REF", "会话标识无效，请重新进入课堂")
        return hashlib.sha256(ticket.encode()).hexdigest()

    def get_ticket(self, ticket):
        value = self.store.get("tickets", self.ticket_key(ticket))
        if not value or value.get("expires_at", 0) <= self.clock():
            raise HTTPError(401, "PROFILE_REF_EXPIRED", "会话已过期，请重新进入课堂")
        return value

    def assess(self, body):
        questionnaire = Questionnaire.parse(body, self.school)
        key = self.learner_key(questionnaire.class_no, questionnaire.student_no)
        old = self.store.get("profiles", key)
        if old and old["source_digest"] == questionnaire.digest:
            return self.admin_summary(old, unchanged=True)
        if old and body.get("replace_digest") != old["source_digest"]:
            raise HTTPError(409, "EXISTING_PROFILE", "该学生已有不同问卷；复核后携带 replace_digest 再导入")
        record = self.grade_questionnaire(questionnaire)
        record["updated_at"] = int(self.clock())
        record["reviewed_by_teacher"] = False
        self.store.put("profiles", key, record)
        return self.admin_summary(record)

    def grade_questionnaire(self, questionnaire):
        try:
            assessment = self.assessor.assess(questionnaire) if needs_model(questionnaire) else None
            record = (score_semantic(questionnaire, assessment)
                      if isinstance(assessment, dict) and assessment.get('source') == 'coze_semantic_dimensions'
                      else score(questionnaire, assessment))
        except ValidationError:
            record = pending_review(questionnaire)
        return record

    @staticmethod
    def student_identity(body):
        user_id = body.get('user_id')
        matched = re.fullmatch(r'([1-8])班_([1-9]|[1-4][0-9]|5[0-5])_1', user_id) if isinstance(user_id, str) else None
        if not matched:
            raise ValidationError('仅支持彩田学校1至8班、1至55号、第1课次')
        return matched.groups()

    def questionnaire_status(self, body):
        key = self.learner_key(*self.student_identity(body))
        record = self.store.get('profiles', key)
        if record:
            return {'status': 'ready' if record.get('status') == 'ready' else 'needs_review'}
        submission = self.store.get('submissions', key)
        if submission:
            return {'status': 'processing' if self.clock() - submission['submitted_at'] < 120 else 'needs_review'}
        return {'status': 'missing'}

    def submit_questionnaire(self, body):
        class_no, student_no = self.student_identity(body)
        questionnaire = Questionnaire.parse({'class_no': class_no, 'student_no': student_no,
                                            'answers': body.get('answers')}, self.school)
        answers = questionnaire.answers
        if any(not answers.get(f'q{q}') for q in (3, 4, 5, 7, 8, 9, 10, 11)):
            raise ValidationError('请完成必答题；不知道时可以如实选择或填写不知道')
        tools_used = answers['q3'].split(',')
        if (any(x not in 'ABCDE' or len(x) != 1 for x in tools_used)
                or len(set(tools_used)) != len(tools_used) or ('A' in tools_used and len(tools_used) != 1)
                or answers['q4'] not in ('A', 'B', 'C', 'D')):
            raise ValidationError('AI工具或使用次数选项无效')
        key = self.learner_key(class_no, student_no)
        current = self.questionnaire_status(body)
        if current['status'] != 'missing':
            return current
        submission = {'class_no': class_no, 'student_no': student_no, 'answers': answers,
                      'source_digest': questionnaire.digest, 'submitted_at': int(self.clock())}
        if not self.store.create('submissions', key, submission):
            return self.questionnaire_status(body)
        try:
            record = self.grade_questionnaire(questionnaire)
        except UpstreamError:
            record = pending_review(questionnaire)
            record['assessment']['reason'] = '问卷已保存，判级服务暂不可用，需教师复核或重新处理'
        record.update(updated_at=int(self.clock()), reviewed_by_teacher=False, source='student_web')
        # A teacher may have imported/reviewed the profile while grading was running.
        self.store.create('profiles', key, record)
        return self.questionnaire_status(body)

    @staticmethod
    def admin_summary(record, unchanged=False):
        return {key: record[key] for key in (
            "class_no", "student_no", "status", "source_digest", "preconception", "total", "open_points"
        )} | {"unchanged": unchanged}

    def review(self, body):
        class_no = identity(body.get("class_no"), 8, "班级")
        student_no = identity(body.get("student_no"), 55, "学号")
        key = self.learner_key(class_no, student_no)
        old = self.store.get("profiles", key) or self.submission_for_review(key)
        if not old or body.get("source_digest") != old["source_digest"]:
            raise HTTPError(409, "STALE_REVIEW", "问卷不存在或已更新，请重新读取后复核")
        assessment = body.get("assessment")
        if not isinstance(assessment, dict) or assessment.get("confidence") != 1:
            raise ValidationError("教师复核需要明确的类别、原文证据、理由和confidence=1")
        record = score(Questionnaire.parse(old, self.school), assessment)
        record.update(updated_at=int(self.clock()), reviewed_by_teacher=True)
        self.store.put("profiles", key, record)
        return self.admin_summary(record)

    def read_profile(self, body):
        class_no = identity(body.get("class_no"), 8, "班级")
        student_no = identity(body.get("student_no"), 55, "学号")
        key = self.learner_key(class_no, student_no)
        record = self.store.get("profiles", key) or self.submission_for_review(key)
        if not record:
            raise HTTPError(404, "PROFILE_NOT_FOUND", "未找到该问卷")
        return record

    def regrade(self, body):
        old = self.read_profile(body)
        if old['source_digest'] != body.get('source_digest'):
            raise HTTPError(409, 'STALE_REVIEW', '问卷已更新，请重新读取后再由AI判定')
        record = self.grade_questionnaire(Questionnaire.parse(old, self.school))
        record.update(updated_at=int(self.clock()), reviewed_by_teacher=False, source='ai_regrade')
        self.store.put('profiles', self.learner_key(record['class_no'], record['student_no']), record)
        return self.admin_summary(record)

    def submission_for_review(self, key):
        submission = self.store.get('submissions', key)
        if not submission:
            return None
        record = pending_review(Questionnaire.parse(submission, self.school))
        record.update(updated_at=submission['submitted_at'], reviewed_by_teacher=False, source='student_web')
        return record

    def issue_auth(self, body):
        user_id = body.get("user_id", "")
        if not isinstance(user_id, str):
            raise ValidationError("学生标识无效")
        matched = re.fullmatch(r"([1-8])班_([1-9]|[1-4][0-9]|5[0-5])_1", user_id)
        if not matched:
            raise ValidationError("仅支持彩田学校1至8班、1至55号、第1课次")
        key = self.learner_key(*matched.groups())
        record = self.store.get("profiles", key)
        if not record or record.get("status") != "ready":
            # Do not leak whether a student's survey is missing, ambiguous or low scoring.
            raise HTTPError(409, "PROFILE_NOT_READY", "课前资料尚未准备好，请联系老师")
        existing = body.get("profile_ref")
        if existing:
            ticket = self.get_ticket(existing)
            if ticket["learner_key"] != key:
                raise HTTPError(403, "IDENTITY_MISMATCH", "学生身份与会话不匹配")
        result = self.auth.issue(user_id)
        if existing and ticket["coze_user_id"] != result["user_id_hash"]:
            raise HTTPError(403, "IDENTITY_MISMATCH", "鉴权身份已变化，请重新进入课堂")
        if self.variable_writer and not existing:
            self.variable_writer.initialize(result, int(record['preconception'][1:]))
        profile_ref = existing or secrets.token_urlsafe(32)
        self.store.put("tickets", self.ticket_key(profile_ref), {
            "learner_key": key, "coze_user_id": result["user_id_hash"], "lesson": 1,
            "expires_at": int(self.clock()) + 4 * 60 * 60,
        })
        # Only opaque references and the pre-existing channel token reach the browser.
        return result | {"profile_ref": profile_ref, "bot_id": MAIN_BOT_ID}

    def resolve(self, body):
        ticket = self.get_ticket(body.get("profile_ref"))
        record = self.store.get("profiles", ticket["learner_key"])
        if not record or record.get("status") != "ready":
            raise HTTPError(409, "PROFILE_NOT_READY", "课前资料未就绪")
        level = record["preconception"]
        # No raw questionnaires, score breakdown, class or student numbers leave this service.
        return {"lesson": 1, "preconception": level, "P0": int(level[1:]), "Pn": int(level[1:]),
                "profile_ready": True,
                "entry_question": ENTRY_QUESTIONS[level], "rubric_version": record["rubric_version"]}

    def handle(self, event):
        request_headers = {str(k).lower(): str(v) for k, v in (event.get("headers") or {}).items()}
        origin = request_headers.get("origin")
        headers = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store",
                   "X-Content-Type-Options": "nosniff", "Vary": "Origin"}
        if origin == self.origin:
            headers["Access-Control-Allow-Origin"] = self.origin
            headers["Access-Control-Allow-Headers"] = "Content-Type"
            headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        try:
            method = event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method", "")
            path = (event.get("path") or event.get("rawPath") or "/").rstrip("/") or "/"
            if origin and origin != self.origin:
                raise HTTPError(403, "ORIGIN_DENIED", "来源不被允许")
            public_paths = {'/auth', '/questionnaire/status', '/questionnaire/submit'}
            if method == "OPTIONS" and path in public_paths:
                return {"statusCode": 204, "headers": headers, "body": "", "isBase64Encoded": False}
            if method == "GET" and path == "/health":
                return self.response(200, {"ok": True, "service": "lesson-one-profiles"}, headers)
            if method != "POST":
                raise HTTPError(405, "METHOD_NOT_ALLOWED", "不支持该请求方法")
            if path.startswith("/admin/"):
                self.check_key(request_headers, "x-admin-key", self.admin_key)
            elif path == "/internal/profile":
                if self.plugin_key is None:
                    raise HTTPError(404, 'NOT_FOUND', '接口未启用')
                self.check_key(request_headers, "x-coze-plugin-key", self.plugin_key)
            elif path not in public_paths:
                raise HTTPError(404, "NOT_FOUND", "接口不存在")
            raw = event.get("body") or "{}"
            if not isinstance(raw, str) or len(raw) > 70000:
                raise HTTPError(413, "TOO_LARGE", "单次只支持一份问卷")
            if event.get("isBase64Encoded"):
                raw = base64.b64decode(raw, validate=True).decode("utf-8")
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValidationError("请求体必须是JSON对象")
            routes = {"/auth": self.issue_auth, "/internal/profile": self.resolve,
                      "/admin/questionnaires": self.assess, "/admin/review": self.review,
                      "/admin/profile": self.read_profile,
                      '/admin/regrade': self.regrade,
                      '/questionnaire/status': self.questionnaire_status,
                      '/questionnaire/submit': self.submit_questionnaire}
            if path not in routes:
                raise HTTPError(404, "NOT_FOUND", "接口不存在")
            result = routes[path](body)
            return self.response(200, {"data": result}, headers)
        except HTTPError as exc:
            return self.response(exc.status, {"error": {"code": exc.code, "message": exc.message}}, headers)
        except (ValidationError, ValueError, UnicodeDecodeError) as exc:
            message = str(exc) if isinstance(exc, ValidationError) else "请求内容格式无效"
            return self.response(422, {"error": {"code": "INVALID_INPUT", "message": message}}, headers)
        except UpstreamError as exc:
            return self.response(502, {"error": {"code": "UPSTREAM_UNAVAILABLE", "message": str(exc)}}, headers)
        except Exception:
            # No questionnaires, tokens, internal traces or credential-bearing URLs in public responses.
            return self.response(503, {"error": {"code": "SERVICE_UNAVAILABLE", "message": "服务暂时不可用，请稍后重试"}}, headers)

    @staticmethod
    def response(status, body, headers):
        return {"statusCode": status, "headers": headers, "isBase64Encoded": False,
                "body": json.dumps(body, ensure_ascii=False)}
