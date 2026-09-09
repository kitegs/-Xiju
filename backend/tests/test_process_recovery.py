"""Kill only our child process; never change the user's service or network."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def child(port):
    import asyncio
    import uvicorn
    import app.main as main
    original = main._schedule_run
    scheduled = 0

    def first_only(*args):
        nonlocal scheduled
        scheduled += 1
        if scheduled == 1:
            original(*args)

    async def waiting(*args, **kwargs):
        await asyncio.sleep(3600)

    main._schedule_run = first_only
    main.plan_chat = waiting
    uvicorn.run(main.app, host='127.0.0.1', port=port)


def test_hard_exit_preserves_running_and_queued_plans(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    env = {**os.environ, 'AIBI_DATA_DIR': str(tmp_path / 'runtime')}
    env.pop('AIBI_DATABASE_URL', None)
    env['PYTHONPATH'] = str(backend)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    process = None
    with (tmp_path / 'process.log').open('w') as log, httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=5) as client:
        def start(fault):
            args = [str(Path(__file__).resolve()), str(port)] if fault else ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', str(port)]
            proc = subprocess.Popen([sys.executable, *args], cwd=backend, env=env, stdout=log, stderr=log,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            for _ in range(150):
                assert proc.poll() is None, 'Owned test server exited unexpectedly'
                try:
                    if client.get('/api/v1/health').is_success:
                        return proc
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
            proc.kill(); proc.wait()
            raise AssertionError('Owned test server did not start')

        def runs():
            return {r['id']: r for r in client.get('/api/v1/analysis-runs', params={'workspace_id': wid, 'conversation_id': cid}).json()}

        try:
            process = start(True)
            wid = client.post('/api/v1/workspaces/bootstrap').json()['id']
            cid = client.post('/api/v1/conversations', json={'workspace_id': wid, 'clarification_mode': 'off'}).json()['id']
            body = {'workspace_id': wid, 'conversation_id': cid, 'message': '说明如何开始分析'}
            first = client.post('/api/v1/chat/plan-async', json=body).json()['id']
            second = client.post('/api/v1/chat/plan-async', json=body).json()['id']
            for _ in range(100):
                if runs()[first]['status'] == 'running':
                    break
                time.sleep(.05)
            assert runs()[first]['status'] == 'running'
            assert runs()[second]['status'] == 'queued'
            before = client.get(f'/api/v1/conversations/{cid}/messages').json()
            process.kill(); process.wait(timeout=10)
            process = start(False)
            for _ in range(150):
                current = runs()
                if current[second]['status'] not in ('queued', 'running'):
                    break
                time.sleep(.1)
            assert current[first]['status'] == 'interrupted'
            assert current[second]['status'] == 'completed'
            assert all(r['report_id'] is None for r in current.values())
            after = client.get(f'/api/v1/conversations/{cid}/messages').json()
            assert {m['id'] for m in before} == {m['id'] for m in after}
            events = client.get(f'/api/v1/analysis-runs/{first}/events', params={'workspace_id': wid}).json()
            assert not any(e['event_type'] == 'run.completed' for e in events)
        finally:
            if process is not None and process.poll() is None:
                process.kill(); process.wait(timeout=10)


if __name__ == '__main__':
    child(int(sys.argv[1]))
