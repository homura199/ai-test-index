"""Probe the existing issuer and two bots using an isolated synthetic identity.

No tokens, raw API errors or survey data are printed or saved. This checks API
access, not the configured profile chatflow or the school's network capacity.
"""
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.profiles.coze import LegacyAuth
from backend.profiles.scoring import ASSESSMENT_BOT_ID, MAIN_BOT_ID


def probe(token, safe_user, bot_id, prompt):
    request = urllib.request.Request('https://api.coze.cn/v3/chat',
        data=json.dumps({'bot_id': bot_id, 'user_id': safe_user, 'stream': True,
                         'auto_save_history': False,
                         'additional_messages': [{'role': 'user', 'content_type': 'text', 'content': prompt}]}).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
    result = {'bot_id': bot_id, 'completed': False, 'answer_received': False}
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            result['http_status'] = response.status
            if 'text/event-stream' not in response.headers.get('Content-Type', ''):
                value = json.loads(response.read(32768))
                result['api_code'] = value.get('code')
                return result
            event, lines = '', []
            for raw in response:
                line = raw.decode('utf-8').strip()
                if line.startswith('event:'): event = line[6:].strip()
                elif line.startswith('data:'): lines.append(line[5:].strip())
                elif not line and lines:
                    content, lines = '\n'.join(lines), []
                    if content == '[DONE]': break
                    item = json.loads(content)
                    if event == 'conversation.message.completed' and item.get('type') == 'answer':
                        result['answer_received'] = bool(item.get('content'))
                        try:
                            answer = json.loads(item.get('content', ''))
                            result['answer_json_fields'] = sorted(answer) if isinstance(answer, dict) else []
                        except ValueError:
                            result['answer_json_fields'] = []
                    if event == 'conversation.chat.completed': result['completed'] = True
                    if event in ('error', 'conversation.chat.failed'):
                        result['failure_event'] = event
                        result['api_code'] = item.get('code') or (item.get('last_error') or {}).get('code')
    except urllib.error.HTTPError as exc:
        result['http_status'] = exc.code
        try:
            result['api_code'] = json.loads(exc.read(32768)).get('code')
        except ValueError:
            pass
    except (TimeoutError, OSError, ValueError):
        result['connection_failed'] = True
    return result


def main():
    user_id = 'caitian_probe_' + uuid.uuid4().hex
    try:
        auth = LegacyAuth('https://1308037263-lxn5m4tut3.ap-guangzhou.tencentscf.com').issue(user_id)
    except Exception:
        print(json.dumps({'issuer_available': False}))
        return 1
    results = {'issuer_available': True, 'bots': [
        probe(auth['token'], auth['user_id_hash'], MAIN_BOT_ID, '开始第一课时。这是一条系统联调测试消息，不是真实学生作答。'),
        probe(auth['token'], auth['user_id_hash'], ASSESSMENT_BOT_ID, json.dumps({
            'task': 'preconcept_q11', 'q11': 'AI看过很多图片，从中学到规律，再生成以前没有的新图。',
            'q6_reference_only': '', 'test_only': True}, ensure_ascii=False))
    ]}
    target = Path('.private/live-probe.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False))


if __name__ == '__main__':
    sys.exit(main())
