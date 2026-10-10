"""Alternate frozen shims over one real Cargo script, environment and primed entry."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import statistics
import subprocess
import tempfile
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'candidate', 'cargo_log', 'real', 'contract', 'output'):
        parser.add_argument('--'+name.replace('_', '-'), type=Path, required=True)
    parser.add_argument('--runs', type=int, default=10)
    args = parser.parse_args()
    assert args.runs >= 2
    assignments = None
    for line in args.cargo_log.read_text().splitlines():
        match = re.fullmatch(r'\s*Running `(.*)`', line)
        if not match:
            continue
        fields = shlex.split(match[1])
        variables = {}
        for field in fields:
            if '=' not in field or not re.fullmatch('[A-Za-z_][A-Za-z_0-9]*', field.split('=', 1)[0]):
                break
            key, value = field.split('=', 1)
            variables[key] = value
        if variables.get('CARGO_PKG_NAME') == 'ring' and 'OUT_DIR' in variables:
            assignments = variables
            break
    assert assignments, 'No ring execution environment in verbose Cargo log'
    env = {k:v for k,v in os.environ.items() if not k.startswith(('NANOCOMPILE_', 'R2_', 'KACHE_')) and k not in ('RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER')}
    env.update(assignments)
    samples = []
    with tempfile.TemporaryDirectory(prefix='nano-script-ab-') as temporary:
        root = Path(temporary)
        shim, real, out, cache = root/'build-script-build', root/'real', root/'out', root/'cache'
        shutil.copyfile(args.real, real)
        real.chmod(0o700)
        (root/'nano-build-script.json').write_text(json.dumps(dict(real=str(real))))
        env.update(OUT_DIR=str(out), NANOCOMPILE_DIR=str(cache),
                   NANOCOMPILE_BUILD_SCRIPTS_FILE=str(args.contract.resolve()),
                   NANOCOMPILE_TRACE='1', NANOCOMPILE_SCRIPT_PROFILE='1')
        cwd = Path(assignments['CARGO_MANIFEST_DIR'])
        def run(binary, phase):
            shutil.copyfile(binary, shim)
            shim.chmod(0o700)
            shutil.rmtree(out, ignore_errors=True)
            out.mkdir()
            events = cache/'events'
            before = events.read_text().splitlines() if events.exists() else []
            with open('/dev/null','rb') as stream:
                start = time.perf_counter_ns()
                result = subprocess.run([str(shim)], cwd=cwd, env=env, stdin=stream, capture_output=True)
                elapsed = time.perf_counter_ns()-start
            assert result.returncode == 0, result.stderr.decode(errors='replace')
            after = events.read_text().splitlines()[len(before):]
            assert 'build_script_'+phase in after, after
            files = {p.name:dict(sha256=digest(p), mode=p.stat().st_mode & 0o777) for p in out.iterdir()}
            measured = re.findall(rb'^nanocompile: script-phase ([\w.]+) ns=(\d+)$', result.stderr, re.M)
            phases = {name.decode():int(value) for name,value in measured}
            streams = dict(stdout=hashlib.sha256(result.stdout).hexdigest(),
                           stderr=hashlib.sha256(re.sub(rb'^nanocompile: .*\n', b'', result.stderr, flags=re.M)).hexdigest())
            return dict(elapsed_ns=elapsed, phases_ns=phases, artifacts=files, streams=streams)
        prime = run(args.baseline, 'miss')
        for pair in range(args.runs):
            order = ('baseline','candidate') if pair%2==0 else ('candidate','baseline')
            for implementation in order:
                row = run(getattr(args, implementation), 'hit')
                assert row['artifacts'] == prime['artifacts']
                assert row['streams'] == prime['streams'], (implementation, row['streams'], prime['streams'])
                samples.append(dict(pair=pair, implementation=implementation, **row))
    report = dict(diagnostic=True, method='one primed entry, same script/environment/cache/output paths; alternating frozen shim binaries; excludes binary copying, output deletion and artifact checks; complete own-prime artifacts and stdout/normalized-stderr hashes match; wrapper diagnostic lines excluded from stderr equality; not a whole-build speed benchmark',
                  runner_sha256=digest(Path(__file__)), baseline_sha256=digest(args.baseline), candidate_sha256=digest(args.candidate), real_sha256=digest(args.real), cargo_log_sha256=digest(args.cargo_log), contract_sha256=digest(args.contract), runs=args.runs, samples=samples)
    report['median_seconds'] = {name:statistics.median(r['elapsed_ns'] for r in samples if r['implementation']==name)/1e9 for name in ('baseline','candidate')}
    report['median_phase_ns'] = {name:{phase:statistics.median(r['phases_ns'][phase] for r in samples if r['implementation']==name and phase in r['phases_ns']) for phase in sorted({p for r in samples if r['implementation']==name for p in r['phases_ns']})} for name in ('baseline','candidate')}
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('median_seconds','median_phase_ns')}))

if __name__ == '__main__':
    main()
