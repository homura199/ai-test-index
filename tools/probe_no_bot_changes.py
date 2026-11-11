"""Check existing bot variable access and legacy grading without editing bots."""
import json
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.profiles.coze import CozeAssessor, CozeVariableWriter, LegacyAuth
from backend.profiles.scoring import MAIN_BOT_ID, Questionnaire, score_semantic


def main():
    try:
        credentials = LegacyAuth('https://1308037263-lxn5m4tut3.ap-guangzhou.tencentscf.com').issue('caitian_adapter_probe_' + uuid.uuid4().hex)
    except Exception as exc:
        cause = exc.__cause__ or exc
        print(json.dumps({'issuer_available': False, 'error_type': type(cause).__name__,
                          'http_status': getattr(cause, 'code', None)}))
        return 1
    result = {'variables': [], 'legacy_grades': []}
    for channel in ('999', '1024'):
        query = urllib.parse.urlencode({'bot_id': MAIN_BOT_ID, 'connector_id': channel,
            'connector_uid': credentials['user_id_hash'], 'keywords': 'Pn,Ln,P0,L0'})
        request = urllib.request.Request('https://api.coze.cn/v1/variables?' + query,
            headers={'Authorization': 'Bearer ' + credentials['token']})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.load(response)
            result['variables'].append({'channel': channel, 'code': data.get('code'),
                'names': [item['keyword'] for item in (data.get('data') or {}).get('items', [])]})
        except urllib.error.HTTPError as exc:
            data = json.loads(exc.read(32768))
            result['variables'].append({'channel': channel, 'http_status': exc.code, 'code': data.get('code')})
    try:
        CozeVariableWriter().initialize(credentials, 3)
        result['variable_write_verified'] = True
    except Exception as exc:
        result['variable_write_verified'] = False
        result['variable_write_error'] = type(exc).__name__
    print(json.dumps({'variables': result['variables'], 'write_verified': result['variable_write_verified']}), flush=True)
    samples = [
        ('pattern', 'AI看过很多画，学会了画里面的规律，再生成从没见过的新画。', 'pattern_generation'),
        ('retrieval_after_learning', 'AI学了很多，然后从里面找一张最像的。', 'retrieval'),
        ('mixed', '它很聪明，有自己的想法，也会去网上找现成的图，两种都有。', 'mixed'),
        ('anthropomorphic', 'AI有艺术天赋和自己的灵感，想画什么就能构思出来。', 'anthropomorphic'),
        ('negation', '不是到网上找现成的图，而是看过很多画后学到规律，再生成新的作品。', 'pattern_generation'),
        ('unknown', '我不知道。', 'unscorable'),
    ]
    for label, answer, expected in samples:
        questionnaire = Questionnaire.parse({'class_no': 1, 'student_no': 1, 'answers': {'q11': answer}})
        try:
            grade = CozeAssessor(credentials['token']).assess(questionnaire)
            scored = score_semantic(questionnaire, grade)
            row = {'sample': label, 'category': scored['assessment']['category'],
                   'open_points': scored['open_points'], 'passed': scored['assessment']['category'] == expected}
        except Exception as exc:
            row = {'sample': label, 'error_type': type(exc).__name__, 'passed': False}
        result['legacy_grades'].append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    target = Path('.private/no-bot-changes-probe.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result['variable_write_verified'] and all(row['passed'] for row in result['legacy_grades']) else 1


if __name__ == '__main__':
    sys.exit(main())
