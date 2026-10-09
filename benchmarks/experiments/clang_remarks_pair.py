"""Compare installed Clang remarks capture versus streaming with a fixed Cargo environment."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import shlex
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
    p.add_argument('binary', type=Path)
    p.add_argument('project', type=Path)
    p.add_argument('--state', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--runs', type=int, default=27)
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--package', default='harness-adapters')
    args = p.parse_args()
    assert args.runs > 0 and args.jobs > 0
    binary = args.binary.resolve()
    modes = {'remarks': '1', 'streaming': '0'}
    project, root = args.project.resolve(), args.state.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    wrapper, target = root / 'wrapper', root / 'target'
    control = root / 'native-mode'
    wrapper.write_text('#!/bin/sh\nIFS= read -r mode < ' + shlex.quote(str(control)) + '\nNANOCOMPILE_CLANG_REMARKS="$mode" exec ' + shlex.quote(str(binary)) + ' clang "$@"\n')
    wrapper.chmod(0o700)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
           and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTC_BOOTSTRAP')}
    env.update(RUSTUP_TOOLCHAIN='1.97.1', RUSTC_WRAPPER=str(binary), CC=str(wrapper),
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
        'nanocompile_sha256': sha(binary), 'launcher_sha256': sha(wrapper),
        'implementation_labels': {'remarks': 'installed Clang adapter: remarks and bounded capture', 'streaming': 'installed Clang adapter: no remarks, inherited descriptors'},
        'method': 'alternating paired clean Cargo builds; same installed binary, CC launcher, Rust wrapper, target path, shared cache and full Cargo environment; launcher reads a mode control file and sets NANOCOMPILE_CLANG_REMARKS only in the native compiler child; both modes primed; exact Rust, producer, native object/archive artifact bytes must match first prime. Streaming mode records invocation counts but makes no claim about unobserved native hits. Configured job count, 40 GiB cap, RSS sampled every 0.5 seconds including benchmark parent and descendants.',
        'project': str(project), 'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=project, text=True).strip(),
        'dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=project)),
        'rustc': subprocess.check_output(['rustc', '-vV'], env=env, cwd=project, text=True),
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'mode_values': modes,
        'script_sha256': sha(Path(__file__)), 'jobs': args.jobs, 'runs_per_mode': args.runs,
        'command': command, 'tracked_rust_and_manifest_hashes': source_hashes, 'builds': [],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.output.write_text(json.dumps(evidence, indent=2) + '\n')

    reference = None
    def build(name, phase):
        nonlocal reference
        shutil.rmtree(target, ignore_errors=True)
        control.write_text(modes[name] + '\n')
        assert sha(binary) == evidence['nanocompile_sha256'] and sha(wrapper) == evidence['launcher_sha256']
        event_file = root / 'cache/events'
        before = event_file.read_text().splitlines() if event_file.exists() else []
        log_path = root / f'{len(evidence["builds"]):02d}-{name}.log'
        print(f'Building {name} {phase}', flush=True)
        with log_path.open('w') as log:
            child = subprocess.Popen(command, cwd=project, env=env, stdout=log,
                                     stderr=log, start_new_session=True)
            started = time.perf_counter()
            peak, last_sample = 0, 0
            while child.poll() is None:
                if time.perf_counter() - last_sample >= .5:
                    peak = max(peak, tree_rss(os.getpid()))
                    last_sample = time.perf_counter()
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
        assert counts.get('clang_native_run', 0) >= 20, counts
        if name == 'remarks' and phase == 'warm':
            assert counts.get('clang_native_hit', 0) >= 20, counts
        if name == 'streaming':
            assert not counts.get('clang_native_hit', 0) and not counts.get('clang_native_miss', 0), counts
        row = {'native_artifact_count': len(native_artifacts), 'implementation': name, 'phase': phase, 'seconds': elapsed,
               'events': counts, 'peak_sampled_process_tree_rss_bytes': peak,
               'artifacts_match_first_prime': True, 'artifact_count': len(artifacts)}
        evidence['builds'].append(row)
        save()
        print(json.dumps(row), flush=True)
    for name in modes:
        build(name, 'prime')
    for i in range(args.runs):
        for name in (('remarks', 'streaming') if i % 2 == 0 else ('streaming', 'remarks')):
            build(name, 'warm')
    evidence['artifact_sha256'] = reference
    evidence['median_seconds'] = {name: statistics.median(r['seconds'] for r in evidence['builds']
                                                         if r['implementation'] == name and r['phase'] == 'warm')
                                  for name in modes}
    evidence['paired_seconds_saved'] = [a['seconds'] - b['seconds'] for a, b in zip(
        [r for r in evidence['builds'] if r['implementation'] == 'remarks' and r['phase'] == 'warm'],
        [r for r in evidence['builds'] if r['implementation'] == 'streaming' and r['phase'] == 'warm'])]
    deltas = evidence['paired_seconds_saved']
    evidence['paired_summary'] = {'streaming_wins': sum(d > 0 for d in deltas),
        'median_seconds_saved': statistics.median(deltas), 'mean_seconds_saved': statistics.mean(deltas),
        'stdev_seconds_saved': statistics.stdev(deltas) if len(deltas)>1 else None,
        'standard_error_seconds_saved': statistics.stdev(deltas)/len(deltas)**.5 if len(deltas)>1 else None}
    evidence['tracked_sources_unchanged'] = all((project / name).is_file() and sha(project / name) == digest
                                               for name, digest in source_hashes.items())
    assert evidence['tracked_sources_unchanged']
    save()
    print(json.dumps(evidence['median_seconds']), flush=True)


if __name__ == '__main__':
    main()
