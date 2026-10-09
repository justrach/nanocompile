"""Controlled Harness comparison of accepted wrapper and private restore-worker client."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import statistics
import subprocess
import time
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
from project_comparison import tree_rss
from restore_worker_pool import Pool


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path)
    p.add_argument('candidate', type=Path)
    p.add_argument('project', type=Path)
    p.add_argument('--state', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--runs', type=int, default=9)
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--worker', type=Path, required=True)
    p.add_argument('--worker-root', type=Path, default=Path('/tmp/nanocompile-restore-worker-service'))
    p.add_argument('--package', default='harness-adapters')
    args = p.parse_args()
    assert args.runs > 0 and args.jobs > 0
    binaries = {name: getattr(args, name).resolve() for name in ('baseline', 'candidate')}
    project, root = args.project.resolve(), args.state.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    pool = Pool(args.worker.resolve(), binaries['baseline'], args.worker_root)
    import atexit
    atexit.register(pool.close)
    wrapper, target = root / 'wrapper', root / 'target'
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
           and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTC_BOOTSTRAP')}
    env.update(RUSTUP_TOOLCHAIN='1.97.1', RUSTC_WRAPPER=str(wrapper),
               CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL='0',
               NANOCOMPILE_DIR=str(root / 'cache'), NANOCOMPILE_PROC_MACROS='reported',
               NANOCOMPILE_PROC_MACRO_PRODUCERS='1', NANOCOMPILE_EXECUTABLE_PRODUCERS='1')
    command = ['cargo', 'build', '--release', '--lib', '--locked', '--offline',
               '-p', args.package, '-j', str(args.jobs)]
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=project).decode().split('\0')
    source_hashes = {name: sha(project / name) for name in tracked if name and
                     (name.endswith(('.rs', '.toml')) or Path(name).name == 'Cargo.lock')
                     and (project / name).is_file()}
    evidence = {
        'method': 'rotating clean Cargo builds with stable wrapper path, identical environment/target/shared cache; accepted wrapper versus lightweight C client and four persistent Zig cache-hit workers; full input/blob hashing retained; misses and producers exec accepted wrapper; worker pool remains alive for both modes; RSS includes benchmark parent, Cargo descendants and all workers',
        'worker_binary_sha256': sha(args.worker.resolve()),
        'project': str(project), 'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=project, text=True).strip(),
        'dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=project)),
        'rustc': subprocess.check_output(['rustc', '-vV'], env=env, cwd=project, text=True),
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'binary_sha256': {name: sha(path) for name, path in binaries.items()},
        'script_sha256': sha(Path(__file__)), 'jobs': args.jobs, 'runs_per_binary': args.runs,
        'command': command, 'tracked_rust_and_manifest_hashes': source_hashes, 'builds': [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.output.write_text(json.dumps(evidence, indent=2) + '\n')

    reference = None
    def build(name, phase):
        nonlocal reference
        shutil.rmtree(target, ignore_errors=True)
        shutil.copy2(binaries[name], wrapper)
        assert sha(wrapper) == evidence['binary_sha256'][name]
        event_file = root / 'cache/events'
        before = event_file.read_text().splitlines() if event_file.exists() else []
        worker_before = pool.counts()
        log_path = root / f'{len(evidence["builds"]):02d}-{name}.log'
        print(f'Building {name} {phase}', flush=True)
        with log_path.open('w') as log:
            child = subprocess.Popen(command, cwd=project, env=env, stdout=log,
                                     stderr=log, start_new_session=True)
            started = time.perf_counter()
            peak = 0
            while child.poll() is None:
                peak = max(peak, tree_rss(os.getpid()))
                if peak > 40 * 1024**3 or time.perf_counter() - started > 3600:
                    os.killpg(child.pid, signal.SIGTERM)
                    child.wait(timeout=15)
                    raise RuntimeError('Project comparison exceeded memory/time limit')
                try:
                    child.wait(timeout=.02)
                except subprocess.TimeoutExpired:
                    pass
            elapsed = time.perf_counter() - started
        assert child.returncode == 0, log_path.read_text()[-4000:]
        artifacts = {str(path.relative_to(target)): sha(path) for path in sorted(target.rglob('*'))
                     if path.is_file() and (path.suffix in ('.rlib', '.dylib', '.so') or
                                           path.name == 'build-script-build')}
        assert artifacts
        if reference is None:
            reference = artifacts
        assert artifacts == reference, 'Artifact mismatch: ' + str(log_path)
        after = event_file.read_text().splitlines()
        counts = {event: after[len(before):].count(event) for event in set(after[len(before):])}
        if phase == 'warm':
            assert counts.get('hit', 0) >= 165, counts
        worker_after = pool.counts()
        worker_counts = {k: worker_after[k] - worker_before[k] for k in worker_after}
        if name == 'baseline': assert worker_counts == {'served': 0, 'fallback': 0}, worker_counts
        if name == 'candidate' and phase == 'warm': assert worker_counts['served'] >= 100, worker_counts
        row = {'implementation': name, 'phase': phase, 'seconds': elapsed,
               'worker_requests': worker_counts,
               'events': counts, 'peak_sampled_process_tree_rss_bytes': peak,
               'artifacts_match_first_prime': True, 'artifact_count': len(artifacts)}
        evidence['builds'].append(row)
        save()
        print(json.dumps(row), flush=True)
    for name in binaries:
        build(name, 'prime')
    for i in range(args.runs):
        for name in (('baseline', 'candidate') if i % 2 == 0 else ('candidate', 'baseline')):
            build(name, 'warm')
    evidence['artifact_sha256'] = reference
    evidence['median_seconds'] = {name: statistics.median(r['seconds'] for r in evidence['builds']
                                                         if r['implementation'] == name and r['phase'] == 'warm')
                                  for name in binaries}
    evidence['tracked_sources_unchanged'] = all((project / name).is_file() and sha(project / name) == digest
                                               for name, digest in source_hashes.items())
    assert evidence['tracked_sources_unchanged']
    save()
    pool.close()
    print(json.dumps(evidence['median_seconds']), flush=True)


if __name__ == '__main__':
    main()
