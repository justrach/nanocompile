"""Controlled cold toolchain comparison across caller directories.

This isolates repeated fingerprinting using tiny Rust crates. It is not a
project-build speed prediction; use project_comparison.py for that evidence.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import statistics


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline')
    p.add_argument('candidate')
    p.add_argument('--state', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--runs', type=int, default=3)
    p.add_argument('--directories', type=int, default=6)
    p.add_argument('--toolchain', default='1.97.1')
    args = p.parse_args()
    if args.runs < 2 or args.directories < 2:
        p.error('at least two runs and caller directories are required')
    binaries = {k: Path(getattr(args, k)).resolve() for k in ('baseline', 'candidate')}
    root = Path(args.state).resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    fixtures = []
    for i in range(args.directories):
        fixture = root / 'fixtures' / str(i)
        (fixture / 'out').mkdir(parents=True)
        (fixture / 'lib.rs').write_text('pub fn answer() -> u32 { 42 }\n')
        fixtures.append(fixture)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
           and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER')}
    env.update(RUSTUP_TOOLCHAIN=args.toolchain, NANOCOMPILE_TRACE='1')
    result = {'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'rustc': subprocess.check_output(['rustc', '-vV'], env=env, text=True),
              'binary_sha256': {k: digest(v) for k, v in binaries.items()},
              'runs': args.runs, 'directories': args.directories, 'samples': [],
              'method': 'alternate implementations; fresh private cache each sample; same fixed caller directories, sources, output paths, compiler and environment; time only wrapper invocations; verify artifact hashes across implementations'}
    references = {}
    command = ['rustc', 'lib.rs', '--crate-name', 'cold_fixture', '--crate-type', 'rlib',
               '--emit=dep-info,metadata,link', '--out-dir', 'out']
    for iteration in range(args.runs):
        order = ['baseline', 'candidate'] if iteration % 2 == 0 else ['candidate', 'baseline']
        for kind in order:
            cache = root / f'cache-{kind}-{iteration}'
            cache.mkdir(mode=0o700)
            current_env = dict(env, NANOCOMPILE_DIR=str(cache))
            seconds, durations = 0, []
            for i, fixture in enumerate(fixtures):
                start = time.monotonic()
                completed = subprocess.run([str(binaries[kind]), *command], cwd=fixture,
                                           env=current_env, capture_output=True, timeout=300)
                duration = time.monotonic() - start
                durations.append(duration)
                seconds += duration
                (root / f'{kind}-{iteration}-{i}.log').write_bytes(completed.stdout + completed.stderr)
                if completed.returncode:
                    raise RuntimeError(f'{kind} compilation failed; see private logs')
                if b'nanocompile: miss' not in completed.stderr:
                    raise RuntimeError('Expected a fresh-cache miss in every caller directory')
                artifacts = {f.name: digest(f) for f in (fixture / 'out').iterdir() if f.is_file()}
                if i in references and artifacts != references[i]:
                    raise RuntimeError('Artifact mismatch across implementations')
                references[i] = artifacts
            row = {'implementation': kind, 'iteration': iteration, 'seconds': seconds,
                   'invocation_seconds': durations, 'artifacts_match': True,
                   'selection_memos': len(list((cache / 'toolchains').iterdir())),
                   'shared_file_memos': len(list((cache / 'toolchain-files').iterdir())) if (cache / 'toolchain-files').exists() else 0}
            result['samples'].append(row)
            print(json.dumps(row), flush=True)
    result['summary'] = {k: {'median_seconds': statistics.median(x['seconds'] for x in result['samples'] if x['implementation'] == k)} for k in binaries}
    result['artifacts'] = references
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result['summary'], indent=2))


if __name__ == '__main__':
    main()
