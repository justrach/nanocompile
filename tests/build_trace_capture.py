"""Verify native capture preserves arguments, streams, stdin, failures and concurrency."""
import concurrent.futures
import json
from pathlib import Path
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from build_trace import Capture, analyze

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
    import signal
    killer = state / 'killer.c'
    killer.write_text('#include <signal.h>\nint main(){raise(SIGTERM);}')
    subprocess.run(['cc', str(killer), '-o', str(child)], check=True)
    terminated = subprocess.run([wrapper], capture_output=True)
    assert terminated.returncode == -signal.SIGTERM
    fixture = state / 'report.json'
    fixture.write_text(json.dumps({'builds': [dict(implementation='nanocompile',phase='cold',trace=dict(requests=[dict(name='<unsafe>',kind='rust',seconds=1,start_seconds=0)],cargo_units=[],kache_service_events=[]))]}))
    analysis = analyze(fixture, state / 'analysis')
    assert analysis['comparisons'][0]['kache'] is None
    assert '&lt;unsafe&gt;' in (state / 'analysis/index.html').read_text()
    assert '<unsafe>' not in (state / 'analysis/index.html').read_text()
print('Native capture transparency, concurrent records and missing-counterpart analysis passed')
