"""Attribute nanocompile decisions and invocation time to real Cargo crates.

This adds a Python capture wrapper and trace output: use it to diagnose gates,
not as a performance comparison. Compiler environments are never recorded.
"""
import argparse
import collections
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from project_comparison import tree_rss

SHIM = '''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys, time
root = pathlib.Path(__file__).parent
cfg = json.loads((root / "config.json").read_text())
start = time.monotonic()
p = subprocess.run([cfg["binary"], *sys.argv[1:]], capture_output=True)
seconds = time.monotonic() - start
sys.stdout.buffer.write(p.stdout); sys.stderr.buffer.write(p.stderr)
args = sys.argv[1:]
def value(flag):
    for i, arg in enumerate(args):
        if arg == flag and i + 1 < len(args): return args[i + 1]
        if arg.startswith(flag + "="): return arg[len(flag) + 1:]
    return None
row = {"crate": value("--crate-name"), "type": value("--crate-type"),
       "phase": cfg["phase"], "seconds": seconds, "exit_code": p.returncode,
       "decisions": [s for s in p.stderr.decode(errors="replace").splitlines() if s.startswith("nanocompile:")],
       "args": args}
fd = os.open(root / "calls.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
os.write(fd, (json.dumps(row) + "\\n").encode()); os.close(fd)
sys.exit(p.returncode)
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary')
    p.add_argument('project')
    p.add_argument('--state', required=True)
    p.add_argument('--package', default='harness-adapters')
    p.add_argument('--proc-macros', choices=('tracked', 'reported'), default='reported')
    p.add_argument('--warm-runs', type=int, default=2)
    args = p.parse_args()
    if args.warm_runs < 1:
        p.error('warm-runs must be positive')
    project, root = Path(args.project).resolve(), Path(args.state).resolve()
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    target = root / 'target'
    shim = root / 'wrapper'
    shim.write_text(SHIM)
    shim.chmod(0o700)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
           and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER')}
    env.update(NANOCOMPILE_DIR=str(root / 'cache'), NANOCOMPILE_TRACE='1',
               NANOCOMPILE_PROC_MACROS=args.proc_macros, CARGO_INCREMENTAL='0',
               CARGO_TARGET_DIR=str(target), RUSTC_WRAPPER=str(shim))
    cfg = {'binary': str(Path(args.binary).resolve()), 'phase': 'cold'}
    for iteration in range(args.warm_runs + 1):
        shutil.rmtree(target, ignore_errors=True)
        cfg['phase'] = 'cold' if iteration == 0 else f'warm-{iteration}'
        (root / 'config.json').write_text(json.dumps(cfg))
        print('Diagnosing ' + cfg['phase'], flush=True)
        with (root / (cfg['phase'] + '.log')).open('w') as log:
            child = subprocess.Popen(['cargo', 'build', '--release', '--lib', '--locked', '--offline',
                                      '-p', args.package, '-j', '4'], cwd=project, env=env,
                                     stdout=log, stderr=log, start_new_session=True)
            start = time.monotonic()
            while child.poll() is None:
                if tree_rss(child.pid) > 40 * 1024**3 or time.monotonic() - start > 3600:
                    os.killpg(child.pid, signal.SIGTERM)
                    child.wait(timeout=15)
                    raise RuntimeError('Diagnostic exceeded memory/time limit')
                try:
                    child.wait(timeout=.5)
                except subprocess.TimeoutExpired:
                    pass
            if child.returncode:
                raise RuntimeError('Cargo diagnostic failed; see ' + str(log.name))
        rows = [json.loads(line) for line in (root / 'calls.jsonl').read_text().splitlines()]
        current = [r for r in rows if r['phase'] == cfg['phase']]
        reasons = collections.Counter(s for r in current for s in r['decisions'] if 'uncached:' in s or 'bypass:' in s)
        print(json.dumps({'phase': cfg['phase'], 'refusals': dict(reasons),
                          'slowest': [{k: r[k] for k in ('crate', 'type', 'seconds', 'decisions')}
                                      for r in sorted(current, key=lambda r: r['seconds'], reverse=True)[:10]]}), flush=True)


if __name__ == '__main__':
    main()
