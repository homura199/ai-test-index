"""Private teacher read / AI retry; never put administrator keys in arguments."""
import argparse
import getpass
import json
import os
from pathlib import Path
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--class-no', type=int, choices=range(1, 9), required=True)
    parser.add_argument('--student-no', type=int, choices=range(1, 56), required=True)
    parser.add_argument('--regrade', action='store_true')
    args = parser.parse_args()
    if not args.base_url.startswith('https://'):
        parser.error('HTTPS is required')
    key = os.environ.get('XIAOHUA_ADMIN_KEY') or getpass.getpass('ADMIN_KEY: ')
    def post(path, body):
        request = urllib.request.Request(args.base_url.rstrip('/') + path,
            data=json.dumps(body).encode(), headers={'Content-Type': 'application/json', 'X-Admin-Key': key})
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)['data']
    body = {'class_no': args.class_no, 'student_no': args.student_no}
    record = post('/admin/profile', body)
    if args.regrade:
        post('/admin/regrade', body | {'source_digest': record['source_digest']})
        record = post('/admin/profile', body)
    output = Path('.private/profile-result.json')
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': record['status'], 'saved_to': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
