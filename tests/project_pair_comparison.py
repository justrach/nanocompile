"""Compare nanocompile binaries or one runtime switch over clean Cargo builds."""
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

from project_comparison import tree_rss
from benchmark_storage import require_space, save_report, save_failure
from bindgen_controls import load as bindgen_controls
from executable_probe import probe_help


# Numeric experimental controls only: never accept cache paths or credentials
# here. Add controls explicitly so a comparison cannot override runner isolation.
RUNTIME_CONTROLS = {
    'NANOCOMPILE_PRODUCER_GRAPH_WORKERS': {'0', '4'},
    'NANOCOMPILE_PRODUCER_SHARED_DIGESTS': {'0', '1'},
    'NANOCOMPILE_HASH_MISMATCH_STOP': {'0', '1'},
    'NANOCOMPILE_BLOB_HASH_MODE': {'0', '1', '2'},
    'NANOCOMPILE_DIGEST_MEMO': {'0', '1'},
    'NANOCOMPILE_SELECTION_MEMO': {'0', '1'},
}


def runtime_comparison(parser, toggle, binary_hashes):
    if toggle is None:
        return None
    name, baseline, candidate = toggle
    allowed = RUNTIME_CONTROLS.get(name)
    if allowed is None or baseline not in allowed or candidate not in allowed:
        parser.error('--runtime-toggle requires a supported control and values: ' +
                     ', '.join(f'{key}={"/".join(sorted(values))}' for key, values in RUNTIME_CONTROLS.items()))
    if baseline == candidate:
        parser.error('--runtime-toggle values must differ')
    if binary_hashes['baseline'] != binary_hashes['candidate']:
        parser.error('--runtime-toggle requires byte-identical baseline and candidate binaries')
    return dict(name=name, values=dict(baseline=baseline, candidate=candidate))


def build_environment(common, name, phase, control, prime_marker):
    result = dict(common)
    if control:
        result[control['name']] = control['values'][name]
    if prime_marker and name == 'candidate' and phase == 'prime':
        result['NANOCOMPILE_TRACE'] = '1'
    return result


def validate_prime_trace(parser, marker, control, cold):
    if marker is None:
        return
    if not control or not marker.strip():
        parser.error('--candidate-prime-marker requires --runtime-toggle and a nonempty marker')
    if not cold:
        parser.error('--candidate-prime-marker requires --cold: tracing changes the compilation cache key')


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
    p.add_argument('--package', default='harness-adapters')
    p.add_argument('--own-artifact-references', action='store_true', help='validate each binary against its own first build instead of requiring cross-binary byte equality')
    p.add_argument('--cold', action='store_true', help='clear compiler cache before every build')
    p.add_argument('--compiler-stream', action='store_true', help='same streaming flag environment for both binaries')
    p.add_argument('--build-script-contract', type=Path)
    p.add_argument('--pipelined-companions', action='store_true', help='experimental guarded metadata-first archive membership')
    p.add_argument('--no-compiler-stream', action='store_true', help='disable default Rust stream forwarding')
    p.add_argument('--no-pipelined-companions', action='store_true', help='disable default guarded companion membership')
    p.add_argument('--bin', help='build and validate this binary instead of the package library')
    p.add_argument('--probe-help', action='store_true')
    p.add_argument('--cargo-timings', action='store_true', help="keep each build's Cargo --timings report for tools/rust_profile.py")
    p.add_argument('--source-date-epoch', type=int)
    p.add_argument('--thin-lto-producers', action='store_true')
    p.add_argument('--rlib-frameworks', action='store_true')
    p.add_argument('--staticlib-companions', action='store_true')
    p.add_argument('--bindgen-tools-file', type=Path)
    p.add_argument('--min-free-gib', type=float, default=8)
    p.add_argument('--minimum-cache-units', type=int, default=165)
    p.add_argument('--runtime-toggle', nargs=3, metavar=('NAME', 'BASELINE', 'CANDIDATE'),
                   help='compare a supported numeric experiment switch in the same binary; recorded for every build')
    p.add_argument('--candidate-prime-marker',
                   help='trace only the excluded candidate prime and require this activation marker in its full log')
    args = p.parse_args()
    if args.probe_help and not args.bin: p.error('--probe-help requires --bin')
    if args.source_date_epoch is not None and args.source_date_epoch < 0: p.error('--source-date-epoch must be nonnegative')
    if not 0 < args.min_free_gib < float('inf'): p.error('--min-free-gib must be positive and finite')
    if (args.compiler_stream and args.no_compiler_stream) or (args.pipelined_companions and args.no_pipelined_companions):
        p.error('choose either enable or disable for each compiler control')
    assert args.runs > 0 and args.jobs > 0 and args.minimum_cache_units > 0
    binaries = {name: getattr(args, name).resolve() for name in ('baseline', 'candidate')}
    binary_hashes = {name: sha(path) for name, path in binaries.items()}
    control = runtime_comparison(p, args.runtime_toggle, binary_hashes)
    validate_prime_trace(p, args.candidate_prime_marker, control, args.cold)
    project, root = args.project.resolve(), args.state.resolve()
    require_space(root, args.min_free_gib)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    wrapper, target = root / 'wrapper', root / 'target'
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
           and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTC_BOOTSTRAP')}
    env.update(RUSTUP_TOOLCHAIN='1.97.1', RUSTC_WRAPPER=str(wrapper),
               CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL='0',
               NANOCOMPILE_DIR=str(root / 'cache'), NANOCOMPILE_PROC_MACROS='reported',
               NANOCOMPILE_PROC_MACRO_PRODUCERS='1', NANOCOMPILE_EXECUTABLE_PRODUCERS='1')
    if args.pipelined_companions:
        env['NANOCOMPILE_PIPELINED_COMPANIONS'] = '1'
    if args.no_compiler_stream:
        env['NANOCOMPILE_STREAM_COMPILER'] = '0'
    if args.no_pipelined_companions:
        env['NANOCOMPILE_PIPELINED_COMPANIONS'] = '0'
    if args.compiler_stream:
        env['NANOCOMPILE_STREAM_COMPILER'] = '1'
    if args.build_script_contract:
        env['NANOCOMPILE_BUILD_SCRIPTS_FILE'] = str(args.build_script_contract.resolve())
    selected_bindgen_tools, bindgen_tools_hash = (None, None)
    if args.bindgen_tools_file:
        selected_bindgen_tools, bindgen_tools_hash = bindgen_controls(args.bindgen_tools_file)
        env.update(selected_bindgen_tools)
    if args.source_date_epoch is not None: env['SOURCE_DATE_EPOCH'] = str(args.source_date_epoch)
    if args.thin_lto_producers: env['NANOCOMPILE_THIN_LTO_PRODUCERS'] = '1'
    if args.rlib_frameworks: env['NANOCOMPILE_RLIB_FRAMEWORKS'] = '1'
    if args.staticlib_companions: env['NANOCOMPILE_RUST_STATICLIB'] = '1'
    command = ['cargo', 'build', '--release', *(['--bin', args.bin] if args.bin else ['--lib']), '--locked', '--offline',
               '-p', args.package, '-j', str(args.jobs), *(['--timings'] if args.cargo_timings else [])]
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=project).decode().split('\0')
    source_hashes = {name: sha(project / name) for name in tracked if name and
                     (name.endswith(('.rs', '.toml')) or Path(name).name == 'Cargo.lock')
                     and (project / name).is_file()}
    evidence = {
        'method': ('rotating clean Cargo builds; binary copied to one stable wrapper path between completed builds; '
                   'fixed target and cache paths; both modes primed; ' +
                   ('same executable identity, varying only the recorded runtime control' if control else
                    'same environment, executable identities recorded by SHA-256') +
                   ('; only the excluded candidate prime enables trace for activation verification' if args.candidate_prime_marker else '')),
        'runtime_control': control,
        'cache_key_scope': 'full environment; different runtime-control values use distinct compilation keys',
        'candidate_prime_marker': args.candidate_prime_marker,
        'project': str(project), 'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=project, text=True).strip(),
        'dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=project)),
        'rustc': subprocess.check_output(['rustc', '-vV'], env=env, cwd=project, text=True),
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'binary_sha256': binary_hashes,
        'script_sha256': sha(Path(__file__)), 'jobs': args.jobs, 'runs_per_binary': args.runs,
        'pipelined_companions': env.get('NANOCOMPILE_PIPELINED_COMPANIONS'), 'cold': args.cold, 'compiler_stream': env.get('NANOCOMPILE_STREAM_COMPILER'),
        'build_script_contract_sha256': sha(args.build_script_contract) if args.build_script_contract else None,
        'command': command, 'tracked_rust_and_manifest_hashes': source_hashes, 'builds': [],
    }
    evidence.update(binary_target=args.bin, cli_help_probe=args.probe_help,
                    source_date_epoch=args.source_date_epoch, thin_lto_producers=args.thin_lto_producers,
                    rlib_frameworks=args.rlib_frameworks, staticlib_companions=args.staticlib_companions,
                    bindgen_tools=selected_bindgen_tools, bindgen_tools_file_sha256=bindgen_tools_hash,
                    minimum_free_space_gib=args.min_free_gib, completed=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        save_report(args.output, evidence)

    reference = None
    own_references = {}
    own_modes = {}
    own_help = {}
    def build(name, phase):
        nonlocal reference
        run_env = build_environment(env, name, phase, control, args.candidate_prime_marker)
        controls = {control['name']: run_env[control['name']]} if control else {}
        traced = run_env.get('NANOCOMPILE_TRACE') == '1'
        shutil.rmtree(target, ignore_errors=True)
        if args.cold:
            shutil.rmtree(root / 'cache', ignore_errors=True)
        require_space(root, args.min_free_gib)
        shutil.copy2(binaries[name], wrapper)
        assert sha(wrapper) == evidence['binary_sha256'][name]
        event_file = root / 'cache/events'
        before = event_file.read_text().splitlines() if event_file.exists() else []
        log_path = root / f'{len(evidence["builds"]):02d}-{name}.log'
        print(f'Building {name} {phase}', flush=True)
        with log_path.open('w') as log:
            child = subprocess.Popen(command, cwd=project, env=run_env, stdout=log,
                                     stderr=log, start_new_session=True)
            started_monotonic = time.monotonic()
            started = time.perf_counter()
            peak = 0
            last_sample = 0
            while child.poll() is None:
                if time.monotonic() - last_sample > .5:
                    peak = max(peak, tree_rss(child.pid))
                    last_sample = time.monotonic()
                if peak > 40 * 1024**3 or time.perf_counter() - started > 3600:
                    os.killpg(child.pid, signal.SIGTERM)
                    child.wait(timeout=15)
                    raise RuntimeError('Project comparison exceeded memory/time limit')
                try:
                    child.wait(timeout=.02)
                except subprocess.TimeoutExpired:
                    pass
            elapsed = time.perf_counter() - started
            ended = time.monotonic()
        log_record = dict(path=log_path.name, bytes=log_path.stat().st_size, sha256=sha(log_path))
        timing_record = None
        if args.cargo_timings and (target / 'cargo-timings/cargo-timing.html').is_file():
            saved = log_path.with_suffix('.timing.html')
            shutil.copyfile(target / 'cargo-timings/cargo-timing.html', saved)
            timing_record = dict(path=saved.name, bytes=saved.stat().st_size, sha256=sha(saved))
        if child.returncode:
            evidence['builds'].append(dict(implementation=name, phase=phase, seconds=elapsed,
                                          exit_code=child.returncode, build_log=log_record,
                                          runtime_controls=controls, trace_enabled=traced))
            evidence['failure'] = dict(type='CompilerFailure', log=log_path.name)
            save()
            raise RuntimeError('Project build failed: ' + str(log_path))
        artifacts = {str(path.relative_to(target)): sha(path) for path in sorted(target.rglob('*'))
                     if path.is_file() and (path.suffix in ('.rlib', '.dylib', '.so', '.o', '.a') or
                                           path.name == 'build-script-build' or path.name.endswith('.nano-real'))}
        final = target / 'release' / args.bin if args.bin else None
        if final is not None:
            assert final.is_file(), 'Missing selected binary'
            artifacts[str(final.relative_to(target))] = sha(final)
        assert artifacts
        modes = {name: oct((target / name).stat().st_mode & 0o777) for name in artifacts}
        own_modes.setdefault(name, modes)
        help_result = probe_help(final, run_env) if args.probe_help else {}
        if args.probe_help: own_help.setdefault(name, help_result.get('cli_help_sha256'))
        if reference is None:
            reference = artifacts
        own_references.setdefault(name, artifacts)
        expected = own_references[name] if args.own_artifact_references else reference
        matches_reference = artifacts == expected
        after = event_file.read_text().splitlines()
        counts = {event: after[len(before):].count(event) for event in set(after[len(before):])}
        if args.cold:
            assert counts.get('miss', 0) >= args.minimum_cache_units and not counts.get('hit', 0) and not counts.get('build_script_hit', 0), counts
        if phase == 'warm':
            assert counts.get('hit', 0) >= args.minimum_cache_units, counts
        row = {'implementation': name, 'phase': phase, 'seconds': elapsed,
               'started_monotonic': started_monotonic, 'ended_monotonic': ended,
               'runtime_controls': controls, 'trace_enabled': traced,
               'exit_code': child.returncode, 'build_log': log_record, 'cargo_timing': timing_record, 'artifact_modes': modes,
               'artifact_modes_match_own_reference': modes == own_modes[name],
               **help_result, 'events': counts, 'peak_sampled_process_tree_rss_bytes': peak,
               'artifacts_match_reference': matches_reference, 'reference_mode': 'own' if args.own_artifact_references else 'shared',
               'artifacts_match_first_prime': artifacts == reference, 'artifact_count': len(artifacts), 'artifact_sha256': artifacts}
        evidence['builds'].append(row)
        if args.candidate_prime_marker:
            marker_present = args.candidate_prime_marker.encode() in log_path.read_bytes()
            row['activation_marker_present'] = marker_present
        save()
        print(json.dumps({k: v for k, v in row.items() if k != 'artifact_sha256'}), flush=True)
        assert matches_reference, 'Artifact mismatch: ' + str(log_path)
        assert modes == own_modes[name], 'Artifact mode mismatch'
        if args.candidate_prime_marker:
            assert marker_present == traced, 'Activation trace did not match the declared prime-only tracing policy'
        if args.probe_help:
            assert help_result['cli_help_valid'] and help_result['cli_help_sha256'] == own_help[name], 'CLI help mismatch'
    try:
        for name in binaries:
            build(name, 'prime')
        for i in range(args.runs):
            for name in (('baseline', 'candidate') if i % 2 == 0 else ('candidate', 'baseline')):
                build(name, 'cold' if args.cold else 'warm')
    except BaseException as error:
        evidence['failure'] = dict(type=type(error).__name__, message=str(error))
        save_failure(args.output, evidence)
        raise
    evidence['artifact_sha256'] = reference
    evidence['own_reference_sha256'] = own_references
    evidence['cross_binary_artifact_differences'] = [name for name in set(own_references['baseline']) | set(own_references['candidate']) if own_references['baseline'].get(name) != own_references['candidate'].get(name)]
    evidence['median_seconds'] = {name: statistics.median(r['seconds'] for r in evidence['builds']
                                                         if r['implementation'] == name and r['phase'] == ('cold' if args.cold else 'warm'))
                                  for name in binaries}
    samples = {name: [r['seconds'] for r in evidence['builds'] if r['implementation'] == name and r['phase'] == ('cold' if args.cold else 'warm')] for name in binaries}
    deltas = [b - c for b, c in zip(samples['baseline'], samples['candidate'])]
    evidence['paired_seconds_saved'] = deltas
    evidence['candidate_pair_wins'] = sum(d > 0 for d in deltas)
    evidence['paired_summary'] = dict(mean_seconds_saved=statistics.mean(deltas), median_seconds_saved=statistics.median(deltas),
                                      standard_error=statistics.stdev(deltas)/len(deltas)**.5 if len(deltas)>1 else None)
    if args.cold:
        evidence['method'] += '; compiler cache cleared before every build, including primes; measured pairs alternate order; filesystem caches unflushed'
    evidence['tracked_sources_unchanged'] = all((project / name).is_file() and sha(project / name) == digest
                                               for name, digest in source_hashes.items())
    assert evidence['tracked_sources_unchanged']
    evidence['completed'] = True
    save()
    print(json.dumps(evidence['median_seconds']), flush=True)


if __name__ == '__main__':
    main()
