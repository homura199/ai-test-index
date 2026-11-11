"""Versioned preconception rubric. P0-P3 are NOT SOLO levels."""
import hashlib
import json
import re
from dataclasses import dataclass

RUBRIC_VERSION = "preconcept-2026-11-06-v1"
MAIN_BOT_ID = "7706348792413011968"
ASSESSMENT_BOT_ID = "7706346907417362432"
SCORED_QUESTIONS = (5, 7, 8, 9, 10)
OPTION_POINTS = {5: (2, 4, 6, 0), 7: (2, 4, 6, 0), 8: (2, 4, 6, 0),
                 9: (4, 6, 2, 0), 10: (2, 4, 6, 0)}
OPTIONS = {
    5: ("AI脑子里有想法，自己构思出来的", "AI在网上搜到最像的图，改一改就给你",
        "AI以前看过很多猫和宇航服的照片，记住了它们的样子，再拼出一个新的", "我也说不清"),
    7: ("能，它很聪明，能自己想象出来", "不能，网上没有这张图，它找不到",
        "能，它学过企鹅和帽子长什么样，可以把两者组合起来", "不知道"),
    8: ("像人一样有天赋，练着练着就会了", "像一个超大的图片仓库，要什么就去里面拿",
        "像一个学生，看了很多范画，总结出规律，自己画", "不知道"),
    9: ("AI记性特别好，把看过的画都记住了", "AI学习时看的这类画特别多，所以画出来就像",
        "AI故意模仿那张画", "说不清"),
    10: ("它有艺术天赋", "它数据库里的图多", "它看过很多画，学到了画得好的规律", "说不清"),
}
CATEGORY_POINTS = {"pattern_generation": 70, "retrieval": 40,
                   "anthropomorphic": 20, "mixed": 30, "unscorable": None}
ENTRY_QUESTIONS = {
    "P0": "它第一次画鸡蛋，画成了一团乱线。它那时候知道鸡蛋长什么样吗？",
    "P1": "它第一次画鸡蛋，画成了一团乱线。它那时候知道鸡蛋长什么样吗？",
    "P2": "有人猜它是去图库里找一张最像的贴上去。你觉得有道理吗？要是图库里没有这张呢？",
    "P3": "你说它是看了很多鸡蛋学出来的。那它画完一张，怎么知道自己画得像不像？谁告诉它的？",
}


class ValidationError(ValueError):
    pass


def normalize_text(value):
    return re.sub(r"[\s，,。.!！?？、:：;；\"“”‘’'（）()]", "", str(value)).lower()


def normalize_choice(question, value):
    """When option text is present, score its meaning even if its letter was reordered."""
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"[ABCDabcd]", text):
        return text.upper()
    text = re.sub(r"^[ABCDabcd]\s*[、.．:：)）]\s*", "", text)
    normalized = normalize_text(text)
    for index, content in enumerate(OPTIONS[question]):
        if normalize_text(content) == normalized:
            return "ABCD"[index]
    raise ValidationError(f"第{question}题选项无法识别；请使用原问卷完整选项或 A/B/C/D")


def identity(value, maximum, label):
    if isinstance(value, bool):
        raise ValidationError(f"{label}必须是整数")
    text = str(value).strip()
    if not re.fullmatch(r"[0-9]+(?:\.0)?", text):
        raise ValidationError(f"{label}必须是整数")
    number = int(text.removesuffix('.0'))
    if not 1 <= number <= maximum:
        raise ValidationError(f"{label}超出范围")
    return str(number)


@dataclass(frozen=True)
class Questionnaire:
    school: str
    class_no: str
    student_no: str
    answers: dict

    @classmethod
    def parse(cls, payload, school="caitian"):
        if not isinstance(payload, dict) or not isinstance(payload.get("answers"), dict):
            raise ValidationError("需要 class_no、student_no 和 answers 对象")
        if payload.get("school", school) != school:
            raise ValidationError("学校标识不匹配")
        answers = {}
        for number in range(3, 13):
            key = f"q{number}"
            value = payload["answers"].get(key, "")
            if value is None:
                value = ""
            if not isinstance(value, (str, int, float)) or len(str(value)) > 4000:
                raise ValidationError(f"{key}内容无效或过长")
            answers[key] = normalize_choice(number, value) if number in SCORED_QUESTIONS else str(value).strip()
        return cls(school, identity(payload.get("class_no"), 8, "班级"),
                   identity(payload.get("student_no"), 55, "学号"), answers)

    @property
    def digest(self):
        data = {"school": self.school, "class_no": self.class_no,
                "student_no": self.student_no, "answers": self.answers, "rubric": RUBRIC_VERSION}
        return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def validate_assessment(result, questionnaire):
    expected = {"category", "confidence", "evidence", "reason"}
    if not isinstance(result, dict) or set(result) != expected:
        raise ValidationError("评级智能体必须返回规定的 JSON 对象，不能返回分数或 P 等级")
    if not isinstance(result["category"], str) or result["category"] not in CATEGORY_POINTS:
        raise ValidationError("开放题类别不合法")
    confidence = result["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValidationError("置信度必须在0到1之间")
    if not isinstance(result["reason"], str) or not 1 <= len(result["reason"]) <= 1000:
        raise ValidationError("需要简短的判定依据")
    evidence = result["evidence"]
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 4:
        raise ValidationError("需要第11题中的原文证据")
    if any(not isinstance(quote, str) or not quote.strip() or quote not in questionnaire.answers["q11"] for quote in evidence):
        raise ValidationError("证据必须逐字来自第11题，不能编造或使用第6题替代")
    if result["category"] == "mixed" and len(set(evidence)) < 2:
        raise ValidationError("混合类别需要两条不同的原文证据")
    return result


def score(questionnaire, assessment, minimum_confidence=0.8):
    objective = {
        f"q{q}": (OPTION_POINTS[q]["ABCD".index(questionnaire.answers[f"q{q}"])]
                  if questionnaire.answers[f"q{q}"] else 0)
        for q in SCORED_QUESTIONS
    }
    raw = questionnaire.answers["q11"]
    if not raw.strip():
        assessment = {"category": "unscorable", "confidence": 1.0,
                      "evidence": [raw] if raw else [], "reason": "空白开放题不打分"}
    else:
        assessment = validate_assessment(assessment, questionnaire)
    ready = assessment["confidence"] >= minimum_confidence
    open_points = CATEGORY_POINTS[assessment["category"]] if ready else None
    total = sum(objective.values()) + (open_points or 0) if ready else None
    level = None if total is None else "P0" if total < 20 else "P1" if total < 45 else "P2" if total < 75 else "P3"
    return {
        "rubric_version": RUBRIC_VERSION, "source_digest": questionnaire.digest,
        "school": questionnaire.school, "class_no": questionnaire.class_no,
        "student_no": questionnaire.student_no, "status": "ready" if ready else "needs_review",
        "objective_points": objective, "open_points": open_points,
        "total": total, "preconception": level, "assessment": assessment,
        "answers": questionnaire.answers,
    }


def needs_model(questionnaire):
    # Every non-empty free response, including "不知道", goes to the AI.
    return bool(questionnaire.answers["q11"].strip())


def pending_review(questionnaire):
    """Keep a malformed model result out of teaching, but retain the survey for review."""
    record = score(questionnaire, {"category": "unscorable", "confidence": 0,
                                  "evidence": [questionnaire.answers["q11"]],
                                  "reason": "智能体返回格式或原文证据未通过校验，需教师复核"})
    return record


def score_semantic(questionnaire, assessment):
    """Convert AI decisions to rubric points; never inspect answer keywords.

    All three judgments are required so mixed viewpoints receive 30 points.
    Six-field outputs cannot supply calibrated confidence or extracted evidence.
    Raw AI decisions and original answers are retained for private audit instead.
    """
    targets = {'anthropomorphic': 1, 'retrieval': 2, 'pattern_generation': 3}
    decisions = assessment.get('decisions')
    if not isinstance(decisions, dict) or set(decisions) != set(targets):
        raise ValidationError('AI必须完成三个前概念维度的判定')
    affirmed, trace = [], {}
    for name, target in targets.items():
        variables = decisions[name]
        if not isinstance(variables, dict) or set(variables) != {'P0', 'Pn', 'L0', 'Ln', 'K0', 'Kn'}:
            raise ValidationError('既有判级结果必须包含六个等级字段')
        values = {}
        for key, value in variables.items():
            if isinstance(value, bool) or not re.fullmatch(r'[0-5]', str(value)):
                raise ValidationError('既有判级结果的等级值无效')
            values[key] = int(value)
        if values['P0'] != 0 or values['Pn'] not in (0, target):
            raise ValidationError('判级智能体未遵循当前维度的独立核查协议')
        if any(values[k] != 1 for k in ('L0', 'Ln', 'K0', 'Kn')):
            raise ValidationError('课前核查不得混入对话SOLO等级')
        trace[name] = values
        if values['Pn'] == target:
            affirmed.append(name)
    category = 'mixed' if len(affirmed) > 1 else affirmed[0] if affirmed else 'unscorable'
    record = pending_review(questionnaire)
    points = CATEGORY_POINTS[category]
    total = sum(record['objective_points'].values()) + (points or 0)
    record.update(status='ready', open_points=points, total=total,
                  preconception='P0' if total < 20 else 'P1' if total < 45 else 'P2' if total < 75 else 'P3')
    record['assessment'] = {'source': 'coze_semantic_dimensions', 'decisions': trace,
        'category': category, 'confidence': None,
        'reason': '隐藏判级智能体逐维度语义判断，后台仅合并类别并按问卷计分'}
    return record
