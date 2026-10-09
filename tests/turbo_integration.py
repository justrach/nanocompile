"""Real Turborepo remote-cache restore and invalidation with a Zig CAS backend."""
import argparse
import contextlib
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import selectors
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from r2_transport import Store
import r2_cache

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary')
    parser.add_argument('--output')
    parser.add_argument('--r2-snapshot', help='use actual R2 credentials from R2_* env instead of in-memory transport')
    args = parser.parse_args()
    binary = str(Path(args.binary).resolve())
    turbo = ROOT / 'examples/turborepo/node_modules/.bin/turbo'
    if not turbo.exists():
        raise SystemExit('Run npm ci --prefix examples/turborepo first')
    with tempfile.TemporaryDirectory(prefix='nanocompile-turbo-') as temp:
        root = Path(temp)
        repo, cache = root / 'project', root / 'cache'
        shutil.copytree(ROOT / 'examples/turborepo', repo,
                        ignore=shutil.ignore_patterns('node_modules', '.turbo', 'dist'))
        token = secrets.token_hex(32)
        env = {k: v for k, v in os.environ.items() if not k.startswith(('TURBO_', 'NANOCOMPILE_', 'R2_'))}
        env.update(TURBO_TOKEN=token, TURBO_TEAM='nanocompile-example', TURBO_TELEMETRY_DISABLED='1',
                   TURBO_REMOTE_CACHE_SIGNATURE_KEY=secrets.token_hex(32),
                   NANO_TURBO_EXECUTION_LOG=str(root / 'executions'), EXAMPLE_LABEL='demo')
        process = None
        starts = 0
        rows = []

        def start():
            nonlocal process, starts
            starts += 1
            server_cwd = root / ("server-cwd-" + str(starts))
            server_cwd.mkdir()
            process = subprocess.Popen([sys.executable, str(ROOT / 'tools/turbo_cache.py'),
                                        '--nanocompile', binary, '--cache', str(cache), '--port', '0'],
                                       env=dict(env, NANOCOMPILE_TURBO_TOKEN=token),
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=server_cwd)
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                assert selector.select(20), 'Cache server startup timeout'
            ready = json.loads(process.stdout.readline())
            env['TURBO_API'] = 'http://127.0.0.1:' + str(ready['port'])
            return ready['port']

        def stop():
            nonlocal process
            if process is not None:
                process.terminate()
                process.communicate(timeout=15)
                process = None

        def executions():
            return (root / 'executions').read_text().splitlines() if (root / 'executions').exists() else []

        def outputs():
            return {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in repo.glob('**/dist/*') if p.is_file()}

        def clean():
            for p in list(repo.glob('**/dist')):
                shutil.rmtree(p)
            shutil.rmtree(repo / '.turbo/cache', ignore_errors=True)

        def build(phase, expected_runs, current_env=None):
            before = len(executions())
            start_time = time.monotonic()
            p = subprocess.run([str(turbo), 'run', 'build', '--cache=remote:rw', '--summarize', '--no-daemon'],
                               cwd=repo, env=current_env or env, capture_output=True, timeout=120)
            seconds = time.monotonic() - start_time
            (root / (phase + '.log')).write_bytes(p.stdout + p.stderr)
            assert p.returncode == 0, p.stderr.decode(errors='replace') + p.stdout.decode(errors='replace')
            ran = executions()[before:]
            assert sorted(ran) == sorted(expected_runs), (phase, ran)
            assert len(outputs()) == 2
            summary_path = max((repo / '.turbo/runs').glob('*.json'), key=lambda p: p.stat().st_mtime_ns)
            summary = json.loads(summary_path.read_text())
            tasks = [{k: task.get(k) for k in ('taskId', 'hash', 'cache')} for task in summary['tasks']]
            row = {'phase': phase, 'seconds': seconds, 'executed': ran, 'artifacts': outputs(), 'tasks': tasks}
            rows.append(row)
            print(json.dumps(row), flush=True)
            return row

        def request(method, path, body=None, auth=token, extra=None):
            conn = http.client.HTTPConnection('127.0.0.1', port, timeout=20)
            headers = {'Authorization': 'Bearer ' + auth, **(extra or {})}
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            data = response.read()
            conn.close()
            return response.status, dict(response.getheaders()), data

        try:
            port = start()
            assert request('GET', '/v8/artifacts/status', auth='wrong')[0] == 401
            assert request('GET', '/v8/artifacts/status?slug=other')[0] == 403
            assert request('GET', '/v8/artifacts/status')[0] == 200
            cold = build('cold', ['message', 'site'])
            clean()
            warm = build('remote-restore', [])
            assert cold['artifacts'] == warm['artifacts']
            assert all(t['cache']['remote'] and t['cache']['status'] == 'HIT' for t in warm['tasks'])
            key = warm['tasks'][0]['hash']
            status, headers, data = request('GET', '/v8/artifacts/' + key)
            assert status == 200 and headers.get('x-artifact-tag') and data
            assert request('HEAD', '/v8/artifacts/' + key)[0] == 200
            bulk = request('POST', '/v8/artifacts', json.dumps({'hashes': [key, '0' * 16]}))
            assert bulk[0] == 200 and json.loads(bulk[2])[key]['taskDurationMs'] >= 0
            # Exercise the unchanged R2 snapshot format with actual Zig entries.
            stop()
            manager = contextlib.nullcontext() if args.r2_snapshot else patch.object(r2_cache, 'client', return_value=(Store(), 'test'))
            try:
                with manager:
                    snapshot = args.r2_snapshot or 'turbo-example'
                    r2_cache.transfer('push', cache, snapshot)
                    shutil.rmtree(cache)
                    cache = root / 'relocated-cache'
                    r2_cache.transfer('pull', cache, snapshot)
            except Exception as exc:
                raise RuntimeError("R2 snapshot transfer failed: " + type(exc).__name__) from None
            assert not (cache / 'toolchains').exists()
            port = start()
            clean()
            restored = build('snapshot-restore', [])
            assert restored['artifacts'] == cold['artifacts']
            # Preserve mtime: task keys must observe source bytes, and dependency
            # changes must invalidate both producer and dependent task outputs.
            source = repo / 'packages/message/greeting.txt'
            stamp = source.stat()
            source.write_text('Changed from the nanocompile task cache!\n')
            os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            clean()
            changed = build('changed-dependency', ['message', 'site'])
            assert changed['artifacts'] != cold['artifacts']
            clean()
            build('changed-dependency-restore', [])
            # A site-only input change leaves the producer cached.
            site = repo / 'apps/site/build.mjs'
            site.write_text(site.read_text().replace('Task cache example', 'Updated cache example'))
            clean()
            build('changed-site', ['site'])
            clean()
            changed_env = build('changed-env', ['message', 'site'], dict(env, EXAMPLE_LABEL='changed'))
            assert 'changed' in (repo / 'apps/site/dist/index.html').read_text()
            # Blob corruption must become a miss, never a restored bad archive.
            entries = [json.loads(p.read_text().split('\n', 1)[1]) for p in (cache / 'entries').iterdir()]
            entry = next(e for e in entries if e['artifact']['key'] == changed_env['tasks'][0]['hash'])
            hash_ = entry['outputs'][0]['hash']
            (cache / 'blobs' / hash_[:2] / hash_).write_bytes(b'corrupt')
            assert request('HEAD', '/v8/artifacts/' + entry['artifact']['key'])[0] == 404
            clean()
            repaired = build('corruption-rebuild', ['message'], dict(env, EXAMPLE_LABEL='changed'))
            assert repaired['artifacts'] == changed_env['artifacts']
            assert request('HEAD', '/v8/artifacts/' + entry['artifact']['key'])[0] == 200
            # GC and clear include task artifacts in the existing blob quota.
            subprocess.run([binary, 'gc', '0'], env=dict(env, NANOCOMPILE_DIR=str(cache)), check=True, capture_output=True)
            assert request('HEAD', '/v8/artifacts/' + key)[0] == 404
            clean()
            build('after-gc', ['message', 'site'])
            subprocess.run([binary, 'clear'], env=dict(env, NANOCOMPILE_DIR=str(cache)), check=True, capture_output=True)
            assert not list((cache / 'entries').iterdir())
        finally:
            stop()
        result = {'turbo_version': subprocess.check_output([str(turbo), '--version'], text=True).strip(),
                  'node_version': subprocess.check_output(['node', '--version'], text=True).strip(),
                  'nanocompile_sha256': hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
                  'snapshot_transport': 'actual R2' if args.r2_snapshot else 'in-memory S3 test double',
                  'method': 'remote-only task cache; remove declared outputs and client local cache before restores; signed artifacts; assert execution log and output hashes',
                  'runs': rows}
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result, indent=2) + '\n')
        print('PASS: real Turbo remote hits, signed restore, snapshot, source/dependency/env changes, isolation, corruption, GC and clear')


if __name__ == '__main__':
    main()
