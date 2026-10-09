"""Compare native compiler adapters with one stable CC path and unchanged Rust wrapper."""
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
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tests'))
from project_comparison import tree_rss


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline', type=Path)
    p.add_argument('candidate', type=Path)
    p.add_argument('project', type=Path)
    p.add_argument('--rust-wrapper', type=Path, required=True)
    p.add_argument('--state', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--runs', type=int, default=9)
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--package', default='harness-adapters')
    args = p.parse_args()
    assert args.runs > 0 and args.jobs > 0
    binaries = {name: getattr(args, name).resolve() for name in ('baseline', 'candidate')}
    project, root = args.project.resolve(), args.state.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    wrapper, target = root / 'wrapper', root / 'target'
    native_events = root / 'native-events'
    native_events.mkdir(mode=0o700)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
           and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTC_BOOTSTRAP')}
    env.update(RUSTUP_TOOLCHAIN='1.97.1', RUSTC_WRAPPER=str(args.rust_wrapper.resolve()), CC=str(wrapper),
               NANOCOMPILE_CLANG_CAS=str(root / 'clang-cas'), NANOCOMPILE_CLANG_EVENTS=str(native_events),
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
        'rust_wrapper_sha256': sha(args.rust_wrapper.resolve()),
        'implementation_labels': {'baseline': 'Zig Clang inline CAS, replay disabled', 'candidate': 'Zig Clang inline CAS, replay enabled'},
        'method': 'rotating clean Cargo builds; native adapter binaries copied to one stable CC path; identical full environment, Rust wrapper, target path and shared Rust/native cache; both primed; build scripts execute live; Rust producer observer identity unchanged; same native Clang dependency scanner in both modes, baseline disables cache replay, candidate enables it; matching debug metadata; diagnostic capture and receipt recording in both modes',
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
        native_before = {p.name for p in native_events.iterdir()}
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
        native_artifacts = {str(path.relative_to(target)): sha(path) for path in sorted(target.rglob('*'))
                            if path.is_file() and path.suffix in ('.o', '.a')}
        artifacts.update(native_artifacts)
        assert artifacts and native_artifacts
        if reference is None:
            reference = artifacts
        assert artifacts == reference, 'Artifact mismatch: ' + str(log_path)
        after = event_file.read_text().splitlines()
        counts = {event: after[len(before):].count(event) for event in set(after[len(before):])}
        if phase == 'warm':
            assert counts.get('hit', 0) >= 165, counts
        receipts = [json.loads(p.read_text()) for p in native_events.iterdir() if p.name not in native_before]
        native_counts = {kind: sum(bool(r[kind]) for r in receipts) for kind in ('hit', 'miss', 'skipped')}
        assert receipts and all(r['exit_code'] == 0 and r['replay_enabled'] == (name == 'candidate') for r in receipts), receipts
        if name == 'baseline': assert native_counts['hit'] == 0 and native_counts['skipped'] > 0, native_counts
        if name == 'candidate' and phase == 'warm': assert native_counts['hit'] > 0, native_counts
        row = {'native_cache': native_counts, 'native_artifact_count': len(native_artifacts), 'implementation': name, 'phase': phase, 'seconds': elapsed,
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
    print(json.dumps(evidence['median_seconds']), flush=True)


if __name__ == '__main__':
    main()
