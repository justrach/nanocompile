"""Measure real clean Xcode builds, compiler interception and object integrity."""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import statistics
import subprocess
import time

SHIM = '''#!/usr/bin/env python3
import json, os, pathlib, sys
root = pathlib.Path(__file__).parent
cfg = json.loads((root / "config.json").read_text())
kind = pathlib.Path(sys.argv[0]).name
real = cfg["compilers"][kind]
mode = cfg["mode"]
# kache 1.0.0 rejects swiftc as an unrecognized CLI subcommand. Preserve
# Swift compilation and explicitly count this unsupported family.
supported = kind != "swiftc"
argv = [real, *sys.argv[1:]]
route = "direct"
if mode == "nanocompile":
    argv = [cfg["nanocompile"], *argv]
    route = "nanocompile"
elif mode == "kache" and supported:
    argv = [cfg["kache"], *argv]
    route = "kache"
elif mode == "kache":
    route = "unsupported_by_kache"
record = json.dumps({"compiler": kind, "route": route, "compile": ("-c" in sys.argv and "-E" not in sys.argv) or "-emit-object" in sys.argv, "argv": sys.argv[1:]}) + "\\n"
fd = os.open(root / "calls.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
os.write(fd, record.encode()); os.close(fd)
os.execv(argv[0], argv)
'''


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def tree_rss(pid):
    rows = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,rss='], text=True)
    entries = [tuple(map(int, r.split())) for r in rows.splitlines() if r.strip()]
    descendants = {pid}
    for _ in range(30):
        new = descendants | {p for p, parent, _ in entries if parent in descendants}
        if new == descendants:
            break
        descendants = new
    return sum(rss for p, _, rss in entries if p in descendants) * 1024


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('project', help='source .xcodeproj; benchmark copies its parent folder')
    p.add_argument('--scheme', required=True)
    p.add_argument('--destination', default='generic/platform=iOS Simulator')
    p.add_argument('--configuration', default='Release')
    p.add_argument('--developer-dir', default='/Applications/Xcode.app/Contents/Developer')
    p.add_argument('--nanocompile', required=True)
    p.add_argument('--kache', required=True)
    p.add_argument('--state', required=True, help='new dedicated directory')
    p.add_argument('--output', required=True)
    p.add_argument('--runs', type=int, default=3)
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--package-cache', help='reuse a private SwiftPM package/artifact cache')
    p.add_argument('--packages', help='reuse already resolved package checkouts')
    p.add_argument('--wrap-swift', action='store_true', help='diagnostic variant: wrap Swift and disable the integrated driver')
    p.add_argument('--verify-app', help='relative Products path of an iOS app bundle to validate')
    p.add_argument('--native-cache', action='store_true', help="also compare Xcode's compilation cache")
    p.add_argument('--managed-xcode', action='store_true', help='also compare nanocompile xcodebuild using the native CAS')
    p.add_argument('--verify-executable', help='relative Products path of a CLI fixture to execute')
    args = p.parse_args()
    if args.runs < 1 or args.jobs < 1:
        p.error('runs and jobs must be positive')
    original = Path(args.project).resolve()
    provenance = {}
    try:
        provenance = {'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=original.parent, text=True).strip(), 'git_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=original.parent))}
    except subprocess.CalledProcessError:
        pass
    state = Path(args.state).resolve()
    state.mkdir(parents=True, mode=0o700, exist_ok=False)
    source = state / 'source'
    shutil.copytree(original.parent, source, ignore=shutil.ignore_patterns('app-store', 'xcuserdata', '.DS_Store', 'DerivedData'))
    project = source / original.name
    derived = state / 'derived'
    packages = Path(args.packages).resolve() if args.packages else state / 'packages'
    package_cache = Path(args.package_cache).resolve() if args.package_cache else state / 'package-cache'
    env = {k: v for k, v in os.environ.items() if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_')) and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'CC', 'CXX', 'SWIFT_EXEC')}
    env.update(DEVELOPER_DIR=args.developer_dir, CARGO_INCREMENTAL='0',
               NANOCOMPILE_DIR=str(state / 'nano-cache'), KACHE_CACHE_DIR=str(state / 'kache-cache'),
               KACHE_SOCKET_PATH=str(state / 'daemon.sock'), KACHE_HOST_CONFIG='',
               KACHE_LOCAL_ONLY='1', SOURCE_DATE_EPOCH='0')
    config = state / 'kache.toml'
    config.write_text('[cache]\nrecord_sessions=true\n')
    env['KACHE_CONFIG'] = str(config)
    binary, kache = str(Path(args.nanocompile).resolve()), str(Path(args.kache).resolve())
    shims = state / 'shims'
    shims.mkdir()
    compilers = {kind: subprocess.check_output(['xcrun', '--find', kind], env=env, text=True).strip() for kind in ('clang', 'clang++', 'swiftc')}
    for kind in compilers:
        script = shims / kind
        script.write_text(SHIM)
        script.chmod(0o700)
    cfg = {'compilers': compilers, 'nanocompile': binary, 'kache': kache, 'mode': 'direct'}
    (shims / 'config.json').write_text(json.dumps(cfg))
    base = ['xcodebuild', '-project', str(project), '-scheme', args.scheme,
            '-clonedSourcePackagesDirPath', str(packages), '-packageCachePath', str(package_cache)]
    resolve = [*base, '-resolvePackageDependencies']
    with (state / 'resolve.log').open('w') as log:
        subprocess.run(resolve, cwd=source, env=env, stdout=log, stderr=log, check=True, timeout=900)
    command = [*base, '-configuration', args.configuration, '-destination', args.destination,
               '-derivedDataPath', str(derived), '-jobs', str(args.jobs), '-disableAutomaticPackageResolution',
               '-onlyUsePackageVersionsFromResolvedFile', '-skipPackageUpdates', '-showBuildTimingSummary',
               'CODE_SIGNING_ALLOWED=NO', 'COMPILER_INDEX_STORE_ENABLE=NO',
               'COMPILATION_CACHE_ENABLE_DIAGNOSTIC_REMARKS=YES',
               'CC=' + str(shims / 'clang'), 'CXX=' + str(shims / 'clang++'), 'build']
    if args.wrap_swift:
        command += ['SWIFT_USE_INTEGRATED_DRIVER=NO', 'SWIFT_EXEC=' + str(shims / 'swiftc')]
    result = {'timestamp': time.time(), 'original_project': str(original), 'provenance': provenance, 'scheme': args.scheme,
              'platform': platform.platform(), 'jobs': args.jobs, 'runs': args.runs, 'command': command,
              'xcode': subprocess.check_output(['xcodebuild', '-version'], env=env, text=True).strip(),
              'swift': subprocess.check_output([compilers['swiftc'], '--version'], env=env, text=True).strip(),
              'clang': subprocess.check_output([compilers['clang'], '--version'], env=env, text=True).strip(),
              'nanocompile_sha256': sha(Path(binary)), 'kache_sha256': sha(Path(kache)),
              'kache_version': subprocess.check_output([kache, '--version'], text=True).strip(),
              'source_files': {str(f.relative_to(source)): sha(f) for f in sorted(source.rglob('*')) if f.is_file()},
              'method': 'copied source snapshot; resolve packages outside timing; delete only dedicated DerivedData/Build before each build; preserve SDK/module caches equally; no signing; direct, apple-cache and nanocompile-xcode use native tools; nanocompile/kache compiler launcher modes include Python instrumentation overhead; native Swift driver retained unless wrap_swift is explicit; native compilation caching enabled only in apple-cache and nanocompile-xcode modes',
              'wrap_swift': args.wrap_swift, 'builds': []}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    def save():
        output.write_text(json.dumps(result, indent=2) + '\n')
    def events(mode):
        file = state / ('nano-cache/events' if mode in ('nanocompile', 'nanocompile-xcode') else 'kache-cache/events.jsonl')
        if not file.exists():
            return collections.Counter()
        if mode in ('nanocompile', 'nanocompile-xcode'):
            return collections.Counter(file.read_text().splitlines())
        return collections.Counter(json.loads(line).get('result', 'unknown') for line in file.read_text().splitlines())
    def refused():
        file = state / 'kache-cache/events.jsonl'
        return collections.Counter(json.loads(line).get('passthrough_reason', '') for line in file.read_text().splitlines() if json.loads(line).get('result') == 'passthrough') if file.exists() else collections.Counter()
    references = {}
    def build(mode, phase):
        shutil.rmtree(derived / 'Build', ignore_errors=True)
        cfg['mode'] = mode
        (shims / 'config.json').write_text(json.dumps(cfg))
        (shims / 'calls.jsonl').write_text('')
        before = events(mode)
        refused_before = refused()
        number = len(result['builds'])
        log_path = state / f'{number}-{mode}-{phase}.log'
        print(f'Starting {mode} {phase} Xcode build {number + 1}', flush=True)
        start = time.monotonic()
        peak = 0
        last_sample = 0
        build_command = list(command)
        if mode in ('direct', 'apple-cache', 'nanocompile-xcode'):
            build_command = [v for v in build_command if not v.startswith(('CC=', 'CXX=', 'SWIFT_EXEC=', 'SWIFT_USE_INTEGRATED_DRIVER='))]
        if mode == 'nanocompile-xcode':
            build_command = [binary, 'xcodebuild', *build_command[1:]]
        if mode != 'nanocompile-xcode':
            build_command.append('COMPILATION_CACHE_ENABLE_CACHING=' + ('YES' if mode == 'apple-cache' else 'NO'))
        with log_path.open('w') as log:
            proc = subprocess.Popen(build_command, cwd=source, env=env, stdout=log, stderr=log, start_new_session=True)
            while proc.poll() is None:
                if time.monotonic() - last_sample > .5:
                    peak = max(peak, tree_rss(proc.pid))
                    last_sample = time.monotonic()
                if peak > 40 * 1024**3 or time.monotonic() - start > 3600:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=15)
                    raise RuntimeError('Xcode build exceeded memory/time limit; see ' + str(log_path))
                try:
                    proc.wait(timeout=.1)
                except subprocess.TimeoutExpired:
                    pass
        seconds = time.monotonic() - start
        calls = [json.loads(line) for line in (shims / 'calls.jsonl').read_text().splitlines()]
        artifacts = {str(f.relative_to(derived / 'Build')): sha(f) for f in sorted((derived / 'Build').rglob('*')) if f.is_file() and f.suffix in ('.o', '.a')}
        products = [str(f.relative_to(derived / 'Build/Products')) for f in (derived / 'Build/Products').rglob('*') if f.is_file() and f.parent.name == 'MacOS']
        row = {'implementation': mode, 'phase': phase, 'seconds': seconds, 'exit_code': proc.returncode,
               'peak_sampled_process_tree_rss_bytes': peak, 'events': dict(events(mode) - before), 'kache_passthrough_reasons': dict(refused() - refused_before) if mode == 'kache' else {},
               'compiler_calls': dict(collections.Counter(c['compiler'] for c in calls)),
               'compiler_routes': dict(collections.Counter(c['route'] for c in calls)),
               'compile_calls': sum(c['compile'] for c in calls), 'objects_and_archives': len(artifacts),
               'artifacts': artifacts, 'products': products, 'log': str(log_path),
               'clang_compile_tasks': len(re.findall(r'^CompileC ', log_path.read_text(), re.MULTILINE)),
               'swift_compile_tasks': len(re.findall(r'^SwiftCompile ', log_path.read_text(), re.MULTILINE)),
               'cache_diagnostic_lines': [line.strip() for line in log_path.read_text().splitlines() if re.search(r'cache (hit|miss)', line, re.I)]}
        if mode in references:
            row['matches_own_cold_objects'] = artifacts == references[mode]
        else:
            references[mode] = artifacts
        if args.verify_app and proc.returncode == 0:
            import plistlib
            bundle = derived / 'Build/Products' / args.verify_app
            with (bundle / 'Info.plist').open('rb') as f:
                info = plistlib.load(f)
            executable = bundle / info['CFBundleExecutable']
            with executable.open('rb') as f:
                if f.read(4) not in (b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe'):
                    raise RuntimeError('App executable is not Mach-O')
            row['app_validated'] = {'bundle': args.verify_app, 'identifier': info['CFBundleIdentifier'], 'executable_sha256': sha(executable)}
        if args.verify_executable and proc.returncode == 0:
            row['executable_stdout'] = subprocess.check_output([str(derived / 'Build/Products' / args.verify_executable)], text=True).strip()
            if row['executable_stdout'] != 'fixture-ok':
                raise RuntimeError('Fixture executable validation failed')
        result['builds'].append(row)
        save()
        print(json.dumps({k: v for k, v in row.items() if k not in ('artifacts', 'products', 'cache_diagnostic_lines')}), flush=True)
        if proc.returncode:
            raise RuntimeError('Xcode build failed; see ' + str(log_path))
        if not artifacts:
            raise RuntimeError('Build produced no objects: cannot validate the workload')
        if row.get('matches_own_cold_objects') is False:
            raise RuntimeError('Object hashes changed; result retained but cache restoration is unproven')
        if mode not in ('direct', 'apple-cache', 'nanocompile-xcode') and not calls:
            raise RuntimeError('No compiler interception: comparison is unproven')
        # A zero-hit result is valid evidence of missing Xcode coverage. Do not
        # turn passthrough builds into a claimed cache speedup.
    daemon = None
    try:
        subprocess.run([binary, 'doctor'], env=env, capture_output=True, check=True)
        with (state / 'daemon.log').open('w') as log:
            daemon = subprocess.Popen([kache, 'daemon', 'run'], env=env, stdout=log, stderr=log)
        deadline = time.monotonic() + 15
        while not (state / 'daemon.sock').exists():
            if daemon.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError('Private kache daemon failed to start')
            time.sleep(.1)
        modes = ['direct', 'nanocompile', 'kache'] + (['apple-cache'] if args.native_cache else []) + (['nanocompile-xcode'] if args.managed_xcode else [])
        build('direct', 'prime')
        for mode in modes[1:]:
            build(mode, 'cold')
        for iteration in range(args.runs):
            offset = iteration % len(modes)
            for mode in modes[offset:] + modes[:offset]:
                build(mode, 'warm')
        result['summary'] = {mode: {'median_seconds': statistics.median(r['seconds'] for r in result['builds'] if r['implementation'] == mode and r['phase'] == 'warm')} for mode in modes}
        result['kache_stats'] = json.loads(subprocess.check_output([kache, '--json', 'stats'], env=env, text=True))
        save()
        print(json.dumps(result['summary'], indent=2), flush=True)
    finally:
        if daemon and daemon.poll() is None:
            daemon.send_signal(signal.SIGINT)
            try:
                daemon.wait(timeout=10)
            except subprocess.TimeoutExpired:
                daemon.kill(); daemon.wait()


if __name__ == '__main__':
    main()
