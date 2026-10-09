"""Capture stable Cargo timing reports without an extra compiler wrapper."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
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
    p.add_argument('--warm-runs', type=int, default=3)
    p.add_argument('--native-clang', action='store_true', help='Profile the accepted Apple Clang CAS configuration too')
    p.add_argument('--clang-wrapper', type=Path, help='Separate diagnostic Clang adapter; Rust wrapper stays fixed')
    args = p.parse_args()
    assert args.warm_runs > 0
    binary, project, root = args.binary.resolve(), args.project.resolve(), args.state.resolve()
    assert args.clang_wrapper is None or args.native_clang
    clang_wrapper = args.clang_wrapper.resolve() if args.clang_wrapper else binary
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    target = root / 'target'
    env = {k: v for k, v in os.environ.items() if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
           and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTC_BOOTSTRAP')}
    env.update(RUSTUP_TOOLCHAIN='1.97.1', RUSTC_WRAPPER=str(binary), CARGO_TARGET_DIR=str(target),
               CARGO_INCREMENTAL='0', NANOCOMPILE_DIR=str(root / 'cache'),
               NANOCOMPILE_PROC_MACROS='reported', NANOCOMPILE_PROC_MACRO_PRODUCERS='1',
               NANOCOMPILE_EXECUTABLE_PRODUCERS='1')
    if args.native_clang:
        env.update(CC=str(clang_wrapper)+' clang', CC_KNOWN_WRAPPER_CUSTOM='nanocompile',
                   NANOCOMPILE_CLANG_REMARKS='1')
    command = ['cargo', 'build', '--release', '--lib', '--locked', '--offline',
               '-p', 'harness-adapters', '-j', '4', '--timings']
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=project).decode().split('\0')
    sources = {name: sha(project/name) for name in names if name and (project/name).is_file()
               and (name.endswith(('.rs', '.toml')) or Path(name).name == 'Cargo.lock')}
    report = {'method': 'Accepted executable used directly as RUSTC_WRAPPER; stable Cargo --timings, one prime and clean warm builds, four jobs, fixed environment/target/cache. Timing instrumentation is diagnostic, not an A/B performance comparison. No extra Python compiler shim.',
              'core_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              'binary_sha256': sha(binary), 'script_sha256': sha(Path(__file__)),
              'native_clang': args.native_clang,
              'clang_wrapper_sha256': sha(clang_wrapper) if args.native_clang else None,
              'project_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=project, text=True).strip(),
              'project_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=project)),
              'tracked_source_sha256': sources, 'command': command, 'jobs': 4,
              'rustc': subprocess.check_output(['rustc', '-vV'], cwd=project, env=env, text=True),
              'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'builds': []}
    reference = None
    for i in range(args.warm_runs+1):
        phase = 'prime' if i == 0 else f'warm-{i}'
        shutil.rmtree(target, ignore_errors=True)
        events = root/'cache/events'
        before = events.read_text().splitlines() if events.exists() else []
        print('Capturing '+phase, flush=True)
        with (root/(phase+'.log')).open('w') as log:
            child = subprocess.Popen(command, cwd=project, env=env, stdout=log, stderr=log, start_new_session=True)
            start = time.perf_counter()
            peak = 0
            while child.poll() is None:
                peak = max(peak, tree_rss(os.getpid()))
                if peak > 40*1024**3 or time.perf_counter()-start > 3600:
                    os.killpg(child.pid, signal.SIGTERM)
                    child.wait(timeout=15)
                    raise RuntimeError('Capture exceeded memory/time limit')
                try: child.wait(timeout=.02)
                except subprocess.TimeoutExpired: pass
            seconds = time.perf_counter()-start
        assert child.returncode == 0, (root/(phase+'.log')).read_text()[-4000:]
        artifacts = {str(p.relative_to(target)): sha(p) for p in sorted(target.rglob('*')) if p.is_file()
                     and (p.suffix in (('.rlib', '.dylib', '.so', '.o', '.a') if args.native_clang else ('.rlib', '.dylib', '.so')) or p.name == 'build-script-build')}
        assert artifacts
        if reference is None: reference = artifacts
        assert artifacts == reference
        timing = target/'cargo-timings/cargo-timing.html'
        assert timing.is_file()
        captured = root/(phase+'-cargo-timing.html')
        shutil.copy2(timing, captured)
        added = events.read_text().splitlines()[len(before):]
        row = {'phase': phase, 'seconds': seconds, 'events': {e: added.count(e) for e in set(added)},
               'peak_sampled_process_tree_rss_bytes': peak, 'artifact_count': len(artifacts),
               'artifacts_match_prime': True, 'timing_html_sha256': sha(captured), 'timing_file': captured.name}
        if i: assert row['events'].get('hit') == 167 and row['events'].get('failed') == 3, row
        if i and args.native_clang: assert row['events'].get('clang_native_hit') == 24, row
        report['builds'].append(row)
        args.output.write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(row), flush=True)
    report['artifact_sha256'] = reference
    report['tracked_sources_unchanged'] = all((project/name).is_file() and sha(project/name) == h for name,h in sources.items())
    assert report['tracked_sources_unchanged']
    args.output.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__': main()
