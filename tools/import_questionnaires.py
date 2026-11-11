"""Teacher-only XLSX ingestion. Validates the whole file before sending any row.

Usage: python tools/import_questionnaires.py input.xlsx --base-url https://... --dry-run
       python tools/import_questionnaires.py --template .private/questionnaire-template.xlsx
The admin key is read from XIAOHUA_ADMIN_KEY or an interactive hidden prompt.
"""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.profiles.scoring import Questionnaire, ValidationError

FIELDS = ["class_no", "student_no"] + [f"q{i}" for i in range(3, 13)]
REQUIRED = {"class_no", "student_no", "q5", "q7", "q8", "q9", "q10", "q11"}


def field_name(header):
    text = str(header or "").strip()
    if text in FIELDS:
        return text
    if text in ("班级", "你的班级", "所在班级"):
        return "class_no"
    if text in ("学号", "你的学号", "学生学号"):
        return "student_no"
    match = re.match(r"^(?:第\s*)?(\d{1,2})\s*(?:[、.．:：]|题)", text)
    if match:
        number = int(match.group(1))
        return {1: "class_no", 2: "student_no"}.get(number, f"q{number}" if 3 <= number <= 12 else None)
    return None


def read_xlsx(path, mapping=None):
    from openpyxl import load_workbook
    path = Path(path)
    if mapping is not None and (not isinstance(mapping, dict) or any(value not in FIELDS for value in mapping.values())):
        raise ValidationError("列映射必须是Excel列名到标准字段名的JSON对象")
    if path.suffix.lower() != ".xlsx" or path.stat().st_size > 8 * 1024 * 1024:
        raise ValidationError("仅接受8MB以内的xlsx文件")
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 2000 or sum(e.file_size for e in entries) > 64 * 1024 * 1024:
            raise ValidationError("Excel解压后过大")
    workbook = load_workbook(path, read_only=True, data_only=False, keep_links=False)
    try:
        sheet = workbook.active
        if sheet.max_row > 1001 or sheet.max_column > 100:
            raise ValidationError("最多1000行学生记录、100列，请去掉空白区域格式后重试")
        iterator = sheet.iter_rows()
        header_cells = next(iterator, ())
        columns = {}
        for index, cell in enumerate(header_cells):
            header = str(cell.value or "").strip()
            key = mapping.get(header) if mapping is not None else field_name(header)
            if key in FIELDS:
                if key in columns.values():
                    raise ValidationError(f"重复字段：{key}")
                columns[index] = key
        missing = REQUIRED - set(columns.values())
        if missing:
            raise ValidationError("缺少列：" + ", ".join(sorted(missing)))
        rows, identities = [], set()
        for row_number, cells in enumerate(iterator, 2):
            if all(cell.value is None for cell in cells):
                continue
            if any(cell.data_type == "f" for cell in cells):
                raise ValidationError(f"第{row_number}行包含公式，请粘贴为值")
            values = {key: cells[i].value for i, key in columns.items()}
            payload = {"class_no": values["class_no"], "student_no": values["student_no"],
                       "answers": {key: value for key, value in values.items() if key.startswith("q")}}
            try:
                questionnaire = Questionnaire.parse(payload)
            except ValidationError as exc:
                raise ValidationError(f"第{row_number}行：{exc}") from exc
            identity_key = (questionnaire.class_no, questionnaire.student_no)
            if identity_key in identities:
                raise ValidationError(f"第{row_number}行班级学号重复；请先确定保留哪一份问卷")
            identities.add(identity_key)
            rows.append({"class_no": questionnaire.class_no, "student_no": questionnaire.student_no,
                         "answers": questionnaire.answers})
        if not rows:
            raise ValidationError("没有学生记录")
        return rows
    finally:
        workbook.close()


def write_template(path):
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.worksheet.datavalidation import DataValidation
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "课前问卷"
    sheet.append(FIELDS)
    sheet.freeze_panes = "C2"
    descriptions = {
        "class_no": "班级1至8", "student_no": "学号1至55", "q3": "用过的AI绘图工具，不计分",
        "q4": "使用次数，不计分", "q5": "穿宇航服的猫", "q6": "第5题理由，仅参考不计分",
        "q7": "戴帽子的企鹅", "q8": "AI学画更像哪一种", "q9": "画得几乎一样（选项顺序特殊）",
        "q10": "AI画得好看的原因", "q11": "AI画的画从哪里来（必须保留此列，未作答可空）", "q12": "教AI画鸡蛋（选做，不计分）",
    }
    for cell in sheet[1]:
        cell.comment = Comment(descriptions[cell.value], "问卷导入说明")
        sheet.column_dimensions[cell.column_letter].width = 42 if cell.value in ("q6", "q11", "q12") else 20
        if cell.value in ("q5", "q7", "q8", "q9", "q10"):
            rule = DataValidation(type="list", formula1='"A,B,C,D"', allow_blank=True)
            rule.error = "请选择原问卷对应的 A、B、C 或 D"
            rule.showErrorMessage = True
            sheet.add_data_validation(rule)
            rule.add(f"{cell.column_letter}2:{cell.column_letter}1001")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(target)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValidationError("导入接口不应重定向，请检查服务地址")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("xlsx", nargs="?")
    parser.add_argument("--template")
    parser.add_argument("--mapping", help="JSON map from exact Excel column name to canonical field")
    parser.add_argument("--base-url")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", default=".private/import-report.json")
    args = parser.parse_args()
    if args.template:
        write_template(args.template)
        print("问卷模板已生成（不含学生数据）")
        return
    if not args.xlsx:
        parser.error("需要xlsx文件或--template")
    mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8")) if args.mapping else None
    rows = read_xlsx(args.xlsx, mapping)
    print(f"格式验证通过：{len(rows)}份问卷")
    if args.dry_run:
        return
    parsed = urllib.parse.urlsplit(args.base_url or "")
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
        parser.error("--base-url必须是后台HTTPS地址，不可带查询参数或凭据")
    admin_key = os.environ.get("XIAOHUA_ADMIN_KEY") or getpass.getpass("后台导入密钥（隐藏输入）: ")
    if len(admin_key) < 32:
        parser.error("后台导入密钥至少32字符")
    opener = urllib.request.build_opener(NoRedirect())
    results = []
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows, 1):
        request = urllib.request.Request(args.base_url.rstrip("/") + "/admin/questionnaires",
            data=json.dumps(row, ensure_ascii=False).encode(),
            headers={"X-Admin-Key": admin_key, "Content-Type": "application/json"})
        try:
            with opener.open(request, timeout=100) as response:
                result = json.loads(response.read(32768))["data"]
        except urllib.error.HTTPError as exc:
            # Only these codes/messages are emitted by our own backend; do not dump request bodies or keys.
            result = {"class_no": row["class_no"], "student_no": row["student_no"],
                      "status": "failed", "http_status": exc.code}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            result = {"class_no": row["class_no"], "student_no": row["student_no"], "status": "failed"}
        results.append(result)
        report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{index}/{len(rows)}：{result['status']}")
        if result["status"] == "failed":
            print("已停止导入；报告已保存，修复后可重跑，已成功且内容相同的问卷不会重复评级。")
            raise SystemExit(1)
    counts = {level: sum(item.get("preconception") == level for item in results) for level in ("P0", "P1", "P2", "P3")}
    counts["needs_review"] = sum(item["status"] == "needs_review" for item in results)
    print(json.dumps(counts, ensure_ascii=False))
    for class_no in sorted({item['class_no'] for item in results}, key=int):
        members = [item for item in results if item['class_no'] == class_no]
        p0_count = sum(item.get('preconception') == 'P0' for item in members)
        if p0_count / len(members) > 0.2:
            print(f"本次导入的{class_no}班中P0占比超过20%，请关注课前AI体验不足；以全班完整数据作最终判断。")


if __name__ == "__main__":
    try:
        main()
    except ValidationError as exc:
        raise SystemExit(str(exc))
