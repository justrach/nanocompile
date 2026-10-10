"""Compare real Harness leaf/shared edits and reversions in a disposable dirty-source snapshot."""
import argparse
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
from project_artifacts import compiled_scripts
import platform
import shutil
import signal
import statistics
import subprocess
import time

from project_benchmark import sha


def tree_rss(pid):
    rows = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,rss='], text=True)
    entries = [tuple(map(int, row.split())) for row in rows.splitlines() if row.strip()]
    descendants = {pid}
    for _ in range(30):
        new = descendants | {p for p, parent, _ in entries if parent in descendants}
        if new == descendants:
            break
        descendants = new
    return sum(rss for p, _, rss in entries if p in descendants) * 1024


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("binary")
    p.add_argument("project")
    p.add_argument("--kache", required=True)
    p.add_argument("--package", default="harness-adapters")
    p.add_argument("--state", required=True, help="new, dedicated benchmark directory")
    p.add_argument("--output", required=True)
    p.add_argument("--runs", type=int, default=1, choices=(1,), help="one fully verified edit sequence; each point is a single sample")
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--native-clang", action="store_true", help="opt Nano into Apple Clang native CAS; validate each mode against its own cold artifacts")
    p.add_argument("--standalone", action="store_true", help="disable kache's daemon for this comparison")
    p.add_argument("--proc-macros", choices=("tracked", "reported"), default="tracked", help="nanocompile proc-macro input policy; reported requires declaring unreported file reads")
    p.add_argument("--proc-macro-producers", action="store_true", help="enable the experimental macOS producer cache; verify macro dylib artifacts too")
    p.add_argument("--executable-producers", action="store_true", help="enable experimental macOS executable compilation caching")
    p.add_argument("--build-script-contract", type=Path)
    p.add_argument('--compiler-stream', action='store_true')
    p.add_argument('--pipelined-companions', action='store_true')
    p.add_argument('--native-artifacts', action='store_true', help='hash native objects/archives without changing the compiler')
    p.add_argument('--no-compiler-stream', action='store_true', help='disable default Rust stream forwarding')
    p.add_argument('--no-pipelined-companions', action='store_true', help='disable default guarded companion membership')
    args = p.parse_args()
    if (args.compiler_stream and args.no_compiler_stream) or (args.pipelined_companions and args.no_pipelined_companions):
        p.error('choose either enable or disable for each compiler control')
    if args.runs < 1 or args.jobs < 1:
        p.error("runs and jobs must be positive")
    binary, kache = str(Path(args.binary).resolve()), str(Path(args.kache).resolve())
    original_project, state = Path(args.project).resolve(), Path(args.state).resolve()
    project = state / "project"
    state.mkdir(parents=True, mode=0o700, exist_ok=False)
    original_tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=original_project).decode().split('\0')
    original_hashes = {name: sha(original_project/name) for name in original_tracked if name and
                       (name.endswith(('.rs','.toml')) or Path(name).name == 'Cargo.lock') and (original_project/name).is_file()}
    subprocess.run(['git','clone','--shared','--quiet',str(original_project),str(project)],check=True)
    names = subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=original_project).decode().split('\0')
    for name in names:
        if not name or Path(name).name.startswith('.env') or any(part in ('.worktrees','.git','target','node_modules') for part in Path(name).parts): continue
        src, dst = original_project/name, project/name
        if src.is_file() or src.is_symlink():
            dst.parent.mkdir(parents=True,exist_ok=True)
            if dst.is_symlink(): dst.unlink()
            shutil.copy2(src,dst,follow_symlinks=False)
        elif src.is_dir():
            shutil.copytree(src,dst,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.git','.worktrees','target','node_modules','.env*'))
        elif dst.is_file(): dst.unlink()
    leaf, shared = project/'crates/harness/src/lib.rs', project/'crates/proto/src/lib.rs'
    assert leaf.is_file() and shared.is_file() and not leaf.is_symlink() and not shared.is_symlink()
    originals = {path:path.read_bytes() for path in (leaf,shared)}
    suffix = hashlib.sha256(str(state).encode()).hexdigest()[:12]
    leaf_name, shared_name = 'nanocompile_benchmark_probe_' + suffix, 'nanocompile_benchmark_shared_' + suffix
    assert leaf_name.encode() not in originals[leaf] and shared_name.encode() not in originals[shared]
    scenario, expected, verifying = 'initial', 300, False
    def edit(leaf_value, shared_value):
        leaf.write_bytes(originals[leaf]+f'\npub fn {leaf_name}() -> u64 {{ harness_proto::{shared_name}() + {leaf_value} }}\n'.encode())
        shared.write_bytes(originals[shared]+f'\npub fn {shared_name}() -> u64 {{ {shared_value} }}\n'.encode())
    edit(100,200)
    probe = state/'probe.rs'
    probe.write_text('fn main() { println!("{}", harness_adapters::' + leaf_name + '()); }\n')
    config = state / "kache.toml"
    config.write_text("[cache]\nrecord_sessions=true\n")
    target, cache, kcache = state / "target", state / "nano-cache", state / "kache-cache"
    # One environment for every build except RUSTC_WRAPPER. Remote credentials,
    # other wrapper overrides and user kache configuration are excluded.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("R2_", "KACHE_", "NANOCOMPILE_"))
           and k not in ("RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER")}
    env.update(CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL="0", NANOCOMPILE_DIR=str(cache),
               KACHE_CACHE_DIR=str(kcache), KACHE_CONFIG=str(config), KACHE_HOST_CONFIG="",
               NANOCOMPILE_PROC_MACROS=args.proc_macros, KACHE_SOCKET_PATH=str(state / "daemon.sock"), KACHE_DAEMON_IDLE_TIMEOUT="600")
    if args.no_compiler_stream:
        env['NANOCOMPILE_STREAM_COMPILER'] = '0'
    if args.no_pipelined_companions:
        env['NANOCOMPILE_PIPELINED_COMPANIONS'] = '0'
    if args.compiler_stream:
        env['NANOCOMPILE_STREAM_COMPILER'] = '1'
    if args.pipelined_companions:
        env['NANOCOMPILE_PIPELINED_COMPANIONS'] = '1'
    if args.build_script_contract:
        env["NANOCOMPILE_BUILD_SCRIPTS_FILE"] = str(args.build_script_contract.resolve())
    if args.proc_macro_producers:
        env["NANOCOMPILE_PROC_MACRO_PRODUCERS"] = "1"
    if args.executable_producers:
        env["NANOCOMPILE_EXECUTABLE_PRODUCERS"] = "1"
    command = ["cargo", "build", "--release", "--locked", "--offline", "--lib",
               "-p", args.package, "-j", str(args.jobs), "--message-format=json-render-diagnostics"]
    result = {"compiler_stream": env.get("NANOCOMPILE_STREAM_COMPILER"), "pipelined_companions": env.get("NANOCOMPILE_PIPELINED_COMPANIONS"), "probe_functions": [leaf_name, shared_name], "original_project":str(original_project), "source_edits":"exported leaf function and shared dependency function; linked result checked; history-cache timed builds compared to empty-cache builds at identical paths", "script_sha256": sha(Path(__file__)), "project": str(project), "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, text=True).strip(),
              "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=project)),
              "platform": platform.platform(), "jobs": args.jobs, "runs": args.runs,
              "rustc": subprocess.check_output(["rustc", "--version", "--verbose"], cwd=project, text=True),
              "nanocompile_sha256": sha(Path(binary)), "kache_sha256": sha(Path(kache)),
              "kache_version": subprocess.check_output([kache, "--version"], text=True).strip(),
              "build_script_contract_sha256": sha(args.build_script_contract) if args.build_script_contract else None, "kache_daemon": not args.standalone, "native_clang": args.native_clang, "native_artifacts": args.native_artifacts, "nanocompile_proc_macros": args.proc_macros, "nanocompile_proc_macro_producers": args.proc_macro_producers, "nanocompile_executable_producers": args.executable_producers, "command": command,
              "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "builds": [],
              "method": f"disposable tracked/untracked dirty-source snapshot; one cold + leaf/shared/revert sequence; clean target before every build; retained cache timed edits; empty-cache artifact equality reference after each wrapper edit; linked behavior probe; fixed paths and {args.jobs} jobs; no human source edits"}
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=project).decode().split('\0')
    result['tracked_rust_and_manifest_hashes'] = {
        name: sha(project / name) for name in tracked
        if name and (name.endswith(('.rs', '.toml')) or Path(name).name == 'Cargo.lock') and (project / name).is_file()
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        output.write_text(json.dumps(result, indent=2) + "\n")

    def nano_events():
        return collections.Counter((cache / "events").read_text().splitlines()) if (cache / "events").exists() else collections.Counter()

    def kache_events():
        path = kcache / "events.jsonl"
        counts = collections.Counter()
        if path.exists():
            for line in path.read_text().splitlines():
                event = json.loads(line)
                counts[event.get("result", "unknown")] += 1
        return counts

    references = {}
    macro_references = {}
    executable_references = {}
    compiled_script_references = {}
    native_references = {}

    def build(implementation, phase):
        shutil.rmtree(target, ignore_errors=True)
        before = nano_events() if implementation == "nanocompile" else kache_events() if implementation == "kache" else collections.Counter()
        build_env = dict(env)
        if implementation != "direct":
            build_env["RUSTC_WRAPPER"] = binary if implementation == "nanocompile" else kache
        if implementation == "nanocompile" and args.native_clang:
            build_env['CC'] = binary + ' clang'
            build_env['CC_KNOWN_WRAPPER_CUSTOM'] = Path(binary).name
            build_env['NANOCOMPILE_CLANG_REMARKS'] = '1'
        number = len(result["builds"])
        print(f"Starting {implementation} {phase} clean release build {number + 1}", flush=True)
        log_path = state / f"{number}-{implementation}-{phase}.log"
        start = time.monotonic()
        peak = 0
        last_sample = 0
        with log_path.open("w") as log:
            proc = subprocess.Popen(command, cwd=project, env=build_env, stdout=log, stderr=log, start_new_session=True)
            while proc.poll() is None:
                if time.monotonic() - last_sample > .5:
                    peak = max(peak, tree_rss(os.getpid()))
                    last_sample = time.monotonic()
                if peak > 40 * 1024**3 or time.monotonic() - start > 3600:
                    os.killpg(proc.pid, signal.SIGTERM)
                    proc.wait(timeout=15)
                    raise RuntimeError('Build exceeded memory/time limit; see ' + str(log_path))
                try:
                    proc.wait(timeout=.1)
                except subprocess.TimeoutExpired:
                    pass
        seconds = time.monotonic() - start
        after = nano_events() if implementation == "nanocompile" else kache_events() if implementation == "kache" else collections.Counter()
        artifacts = {str(path.relative_to(target)): sha(path) for path in sorted((target / "release/deps").glob("*.rlib"))}
        macros = {str(path.relative_to(target)): sha(path) for path in sorted((target / "release/deps").glob("*.dylib"))}
        executables = {str(path.relative_to(target)): sha(path) for path in sorted((target / "release/build").glob("*/*")) if path.is_file() and (path.name == "build-script-build" or path.name.endswith(".nano-real"))}
        compiled_executables = compiled_scripts(target)
        native = {str(path.relative_to(target)): sha(path) for path in sorted(target.rglob('*'))
                  if path.is_file() and path.suffix in ('.o', '.a')} if args.native_clang or args.native_artifacts else {}
        row = {"native_objects_and_archives": native, "implementation": implementation, "phase": phase, "seconds": seconds,
               "exit_code": proc.returncode, "events": dict(after - before), "rlibs": len(artifacts), "artifacts": artifacts,
               "scenario":scenario, "verification":verifying, "expected_probe":expected, "peak_sampled_process_tree_rss_bytes": peak, "macro_dylibs": macros, "build_script_executables": executables, "compiled_build_script_executables": compiled_executables}
        reference_key = (scenario, implementation)
        if reference_key not in references:
            references[reference_key] = artifacts
            macro_references[reference_key] = macros
            executable_references[reference_key] = executables
            compiled_script_references[reference_key] = compiled_executables
            native_references[reference_key] = native
        else:
            row["matches_own_cold_native_artifacts"] = native_references[reference_key] == native
            row["matches_own_cold_artifacts"] = references[reference_key] == artifacts
            row["matches_own_cold_macro_dylibs"] = macro_references[reference_key] == macros
            row["matches_own_cold_build_script_executables"] = executable_references[reference_key] == executables
        if not args.native_clang:
            direct_key = (scenario, "direct")
            if direct_key in references:
                # Rotation can put Nano before direct for an edit. Compare
                # retained rows once that scenario's direct outputs exist.
                for candidate in [*result['builds'], row]:
                    if candidate['scenario'] != scenario or candidate['implementation'] != 'nanocompile':
                        continue
                    candidate['matches_direct_artifacts'] = candidate['artifacts'] == references[direct_key]
                    candidate['matches_direct_macro_dylibs'] = candidate['macro_dylibs'] == macro_references[direct_key]
                    candidate['matches_direct_build_script_executables'] = candidate['compiled_build_script_executables'] == compiled_script_references[direct_key]
                    candidate.pop('direct_comparison_pending', None)
            elif implementation == 'nanocompile':
                row['direct_comparison_pending'] = True
        assert proc.returncode == 0, log_path.read_text()[-4000:]
        library = next((target/'release/deps').glob('libharness_adapters-*.rlib'))
        probe_output = state/'probe'
        checked = subprocess.run(['rustc',str(probe),'--edition=2024','-C','lto=thin','-C','opt-level=3','--extern','harness_adapters='+str(library),
                                  '-Ldependency='+str(target/'release/deps'),'-o',str(probe_output)],
                                  cwd=project,env=env,capture_output=True,timeout=180)
        assert checked.returncode == 0, checked.stderr.decode(errors='replace')[-4000:]
        observed = int(subprocess.check_output([str(probe_output)],env=env,text=True).strip())
        assert observed == expected, (scenario,implementation,expected,observed)
        row['observed_probe'] = observed
        result["builds"].append(row)
        save()
        print(json.dumps({k: v for k, v in row.items() if k not in ("artifacts", "macro_dylibs", "build_script_executables", "native_objects_and_archives", "compiled_build_script_executables")}), flush=True)
        if proc.returncode or not artifacts:
            raise RuntimeError(f"Build failed or produced no libraries; see {log_path}")
        if any(record.get(check) is False for record in result['builds'] for check in ("matches_own_cold_native_artifacts", "matches_own_cold_artifacts", "matches_direct_artifacts", "matches_own_cold_macro_dylibs", "matches_direct_macro_dylibs", "matches_own_cold_build_script_executables", "matches_direct_build_script_executables")):
            raise RuntimeError(f"Artifact validation failed; see {log_path}")
        if phase == "warm" and implementation == "nanocompile" and args.native_clang:
            if row['events'].get('clang_native_hit', 0) < 20 or row['events'].get('hit', 0) < 165:
                raise RuntimeError('Nano native or Rust cache did not serve expected warm hits')
        if phase == "warm" and implementation == "kache" and not row["events"].get("local_hit", 0):
            raise RuntimeError("kache recorded no local hits; comparison is invalid")

    if args.native_clang:
        result['method'] += '; Nano explicitly uses CC=nanocompile clang and native remarks; direct and kache retain their usual native compiler selection. Inline scanner changes debug representation, so every mode must match its own cold Rust, macro, executable and native artifact bytes. RSS includes benchmark parent, private kache daemon and Cargo descendants.'
    daemon = None
    daemon_log = (state/'daemon.log').open('w')
    def stop_daemon():
        nonlocal daemon
        if daemon is not None:
            daemon.send_signal(signal.SIGINT)
            try: daemon.wait(timeout=15)
            except subprocess.TimeoutExpired: daemon.kill(); daemon.wait()
            daemon = None
    def start_daemon():
        nonlocal daemon
        if args.standalone: return
        daemon = subprocess.Popen([kache,'daemon','run'],cwd=project,env=env,stdout=daemon_log,stderr=daemon_log)
        deadline=time.monotonic()+15
        while not (state/'daemon.sock').exists():
            if daemon.poll() is not None or time.monotonic()>deadline: raise RuntimeError('Private kache daemon did not start')
            time.sleep(.1)
    try:
        subprocess.run(['cargo','fetch','--locked'],cwd=project,env=env,check=True,capture_output=True)
        start_daemon()
        schedule=['direct','nanocompile','kache']
        for implementation in schedule: build(implementation,'cold')
        for number,(scenario,lv,sv,expected) in enumerate([('leaf-edit',101,200,301),('shared-edit',101,211,312),('revert',100,200,300)]):
            edit(lv,sv)
            rotated=schedule[number%3:]+schedule[:number%3]
            for implementation in rotated:
                verifying=False
                build(implementation,'edit')
                if implementation == 'direct': continue
                active=cache if implementation=='nanocompile' else kcache
                saved=state/('saved-'+implementation)
                if implementation=='kache': stop_daemon()
                active.rename(saved)
                active.mkdir()
                if implementation=='kache': start_daemon()
                try:
                    verifying=True
                    build(implementation,'empty-cache-reference')
                    assert all(result['builds'][-1][check] for check in ('matches_own_cold_native_artifacts','matches_own_cold_artifacts','matches_own_cold_macro_dylibs','matches_own_cold_build_script_executables'))
                finally:
                    if implementation=='kache': stop_daemon()
                    shutil.rmtree(active)
                    saved.rename(active)
                    if implementation=='kache': start_daemon()
                    verifying=False
        assert not any(row.get('direct_comparison_pending') for row in result['builds']), 'Missing direct artifact references'
        result['summary']={phase:{mode:next(r['seconds'] for r in result['builds'] if r['scenario']==phase and r['implementation']==mode and not r['verification']) for mode in schedule} for phase in ('initial','leaf-edit','shared-edit','revert')}
        result['original_tracked_sources_unchanged']=all((original_project/name).is_file() and sha(original_project/name)==digest for name,digest in original_hashes.items())
        assert result['original_tracked_sources_unchanged']
        result['original_tracked_rust_and_manifest_hashes']=original_hashes
        result['snapshot_sources_unchanged_except_declared_edits']=all((project/name).is_file() and sha(project/name)==digest for name,digest in result['tracked_rust_and_manifest_hashes'].items() if name not in ('crates/harness/src/lib.rs','crates/proto/src/lib.rs'))
        assert result['snapshot_sources_unchanged_except_declared_edits']
        save()
        print(json.dumps(result['summary'],indent=2),flush=True)
    finally:
        stop_daemon()
        daemon_log.close()


if __name__ == "__main__":
    main()
