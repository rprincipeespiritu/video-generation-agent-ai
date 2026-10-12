"""Prueba HTTP del contenedor en CI, sin claves ni APIs externas."""
import base64
import json
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = 'http://127.0.0.1:18765'
AUTH = 'Basic ' + base64.b64encode(b'admin:ci-only-password-1234567890').decode()


def call(path, data=None, *, auth=True, token='', headers=None):
    opts = {'Host': 'studio.example.test', 'X-Forwarded-Proto': 'https'}
    if auth:
        opts['Authorization'] = AUTH
    if data is not None:
        opts.update({'Content-Type': 'application/json', 'X-Local-Token': token})
    opts.update(headers or {})
    req = Request(BASE + path, data=None if data is None else json.dumps(data).encode(), headers=opts)
    with urlopen(req, timeout=10) as response:
        raw = response.read()
        body = json.loads(raw) if response.headers.get_content_type() == 'application/json' else raw
        return response.status, body


def main():
    deadline = time.monotonic() + 60
    while True:
        try:
            assert call('/healthz', auth=False)[0] == 200
            break
        except (OSError, AssertionError):
            if time.monotonic() > deadline:
                raise
            time.sleep(1)
    try:
        call('/api/jobs', auth=False)
        raise AssertionError('La API no debe ser pública.')
    except HTTPError as error:
        assert error.code == 401
    token = call('/api/session')[1]['token']
    if '--check-persisted' not in sys.argv:
        assert call('/api/create', {'mode': 'demo'}, token=token)[0] == 200
        deadline = time.monotonic() + 90
        while True:
            activity = call('/api/status')[1]['activity']
            if activity['status'] != 'RUNNING':
                assert activity['status'] == 'DONE', activity
                break
            assert time.monotonic() < deadline, 'La demo no terminó.'
            time.sleep(1)
    jobs = call('/api/jobs')[1]['jobs']
    assert len(jobs) == 1 and jobs[0]['demo'] and jobs[0]['status'] == 'REVIEW'
    code, body = call('/media/' + jobs[0]['id'] + '/video', headers={'Range': 'bytes=0-9'})
    assert code == 206 and len(body) == 10
    print('OK: contenedor, autenticación, demo, reproducción y volumen.')


if __name__ == '__main__':
    main()
