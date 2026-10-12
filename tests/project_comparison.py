"""Compare direct Cargo, nanocompile and kache on clean real-project builds."""
import argparse
from benchmark_storage import require_space, save_report, save_failure
from bindgen_controls import load as bindgen_controls
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import statistics
import subprocess
import time
import sys
from project_artifacts import compiled_scripts
from reference_artifacts import retain
from executable_probe import probe_help

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from build_trace import Capture

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
    p.add_argument("--bin", help="build this package binary instead of its library; validate the final executable too")
    p.add_argument("--probe-help", action="store_true", help="verify the selected binary's --help outside build timing")
    p.add_argument("--source-date-epoch", type=int, help="explicit reproducible build timestamp shared by every implementation")
    p.add_argument("--retain-artifacts", action="store_true", help="keep private first-build artifact bytes for later mismatch diagnosis; excluded from timing")
    p.add_argument("--state", required=True, help="new, dedicated benchmark directory")
    p.add_argument("--output", required=True)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--cold-runs", type=int, default=1, help="alternating fresh-cache comparisons; restart private daemon before each pair")
    p.add_argument("--cold-only", action="store_true", help="skip warm builds")
    p.add_argument("--warm-caches-only", action="store_true", help="alternate Nano/kache warm builds; retain the direct prime but omit repeated direct builds")
    p.add_argument("--native-clang", action="store_true", help="opt Nano into Apple Clang native CAS; validate each mode against its own cold artifacts")
    p.add_argument("--native-artifacts", action="store_true", help="validate native outputs without changing the native compiler")
    p.add_argument("--portable-cc", action="store_true", help="opt Nano into portable compile-only C/C++ caching")
    p.add_argument("--standalone", action="store_true", help="disable kache's daemon for this comparison")
    p.add_argument("--proc-macros", choices=("tracked", "reported"), default="tracked", help="nanocompile proc-macro input policy; reported requires declaring unreported file reads")
    p.add_argument("--proc-macro-producers", action="store_true", help="enable the experimental macOS producer cache; verify macro dylib artifacts too")
    p.add_argument("--thin-lto-producers", action="store_true", help="opt-in stable-alias LTO candidate; preserve own-cold byte gates")
    p.add_argument("--rlib-frameworks", action="store_true", help="opt-in native macOS rlib command-line framework metadata caching")
    p.add_argument("--staticlib-companions", action="store_true", help="opt-in pinned native macOS mixed lib/staticlib archive caching")
    p.add_argument("--executable-producers", action="store_true", help="enable experimental macOS executable compilation caching")
    p.add_argument("--build-script-contract", type=Path, help="opt Nano into explicit whole build-script execution contracts")
    p.add_argument("--bindgen-tools-file", type=Path, help="explicit libclang, clang and rustfmt paths shared by all implementations")
    p.add_argument("--kache-no-build-scripts", action="store_true", help="diagnostic ablation: disable only kache build-script execution caching")
    p.add_argument("--compiler-stream", action="store_true", help="experimental immediate Rust compiler stream forwarding")
    p.add_argument("--script-profile", action="store_true", help="diagnostic build-script phase timings; requires execution contract")
    p.add_argument("--declared-build-scripts", action="store_true", help="cache every Nano build-script run under Cargo's rerun-if-changed rule (NANOCOMPILE_BUILD_SCRIPT_CACHE=declared); explicit contract packages keep their contract")
    p.add_argument("--record-kache-mismatches", action="store_true", help="record kache's own-cold artifact mismatches in the report instead of stopping; Nano mismatches still stop the run")
    p.add_argument("--dev", action="store_true", help="build Cargo's dev profile (target/debug) instead of --release")
    p.add_argument("--cargo-timings", action="store_true", help="keep each build's Cargo --timings report for tools/rust_profile.py; small report-writing overhead")
    p.add_argument("--trace-builds", action="store_true", help="private full compiler logs and Cargo timings; diagnostic overhead, not a benchmark")
    p.add_argument("--compiler-profile", action="store_true", help="diagnostic producer/restore phase timings; requires --trace-builds")
    p.add_argument("--nano-only", action="store_true", help="diagnostic direct prime then Nano cold/warm capture; requires --trace-builds")
    p.add_argument('--pipelined-companions', action='store_true', help='experimental guarded metadata-first archive membership')
    p.add_argument('--no-compiler-stream', action='store_true', help='disable default Rust stream forwarding')
    p.add_argument('--no-pipelined-companions', action='store_true', help='disable default guarded companion membership')
    p.add_argument("--min-free-gib", type=float, help="free-space gate before each build; default 32 for full binaries, 8 for libraries")
    args = p.parse_args()
    if args.warm_caches_only and (args.cold_only or args.nano_only):
        p.error("--warm-caches-only requires a comparison with both caches and warm builds")
    if args.nano_only and not args.trace_builds:
        p.error("--nano-only requires --trace-builds")
    if args.compiler_profile and not args.trace_builds:
        p.error("--compiler-profile requires --trace-builds")
    if args.min_free_gib is None:
        args.min_free_gib = 32 if args.bin else 8
    if not 0 < args.min_free_gib < float("inf"):
        p.error("--min-free-gib must be positive and finite")
    if args.thin_lto_producers and not args.executable_producers:
        p.error("--thin-lto-producers requires --executable-producers")
    if args.probe_help and not args.bin:
        p.error('--probe-help requires --bin')
    if args.source_date_epoch is not None and args.source_date_epoch < 0:
        p.error('--source-date-epoch must be nonnegative')
    if (args.compiler_stream and args.no_compiler_stream) or (args.pipelined_companions and args.no_pipelined_companions):
        p.error('choose either enable or disable for each compiler control')
    if args.native_clang and args.portable_cc:
        p.error("choose one native adapter")
    if args.runs < 1 or args.jobs < 1 or args.cold_runs < 1:
        p.error("runs and jobs must be positive")
    binary, kache = str(Path(args.binary).resolve()), str(Path(args.kache).resolve())
    project, state = Path(args.project).resolve(), Path(args.state).resolve()
    require_space(state, args.min_free_gib)
    state.mkdir(parents=True, mode=0o700, exist_ok=False)
    capture = Capture(state, {"nanocompile": binary} if args.nano_only else {"nanocompile": binary, "kache": kache}) if args.trace_builds else None
    config = state / "kache.toml"
    config.write_text("[cache]\nrecord_sessions=true\n")
    target, cache, kcache = state / "target", state / "nano-cache", state / "kache-cache"
    # One environment for every build except RUSTC_WRAPPER. Remote credentials,
    # other wrapper overrides and user kache configuration are excluded.
    env = {k: v for k, v in os.environ.items() if not k.startswith(("R2_", "KACHE_", "NANOCOMPILE_"))
           and k not in ("RUSTC_WRAPPER", "RUSTC_WORKSPACE_WRAPPER")}
    selected_bindgen_tools, bindgen_tools_hash = (None, None)
    if args.source_date_epoch is not None:
        env['SOURCE_DATE_EPOCH'] = str(args.source_date_epoch)
    if args.bindgen_tools_file:
        selected_bindgen_tools, bindgen_tools_hash = bindgen_controls(args.bindgen_tools_file)
        env.update(selected_bindgen_tools)
    env.update(CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL="0", NANOCOMPILE_DIR=str(cache),
               KACHE_CACHE_DIR=str(kcache), KACHE_CONFIG=str(config), KACHE_HOST_CONFIG="",
               NANOCOMPILE_PROC_MACROS=args.proc_macros, KACHE_SOCKET_PATH=str(state / "daemon.sock"), KACHE_DAEMON_IDLE_TIMEOUT="600")
    if args.build_script_contract:
        env["NANOCOMPILE_BUILD_SCRIPTS_FILE"] = str(args.build_script_contract.resolve())
    if args.pipelined_companions:
        env['NANOCOMPILE_PIPELINED_COMPANIONS'] = '1'
    if args.declared_build_scripts:
        env['NANOCOMPILE_BUILD_SCRIPT_CACHE'] = 'declared'
    if args.no_compiler_stream:
        env['NANOCOMPILE_STREAM_COMPILER'] = '0'
    if args.no_pipelined_companions:
        env['NANOCOMPILE_PIPELINED_COMPANIONS'] = '0'
    if args.compiler_stream:
        env["NANOCOMPILE_STREAM_COMPILER"] = "1"
    if args.script_profile:
        env["NANOCOMPILE_SCRIPT_PROFILE"] = "1"
        env["NANOCOMPILE_TRACE"] = "1"
    if args.kache_no_build_scripts:
        env["KACHE_BUILD_SCRIPT_CACHE"] = "0"
    if args.compiler_profile:
        env["NANOCOMPILE_COMPILER_PROFILE"] = "1"
    if capture:
        env["NANOCOMPILE_TRACE"] = "1"
    if args.proc_macro_producers:
        env["NANOCOMPILE_PROC_MACRO_PRODUCERS"] = "1"
    if args.executable_producers:
        env["NANOCOMPILE_EXECUTABLE_PRODUCERS"] = "1"
    if args.thin_lto_producers:
        env["NANOCOMPILE_THIN_LTO_PRODUCERS"] = "1"
    if args.staticlib_companions:
        env["NANOCOMPILE_RUST_STATICLIB"] = "1"
    if args.rlib_frameworks:
        env["NANOCOMPILE_RLIB_FRAMEWORKS"] = "1"
    target_options = ["--bin", args.bin] if args.bin else ["--lib"]
    profile_dir = "debug" if args.dev else "release"
    command = ["cargo", "build", *([] if args.dev else ["--release"]), "--locked", "--offline", *target_options,
               "-p", args.package, "-j", str(args.jobs), "--message-format=json-render-diagnostics"]
    if capture:
        command += ["--timings", "-vv"]
    elif args.cargo_timings:
        command += ["--timings"]
    result = {"thin_lto_producers": args.thin_lto_producers, "diagnostic_trace": bool(capture) or args.script_profile, "script_profile": args.script_profile, "compiler_stream": env.get("NANOCOMPILE_STREAM_COMPILER"), "pipelined_companions": env.get("NANOCOMPILE_PIPELINED_COMPANIONS"), "script_sha256": sha(Path(__file__)), "project": str(project), "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, text=True).strip(),
              "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=project)),
              "platform": platform.platform(), "jobs": args.jobs, "runs": args.runs, "cold_runs": args.cold_runs, "cold_only": args.cold_only,
              "rustc": subprocess.check_output(["rustc", "--version", "--verbose"], cwd=project, text=True),
              "nanocompile_sha256": sha(Path(binary)), "kache_sha256": sha(Path(kache)),
              "kache_version": subprocess.check_output([kache, "--version"], text=True).strip(),
              "build_script_contract_sha256": sha(args.build_script_contract) if args.build_script_contract else None, "kache_build_script_cache": None if args.nano_only else not args.kache_no_build_scripts, "kache_daemon": not args.standalone and not args.nano_only, "native_clang": args.native_clang, "native_artifacts": args.native_artifacts, "portable_cc":args.portable_cc, "nanocompile_proc_macros": args.proc_macros, "nanocompile_proc_macro_producers": args.proc_macro_producers, "nanocompile_declared_build_scripts": args.declared_build_scripts, "nanocompile_executable_producers": args.executable_producers, "command": command,
              "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "builds": [],
              "method": "offline clean release package builds; same target path; prime direct build then empty caches; rotate three-way warm measurement order unless cold-only; validate each wrapper against its own cold artifact hashes (kache remaps paths)"}
    result['source_date_epoch'] = env.get('SOURCE_DATE_EPOCH')
    result['nano_only'] = args.nano_only
    result['warm_caches_only'] = args.warm_caches_only
    if args.warm_caches_only:
        result['method'] = 'offline clean release builds; direct prime then empty-cache Nano/kache builds; alternate Nano/kache warm pairs with no repeated direct builds; validate each wrapper against its own cold artifact hashes (kache remaps paths)'
    if args.nano_only:
        result['method'] = 'offline clean release builds; direct prime then Nano cold/warm diagnostic capture; own-cold artifact/mode checks and source verification; no kache execution or speed comparison'
    result['compiler_profile'] = args.compiler_profile
    result['staticlib_companions'] = args.staticlib_companions
    result['rlib_frameworks'] = args.rlib_frameworks
    result['bindgen_tools_file_sha256'] = bindgen_tools_hash
    result['bindgen_tools'] = selected_bindgen_tools
    result['binary_target'] = args.bin
    result['cli_help_probe'] = args.probe_help
    result['reference_artifacts_retained'] = args.retain_artifacts
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=project).decode().split('\0')
    result['tracked_rust_and_manifest_hashes'] = {
        name: sha(project / name) for name in tracked
        if name and (name.endswith(('.rs', '.toml')) or Path(name).name == 'Cargo.lock') and (project / name).is_file()
    }
    result["minimum_free_space_gib"] = args.min_free_gib
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        save_report(output, result)

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
    final_references = {}
    mode_references = {}
    all_mode_references = {}

    def build(implementation, phase):
        shutil.rmtree(target, ignore_errors=True)
        require_space(state, args.min_free_gib)
        require_space(output.parent, min(args.min_free_gib, 1))
        before = nano_events() if implementation == "nanocompile" else kache_events() if implementation == "kache" else collections.Counter()
        build_env = dict(env)
        nano_frontend = capture.wrappers["nanocompile"] if capture else binary
        if implementation != "direct":
            build_env["RUSTC_WRAPPER"] = capture.wrappers[implementation] if capture else binary if implementation == "nanocompile" else kache
        if implementation == "nanocompile" and args.native_clang:
            build_env['CC'] = nano_frontend + ' clang'
            build_env['CC_KNOWN_WRAPPER_CUSTOM'] = Path(nano_frontend).name
            build_env['NANOCOMPILE_CLANG_REMARKS'] = '1'
        if implementation == "nanocompile" and args.portable_cc:
            build_env['CC'] = nano_frontend + ' cc'
            build_env['CXX'] = nano_frontend + ' c++'
            build_env['CC_KNOWN_WRAPPER_CUSTOM'] = Path(nano_frontend).name
        number = len(result["builds"])
        print(f"Starting {implementation} {phase} clean release build {number + 1}", flush=True)
        log_path = state / f"{number}-{implementation}-{phase}.log"
        event_path = kcache / "events.jsonl" if implementation == "kache" else cache / "events"
        event_offset = event_path.stat().st_size if event_path.exists() else 0
        if capture:
            capture.begin(number, implementation)
        origin_ns = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
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
        artifacts = {str(path.relative_to(target)): sha(path) for path in sorted((target / profile_dir / "deps").glob("*.rlib"))}
        macros = {str(path.relative_to(target)): sha(path) for path in sorted((target / profile_dir / "deps").glob("*.dylib"))}
        executables = {str(path.relative_to(target)): sha(path) for path in sorted((target / profile_dir / "build").glob("*/*")) if path.is_file() and (path.name == "build-script-build" or path.name.endswith(".nano-real"))}
        compiled_executables = compiled_scripts(target, profile_dir)
        native = {str(path.relative_to(target)): sha(path) for path in sorted(target.rglob('*'))
                  if path.is_file() and path.suffix in ('.o', '.a')} if (args.native_clang or args.portable_cc or args.native_artifacts) else {}
        final_path = target / profile_dir / (args.bin + ('.exe' if os.name == 'nt' else '')) if args.bin else None
        final_artifacts = {str(final_path.relative_to(target)): sha(final_path)} if final_path and final_path.is_file() else {}
        row = {"native_objects_and_archives": native, "implementation": implementation, "phase": phase, "seconds": seconds,
               "exit_code": proc.returncode, "events": dict(after - before), "rlibs": len(artifacts), "artifacts": artifacts,
               "peak_sampled_process_tree_rss_bytes": peak, "macro_dylibs": macros, "build_script_executables": executables, "compiled_build_script_executables": compiled_executables}
        row['build_log'] = dict(path=log_path.name, bytes=log_path.stat().st_size, sha256=sha(log_path))
        timing = target / 'cargo-timings/cargo-timing.html'
        if args.cargo_timings and timing.is_file():
            saved = state / f"{number}-{implementation}-{phase}.timing.html"
            shutil.copyfile(timing, saved)
            row['cargo_timing'] = dict(path=saved.name, bytes=saved.stat().st_size, sha256=sha(saved))
        row['started_monotonic'] = start
        row['ended_monotonic'] = start + seconds
        row['artifact_modes'] = {name: oct((target / name).stat().st_mode & 0o777)
                                 for name in {**artifacts, **macros, **executables, **native, **final_artifacts}}
        if args.bin:
            row['final_executable_artifacts'] = final_artifacts
            row['final_executable_modes'] = {str(final_path.relative_to(target)): oct(final_path.stat().st_mode & 0o777)} if final_artifacts else {}
            if proc.returncode == 0 and args.probe_help:
                row.update(probe_help(final_path, env))
        # Preserve the completed compiler result even if capture verification or
        # reference copying fails. Later validation enriches this same row.
        result['builds'].append(row)
        save()
        if capture:
            capture.finish(row, target, origin_ns, event_path, event_offset, log_path)
        if implementation not in references:
            if args.retain_artifacts:
                manifest = retain(target, state / 'reference-artifacts' / implementation,
                                  {**artifacts, **macros, **executables, **native, **final_artifacts})
                row['reference_manifest'] = str(manifest.relative_to(state))
            references[implementation] = artifacts
            macro_references[implementation] = macros
            executable_references[implementation] = executables
            compiled_script_references[implementation] = compiled_executables
            native_references[implementation] = native
            final_references[implementation] = final_artifacts
            mode_references[implementation] = row.get('final_executable_modes', {})
            all_mode_references[implementation] = row['artifact_modes']
        else:
            row['matches_own_cold_artifact_modes'] = all_mode_references[implementation] == row['artifact_modes']
            row["matches_own_cold_native_artifacts"] = native_references[implementation] == native
            row["matches_own_cold_artifacts"] = references[implementation] == artifacts
            row["matches_own_cold_macro_dylibs"] = macro_references[implementation] == macros
            row["matches_own_cold_build_script_executables"] = executable_references[implementation] == executables
            if args.bin:
                row['matches_own_cold_final_executable'] = final_references[implementation] == final_artifacts
                row['matches_own_cold_final_executable_modes'] = mode_references[implementation] == row['final_executable_modes']
        if implementation == "nanocompile" and not (args.native_clang or args.portable_cc or args.native_artifacts):
            row["matches_direct_artifacts"] = artifacts == references.get("direct")
            row["matches_direct_macro_dylibs"] = macros == macro_references.get("direct")
            row["matches_direct_build_script_executables"] = compiled_executables == compiled_script_references.get("direct")
        save()
        print(json.dumps({k: v for k, v in row.items() if k not in ("artifacts", "macro_dylibs", "build_script_executables", "native_objects_and_archives", "compiled_build_script_executables", "trace")}), flush=True)
        if proc.returncode or not artifacts or (args.bin and not final_artifacts):
            raise RuntimeError(f"Build failed or produced no libraries; see {log_path}")
        if row.get('cli_help_valid') is False:
            raise RuntimeError(f'Final executable failed explicit --help probe; saved result in {output}')
        if implementation == "kache" and args.record_kache_mismatches:
            failed = [check for check, value in row.items() if check.startswith("matches_") and value is False]
            if failed:
                row["recorded_mismatches"] = failed
                save()
        elif any(row.get(check) is False for check in ("matches_own_cold_artifact_modes", "matches_own_cold_final_executable_modes", "matches_own_cold_final_executable", "matches_own_cold_native_artifacts", "matches_own_cold_artifacts", "matches_direct_artifacts", "matches_own_cold_macro_dylibs", "matches_direct_macro_dylibs", "matches_own_cold_build_script_executables", "matches_direct_build_script_executables")):
            raise RuntimeError(f"Artifact validation failed; see {log_path}")
        if phase == "warm" and implementation == "nanocompile" and args.native_clang:
            if (row['events'].get('clang_native_hit', 0) < 20 and not row['events'].get('build_script_hit',0)) or row['events'].get('hit', 0) < 165:
                raise RuntimeError('Nano native or Rust cache did not serve expected warm hits')
        if phase == "warm" and implementation == "nanocompile" and args.build_script_contract and not row["events"].get("build_script_hit", 0):
            raise RuntimeError("Selected execution cache did not serve a warm script hit")
        if phase == "warm" and implementation == "kache" and not row["events"].get("local_hit", 0):
            raise RuntimeError("kache recorded no local hits; comparison is invalid")

    if args.native_clang:
        result['method'] += '; Nano explicitly uses CC=nanocompile clang and native remarks; direct and kache retain their usual native compiler selection. Inline scanner changes debug representation, so every mode must match its own cold Rust, macro, executable and native artifact bytes. RSS includes benchmark parent, private kache daemon and Cargo descendants.'
    if args.portable_cc:
        result["method"] += "; Nano explicitly uses portable CC/CXX; count cc_hit/cc_miss/cc_bypass separately; compare native outputs to own cold bytes; initial coverage has unsupported jobs"
    daemon = None
    daemon_log = None
    try:
        with (state / "fetch.log").open("w") as log:
            subprocess.run(["cargo", "fetch", "--locked"], cwd=project, env=env, stdout=log, stderr=log, check=True)
        build("direct", "prime")
        for iteration in range(args.cold_runs):
            if daemon is not None:
                daemon.send_signal(signal.SIGINT)
                try:
                    daemon.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    daemon.kill()
                    daemon.wait()
                daemon_log.close()
                daemon = None
            socket = state / "daemon.sock"
            # No daemon keeps fingerprints or SQLite handles across cold pairs.
            if socket.exists():
                socket.unlink()
            shutil.rmtree(cache, ignore_errors=True)
            shutil.rmtree(kcache, ignore_errors=True)
            if not args.standalone and not args.nano_only:
                daemon_log = (state / f"daemon-{iteration}.log").open("w")
                daemon = subprocess.Popen([kache, "daemon", "run"], cwd=project, env=env, stdout=daemon_log, stderr=daemon_log)
                deadline = time.monotonic() + 15
                while not socket.exists():
                    if daemon.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Isolated kache daemon failed to start")
                    time.sleep(0.1)
                status = subprocess.run([kache, "--json", "daemon", "status"], cwd=project, env=env, capture_output=True, text=True, check=True)
                result.setdefault("daemon_statuses", []).append(status.stdout)
            cold_order = ("nanocompile",) if args.nano_only else (("nanocompile", "kache") if iteration % 2 == 0 else ("kache", "nanocompile"))
            for implementation in cold_order:
                build(implementation, "cold")
                row = result["builds"][-1]
                if implementation == "nanocompile":
                    if row["events"].get("hit", 0) or not row["events"].get("miss", 0):
                        raise RuntimeError("Nano cold cache was not empty")
                    if args.native_clang and (row["events"].get("clang_native_hit", 0) or not row["events"].get("clang_native_miss", 0)):
                        raise RuntimeError("Nano native cold cache was not empty")
                elif row["events"].get("local_hit", 0) or row["events"].get("remote_hit", 0):
                    raise RuntimeError("kache cold cache was not empty")
        schedule = ["nanocompile"] if args.nano_only else ["direct", "nanocompile", "kache"]
        if args.warm_caches_only:
            schedule = ["nanocompile", "kache"]
        if not args.cold_only:
            for iteration in range(args.runs):
                offset = iteration % len(schedule)
                for implementation in schedule[offset:] + schedule[:offset]:
                    build(implementation, "warm")
            for implementation in schedule:
                samples = [r["seconds"] for r in result["builds"] if r["implementation"] == implementation and r["phase"] == "warm"]
                result.setdefault("summary", {})[implementation] = {"samples_seconds": samples, "median_seconds": statistics.median(samples)}
        result["cold_summary"] = {}
        for implementation in (("nanocompile",) if args.nano_only else ("nanocompile", "kache")):
            samples = [r["seconds"] for r in result["builds"] if r["implementation"] == implementation and r["phase"] == "cold"]
            result["cold_summary"][implementation] = {"samples_seconds": samples, "median_seconds": statistics.median(samples)}
        if not args.nano_only:
            deltas = [k - n for k, n in zip(result["cold_summary"]["kache"]["samples_seconds"], result["cold_summary"]["nanocompile"]["samples_seconds"])]
            result["cold_paired_seconds_saved"] = deltas
            result["cold_paired_summary"] = {"nanocompile_wins": sum(d > 0 for d in deltas), "mean_seconds_saved": statistics.mean(deltas), "median_seconds_saved": statistics.median(deltas), "stdev_seconds_saved": statistics.stdev(deltas) if len(deltas)>1 else None, "standard_error_seconds_saved": statistics.stdev(deltas)/len(deltas)**.5 if len(deltas)>1 else None}
            result["method"] += "; cold pairs alternate wrapper order, clear both compiler caches, and restart the private kache daemon outside timing; Cargo target removed every build; OS filesystem cache is not flushed"
            stats = subprocess.run([kache, "--json", "stats"], cwd=project, env=env, capture_output=True, text=True, check=True)
            result["kache_stats"] = json.loads(stats.stdout)
        result['tracked_sources_unchanged'] = all((project / name).is_file() and sha(project / name) == digest
                                                  for name, digest in result['tracked_rust_and_manifest_hashes'].items())
        save()
        if not result['tracked_sources_unchanged']:
            raise RuntimeError('Tracked Rust sources changed during the comparison; results are not comparable')
        result['completed'] = True
        save()
        print(json.dumps(result.get("summary", result["cold_summary"]), indent=2), flush=True)
    except Exception as error:
        result['completed'] = False
        result['failure'] = dict(type=type(error).__name__, message=str(error))
        save_failure(output, result)
        raise
    finally:
        if daemon is not None:
            if daemon.poll() is None:
                daemon.send_signal(signal.SIGINT)
                try:
                    daemon.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    daemon.kill()
                    daemon.wait()
        elif args.standalone and not args.nano_only:
            # stats may opportunistically start a daemon even in standalone mode.
            subprocess.run([kache, "daemon", "stop"], cwd=project, env=env, capture_output=True)
        if daemon_log is not None:
            daemon_log.close()


if __name__ == "__main__":
    main()
