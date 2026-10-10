"""Verify native capture preserves arguments, streams, stdin, failures and concurrency."""
import concurrent.futures
import json
from pathlib import Path
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from build_trace import Capture, analyze, verify_capture, capture_notifications, verify_logs

with tempfile.TemporaryDirectory() as temp:
    state = Path(temp)
    source = state / 'child.c'
    source.write_text('#include <stdio.h>\n#include <stdlib.h>\nint main(int n,char**v){int c;while((c=getchar())!=EOF)putchar(c);fprintf(stderr,"%s",getenv("CAPTURE_TEST"));for(int i=1;i<n;i++)printf("[%s]",v[i]);return 7;}')
    child = state / 'child'
    subprocess.run(['cc', str(source), '-o', str(child)], check=True)
    capture = Capture(state, {'nanocompile': str(child)})
    wrapper = capture.wrappers['nanocompile']
    import os
    env = dict(os.environ, CAPTURE_TEST='preserved')
    args = ['quote"', 'unicode-λ', 'line\nbreak']
    expected = subprocess.run([str(child), *args], input=b'stdin', capture_output=True, env=env)
    # Without a current capture directory, wrapper must still transparently execute.
    fallback = subprocess.run([wrapper, *args], input=b'stdin', capture_output=True, env=env)
    assert (fallback.returncode, fallback.stdout, fallback.stderr) == (expected.returncode, expected.stdout, expected.stderr)
    capture.begin(0, 'nanocompile')
    def run(_):
        actual = subprocess.run([wrapper, *args], input=b'stdin', capture_output=True, env=env)
        assert (actual.returncode, actual.stdout, actual.stderr) == (expected.returncode, expected.stdout, expected.stderr)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(run, range(16)))
    records = list(capture.directory.glob('*.json'))
    assert len(records) == 16
    for path in records:
        row = json.loads(path.read_text())
        assert row['args'] == args and row['exit_code'] == 7 and row['end_ns'] >= row['start_ns']
        assert path.with_suffix('.stdout').read_bytes() == expected.stdout
        assert path.with_suffix('.stderr').read_bytes() == expected.stderr
    # The compiler must be able to notify Cargo before it finishes. A gate
    # makes this deterministic rather than relying on a speed threshold.
    import selectors
    live = state / 'live.c'
    live.write_text(r'''#define _POSIX_C_SOURCE 200809L
#include <stdlib.h>
#include <unistd.h>
#include <time.h>
int main(){
 const char notice[]="{\"$message_type\":\"artifact\",\"artifact\":\"out.rmeta\",\"emit\":\"metadata\"}\n";
 write(2,notice,sizeof notice-1);
 struct timespec delay={0,1000000};
 while(access(getenv("CAPTURE_GATE"),F_OK))nanosleep(&delay,0);
 unsigned char bytes[16384];for(int i=0;i<16384;++i)bytes[i]=i%256;
 for(int fd=1;fd<=2;++fd)for(int j=0;j<128;++j){int p=0;while(p<16384){int n=write(fd,bytes+p,16384-p);if(n<=0)return 1;p+=n;}}
 return 0;
}''')
    subprocess.run(['cc', str(live), '-o', str(child)], check=True)
    gate = state / 'gate'
    before_live = set(capture.directory.glob('*.json'))
    running = subprocess.Popen([wrapper], env=dict(env, CAPTURE_GATE=str(gate)), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with selectors.DefaultSelector() as sel:
            sel.register(running.stderr, selectors.EVENT_READ)
            assert sel.select(10), 'capture frontend delayed compiler metadata'
        notice = running.stderr.readline()
        assert json.loads(notice)['emit'] == 'metadata'
        assert running.poll() is None
        gate.write_text('go')
        stdout, stderr = running.communicate(timeout=30)
        assert running.returncode == 0
        payload = bytes(range(256)) * 8192
        assert stdout == payload and stderr == payload
        live_record = (set(capture.directory.glob('*.json')) - before_live).pop()
        assert live_record.with_suffix('.stdout').read_bytes() == stdout
        assert live_record.with_suffix('.stderr').read_bytes() == notice + stderr
        assert json.loads(live_record.read_text())['capture_complete'] is True
        chunk_file = live_record.with_suffix('.chunks')
        original_chunks = chunk_file.read_bytes()
        lines = original_chunks.decode().splitlines()
        parts = lines[0].split(','); parts[1] = '1'; lines[0] = ','.join(parts)
        chunk_file.write_text('\n'.join(lines) + '\n')
        try:
            capture_notifications(live_record, json.loads(live_record.read_text()), 0)
            raise AssertionError('Noncontiguous chunk coverage was accepted')
        except ValueError:
            pass
        chunk_file.write_bytes(original_chunks)
    finally:
        if running.poll() is None:
            gate.write_text('abort')
            running.kill()
            running.communicate()
    import signal
    killer = state / 'killer.c'
    killer.write_text('#include <signal.h>\nint main(){raise(SIGTERM);}')
    subprocess.run(['cc', str(killer), '-o', str(child)], check=True)
    terminated = subprocess.run([wrapper], capture_output=True)
    assert terminated.returncode == -signal.SIGTERM
    console = state / 'console.log'
    console.write_bytes(b'complete build console\nprivate-marker\x00')
    event_log = state / 'events'
    event_log.write_text('hit\n')
    captured = dict(implementation='nanocompile', phase='warm')
    capture.finish(captured, state / 'target', 0, event_log, 0, console)
    observed = [request for request in captured['trace']['requests'] if request.get('metadata_notifications_seconds')]
    assert len(observed) == 1 and len(observed[0]['metadata_notifications_seconds']) == 1
    manifest = json.loads((capture.directory / 'manifest.json').read_text())
    import hashlib
    assert manifest['files']['cargo.log']['sha256'] == hashlib.sha256(console.read_bytes()).hexdigest()
    assert manifest['files']['cargo.log']['bytes'] == len(console.read_bytes())
    assert manifest['compiler_records'] == 18 and manifest['build_log_captured']
    assert verify_capture(capture.directory)['verified_files'] == len(manifest['files'])
    (capture.directory / 'cargo.log').write_bytes(b'truncated')
    try:
        verify_capture(capture.directory)
        raise AssertionError('Truncated log was accepted')
    except ValueError:
        pass
    (capture.directory / 'cargo.log').write_bytes(console.read_bytes())
    victim = capture.directory / records[0].name
    original_record = victim.read_bytes()
    victim.unlink()
    try:
        verify_capture(capture.directory)
        raise AssertionError('Missing record was accepted')
    except ValueError:
        pass
    victim.write_bytes(original_record)
    fixture = state / 'report.json'
    fixture.write_text(json.dumps({'builds': [dict(implementation='nanocompile',phase='cold',trace=dict(requests=[dict(name='<unsafe>',kind='rust',seconds=1,start_seconds=0)],cargo_units=[],kache_service_events=[]))]}))
    analysis = analyze(fixture, state / 'analysis')
    assert analysis['comparisons'][0]['kache'] is None
    assert '&lt;unsafe&gt;' in (state / 'analysis/index.html').read_text()
    assert '<unsafe>' not in (state / 'analysis/index.html').read_text()
    paired = [dict(implementation=tool, phase='warm', trace=dict(requests=[],
              cargo_units=[dict(name='ring', mode='run-custom-build', duration=duration)],
              kache_service_events=[])) for tool, duration in [('nanocompile', 1.2), ('kache', .1)]]
    fixture.write_text(json.dumps(dict(builds=paired, native_artifacts=True, portable_cc=False, command=['cargo','build','--release'], runs=2, cold_runs=1)))
    analyze(fixture, state / 'paired')
    instructions = json.loads((state / 'paired/experiments.json').read_text())
    assert instructions['provenance']['native_artifacts'] is True
    assert instructions['provenance']['command'] == ['cargo','build','--release']
    assert instructions['provenance']['runs'] == 2
    assert len(instructions['provenance']['analyzer_sha256']) == 64
    plan = instructions['experiments']
    assert len(plan) == 1 and plan[0]['observation']['name'].startswith('ring')
    assert plan[0]['observation']['nanocompile']['samples'] == 1
    assert 'ablation' in plan[0]['next_measurement']
    assert 'not predicted' in plan[0]['claim']
    assert 'private-marker' not in (state / 'paired/index.html').read_text()
    console_report = state / 'consoles.json'
    console_report.write_text(json.dumps(dict(builds=[dict(build_log=dict(
        path=console.name, bytes=console.stat().st_size,
        sha256=hashlib.sha256(console.read_bytes()).hexdigest()))])))
    assert verify_logs(console_report, state)['verified_build_logs'] == 1
    console.write_bytes(b'changed')
    try:
        verify_logs(console_report, state)
        raise AssertionError('Changed console accepted')
    except ValueError:
        pass
    console_report.write_text(json.dumps(dict(builds=[dict(build_log=dict(path='../escape'))])))
    try:
        verify_logs(console_report, state)
        raise AssertionError('Escaping console path accepted')
    except ValueError:
        pass
    paired[0]['trace']['requests'] = [dict(name='app', kind='rust', seconds=12,
        start_seconds=0, nano_decisions=['nanocompile: bypass: UnsupportedProducerConfiguration']),
        dict(name='large', kind='rust', seconds=2, start_seconds=0,
             nano_decisions=['nanocompile: uncached: StreamTooLong'])]
    fixture.write_text(json.dumps(dict(builds=paired)))
    support = analyze(fixture, state / 'support')
    assert support['uncached_work'][0]['reason'] == 'UnsupportedProducerConfiguration'
    assert support['uncached_work'][1]['reason'] == 'StreamTooLong'
    assert 'cold-build savings' in support['uncached_work'][0]['claim']
    paired[0]['cli_help_valid'] = False
    fixture.write_text(json.dumps(dict(builds=paired, completed=False,
                                      failure=dict(type='RuntimeError', message='probe failed'))))
    rejected = analyze(fixture, state / 'rejected')
    assert len(rejected['excluded_builds']) == 1
    assert rejected['comparisons'][0]['nanocompile'] is None
    instructions = json.loads((state / 'rejected/experiments.json').read_text())
    assert not instructions['experiments'] and not instructions['uncached_work']
    assert instructions['provenance']['completed'] is False
print('Native capture transparency, concurrent records and missing-counterpart analysis passed')
