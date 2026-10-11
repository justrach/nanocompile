"""Alternating Nano/kache pairs on distinct shared-parser edits of the full Harness CLI.

A focused speed instrument for the shared-edit scenario of
tests/harness_full_source_edits.py: one cold prime per cache, the leaf CLI
edit, then N distinct edits to the shared `version_triple` parser. Each edit
is built by both implementations in alternating order with a clean Cargo
target, so both see the same miss set. The private kache daemon runs only
for kache builds and is idle before each. Correctness (artifact equality,
empty-cache references) is the job of the full source-edit runner; this
runner checks the CLI and records Cargo timings for tools/rust_profile.py.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import statistics
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bindgen_controls import load as bindgen_controls  # noqa: E402

VARIANTS = [b"trim_start()", b"trim_end()", b"trim_matches(' ')", b"trim_start_matches(' ')",
            b"trim_end_matches(' ')", b"trim_matches('\\t')", b"trim_start_matches('\\t')",
            b"trim_end_matches('\\t')", b"trim_matches('\\r')", b"trim_start_matches('\\r')",
            b"trim_end_matches('\\r')", b"trim_matches('\\n')"]
PARSER = b"let mut parts = version.trim().splitn(3, '.');"
HELP = b'Multi-device controller for coding agents'


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary', type=Path)
    p.add_argument('project', type=Path)
    p.add_argument('--kache', type=Path, required=True)
    p.add_argument('--state', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--pairs', type=int, default=6)
    p.add_argument('--jobs', type=int, default=8)
    p.add_argument('--source-date-epoch', required=True)
    p.add_argument('--build-script-contract', type=Path)
    p.add_argument('--bindgen-tools-file', type=Path)
    p.add_argument('--declared-build-scripts', action='store_true')
    p.add_argument('--prewarm-stores', action='store_true',
                   help="before every build (outside timing) read every file of that implementation's own cache store, so each starts with a warm OS cache for its store")
    p.add_argument('--quiesce-seconds', type=float, default=0.0,
                   help='before every build (outside timing, for both implementations) flush dirty pages with sync and wait this long')
    args = p.parse_args()
    if not 1 <= args.pairs <= len(VARIANTS):
        p.error(f'--pairs must be between 1 and {len(VARIANTS)}')
    binary, kache = str(args.binary.resolve()), str(args.kache.resolve())
    state = args.state.resolve()
    state.mkdir(mode=0o700)
    project = state / 'project'
    subprocess.run(['cp', '-c', '-R', str(args.project.resolve()), str(project)], check=True)
    target, cache, kcache = state / 'target', state / 'nano-cache', state / 'kache-cache'
    config = state / 'kache.toml'
    config.write_text('[cache]\nrecord_sessions=true\n')
    env = {k: v for k, v in os.environ.items() if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
           and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER')}
    if args.bindgen_tools_file:
        env.update(bindgen_controls(args.bindgen_tools_file)[0])
    env.update(SOURCE_DATE_EPOCH=args.source_date_epoch, CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL='0',
               NANOCOMPILE_DIR=str(cache), NANOCOMPILE_PROC_MACROS='reported', NANOCOMPILE_PROC_MACRO_PRODUCERS='1',
               NANOCOMPILE_EXECUTABLE_PRODUCERS='1', NANOCOMPILE_THIN_LTO_PRODUCERS='1', NANOCOMPILE_RUST_STATICLIB='1',
               NANOCOMPILE_RLIB_FRAMEWORKS='1', KACHE_CACHE_DIR=str(kcache), KACHE_CONFIG=str(config), KACHE_HOST_CONFIG='',
               KACHE_SOCKET_PATH=str(state / 'daemon.sock'), KACHE_DAEMON_IDLE_TIMEOUT='600')
    if args.build_script_contract:
        env['NANOCOMPILE_BUILD_SCRIPTS_FILE'] = str(args.build_script_contract.resolve())
    if args.declared_build_scripts:
        env['NANOCOMPILE_BUILD_SCRIPT_CACHE'] = 'declared'
    command = ['cargo', 'build', '--release', '--locked', '--offline', '--bin', 'harness', '-p', 'harness',
               '-j', str(args.jobs), '--message-format=json-render-diagnostics', '--timings']
    leaf, shared = project / 'apps/harness/src/main.rs', project / 'crates/proto/src/lib.rs'
    leaf_original, shared_original = leaf.read_bytes(), shared.read_bytes()
    assert leaf_original.count(HELP) == 1 and shared_original.count(PARSER) == 1
    daemon = None
    daemon_log = (state / 'daemon.log').open('w')

    def stop_daemon():
        nonlocal daemon
        if daemon is not None:
            daemon.send_signal(signal.SIGINT)
            try:
                daemon.wait(timeout=15)
            except subprocess.TimeoutExpired:
                daemon.kill()
                daemon.wait()
            daemon = None

    def start_daemon():
        nonlocal daemon
        daemon = subprocess.Popen([kache, 'daemon', 'run'], cwd=project, env=env, stdout=daemon_log, stderr=daemon_log)
        deadline = time.monotonic() + 15
        while not (state / 'daemon.sock').exists():
            if daemon.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('private kache daemon did not start')
            time.sleep(0.1)
        quiet, started = 0, time.monotonic()
        while quiet < 3 and time.monotonic() - started < 180:
            sample = subprocess.run(['ps', '-o', '%cpu=', '-p', str(daemon.pid)], capture_output=True, text=True).stdout.strip()
            quiet = quiet + 1 if sample and float(sample) < 2.0 else 0
            time.sleep(1)

    result = dict(method=__doc__.strip(), quiesce_seconds=args.quiesce_seconds, prewarm_stores=args.prewarm_stores, binary_sha256=sha(binary), kache_sha256=sha(kache), project=str(args.project),
                  jobs=args.jobs, builds=[], completed=False)

    def save():
        args.output.write_text(json.dumps(result, indent=2) + '\n')

    def build(implementation, scenario):
        if implementation == 'kache':
            if daemon is None:
                start_daemon()
        else:
            stop_daemon()
        shutil.rmtree(target, ignore_errors=True)
        if args.prewarm_stores:
            store = cache if implementation == 'nanocompile' else kcache
            warmed = 0
            for path in store.rglob('*'):
                if path.is_file() and not path.is_symlink():
                    with path.open('rb') as handle:
                        while chunk := handle.read(1 << 22):
                            warmed += len(chunk)
            print(f'prewarmed {warmed / 1e9:.1f} GB of {implementation} store', flush=True)
        if args.quiesce_seconds:
            # Writeback from the previous build (either implementation) must
            # not overlap this one: flush, wait, flush again.
            os.sync()
            time.sleep(args.quiesce_seconds)
            os.sync()
        e = dict(env)
        e['RUSTC_WRAPPER'] = binary if implementation == 'nanocompile' else kache
        number = len(result['builds'])
        log = state / f'{number:02d}-{implementation}-{scenario}.log'
        print(f'build {number}: {implementation} {scenario}', flush=True)
        t = time.monotonic()
        with log.open('w') as out:
            code = subprocess.run(command, cwd=project, env=e, stdout=out, stderr=out).returncode
        seconds = time.monotonic() - t
        timing = state / f'{number:02d}-{implementation}-{scenario}.timing.html'
        if (target / 'cargo-timings/cargo-timing.html').is_file():
            shutil.copyfile(target / 'cargo-timings/cargo-timing.html', timing)
        help_text = subprocess.run([str(target / 'release/harness'), '--help'], capture_output=True).stdout if code == 0 else b''
        expected = HELP + (b' (build-cache source edit)' if scenario != 'cold' else b'')
        row = dict(implementation=implementation, scenario=scenario, seconds=seconds, exit_code=code,
                   cli_help_valid=expected in help_text,
                   build_log=dict(path=log.name, sha256=sha(log)),
                   cargo_timing=dict(path=timing.name, sha256=sha(timing)) if timing.exists() else None)
        result['builds'].append(row)
        save()
        print(json.dumps({k: row[k] for k in ('implementation', 'scenario', 'seconds', 'cli_help_valid')}), flush=True)
        if code or not row['cli_help_valid']:
            raise RuntimeError(f'build failed or wrong CLI; see {log}')

    try:
        subprocess.run(['cargo', 'fetch', '--locked'], cwd=project, env=env, check=True, capture_output=True)
        for implementation in ('nanocompile', 'kache'):
            build(implementation, 'cold')
        leaf.write_bytes(leaf_original.replace(HELP, HELP + b' (build-cache source edit)', 1))
        for implementation in ('nanocompile', 'kache'):
            build(implementation, 'leaf')
        for i in range(args.pairs):
            shared.write_bytes(shared_original.replace(PARSER, PARSER.replace(b'trim()', VARIANTS[i]), 1))
            order = ('nanocompile', 'kache') if i % 2 == 0 else ('kache', 'nanocompile')
            for implementation in order:
                build(implementation, f'shared-{i}')
        pairs = []
        for i in range(args.pairs):
            rows = {b['implementation']: b['seconds'] for b in result['builds'] if b['scenario'] == f'shared-{i}'}
            pairs.append(dict(variant=VARIANTS[i].decode(), first='nanocompile' if i % 2 == 0 else 'kache', **rows))
        nano = [x['nanocompile'] for x in pairs]
        other = [x['kache'] for x in pairs]
        saved = [k - n for n, k in zip(nano, other)]
        result['pairs'] = pairs
        result['summary'] = dict(nanocompile_median=statistics.median(nano), kache_median=statistics.median(other),
                                 nano_pair_wins=sum(s > 0 for s in saved), mean_saved=statistics.mean(saved),
                                 standard_error=statistics.stdev(saved) / len(saved) ** 0.5 if len(saved) > 1 else None)
        result['completed'] = True
        save()
        print(json.dumps(result['summary']), flush=True)
    finally:
        stop_daemon()
        leaf.write_bytes(leaf_original)
        shared.write_bytes(shared_original)


if __name__ == '__main__':
    main()
