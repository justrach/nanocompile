"""Private whole-build capture and shareable diagnostic analysis (not speed benchmarks)."""
import argparse
import collections
import html
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def verify_capture(directory):
    """Check a local capture against its manifest; this is integrity, not authentication."""
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest.get('schema') != 1:
        raise ValueError('Unsupported capture manifest')
    actual = {str(p.relative_to(directory)) for p in directory.rglob('*')
              if p.is_file() and p != directory / 'manifest.json'}
    if actual != set(manifest['files']):
        raise ValueError('Capture file set differs from manifest')
    for name, expected in manifest['files'].items():
        path = directory / name
        if not path.resolve().is_relative_to(directory.resolve()) or path.is_symlink():
            raise ValueError('Capture path escapes directory or is linked')
        raw = path.read_bytes()
        if len(raw) != expected['bytes'] or hashlib.sha256(raw).hexdigest() != expected['sha256']:
            raise ValueError('Capture content differs from manifest: ' + name)
    return dict(verified_files=len(actual), compiler_records=manifest['compiler_records'],
                cargo_units=manifest['cargo_units'])

class Capture:
    def __init__(self, state, binaries):
        self.root = state / 'capture'
        self.root.mkdir(mode=0o700)
        self.wrappers = {}
        for name, binary in binaries.items():
            folder = self.root / name
            folder.mkdir(mode=0o700)
            wrapper = folder / name
            subprocess.run(['cc', '-O2', str(ROOT / 'tools/build_capture.c'),
                            '-DREAL_BINARY=' + json.dumps(binary),
                            '-DCAPTURE_ROOT=' + json.dumps(str(folder)), '-o', str(wrapper)], check=True)
            self.wrappers[name] = str(wrapper)

    def begin(self, number, implementation):
        self.directory = self.root / str(number)
        self.directory.mkdir(mode=0o700)
        if implementation in self.wrappers:
            (self.root / implementation / 'current').write_text(str(self.directory) + '\n')

    def finish(self, row, target, origin_ns, event_path, event_offset, build_log=None):
        if build_log is not None:
            shutil.copyfile(build_log, self.directory / 'cargo.log')
        units = []
        timing = target / 'cargo-timings/cargo-timing.html'
        if timing.exists():
            shutil.copyfile(timing, self.directory / 'cargo-timing.html')
            source = timing.read_text()
            units = json.JSONDecoder().raw_decode(source.split('const UNIT_DATA = ', 1)[1])[0]
        build_outputs = self.directory / 'build-script-outputs'
        for path in (target / 'release/build').glob('*/*'):
            if path.is_file() and path.name in ('output', 'stderr', 'root-output'):
                dest = build_outputs / path.parent.name / path.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)
        events = b''
        if event_path.exists():
            with event_path.open('rb') as f:
                f.seek(event_offset)
                events = f.read()
        (self.directory / 'cache-events').write_bytes(events)
        calls = []
        for path in sorted(self.directory.glob('*.json')):
            raw = json.loads(path.read_text())
            args = raw['args']
            crate = args[args.index('--crate-name') + 1] if '--crate-name' in args else None
            stderr = path.with_suffix('.stderr').read_text(errors='replace')
            source = next((Path(a).name for a in args if a.endswith(('.c', '.cc', '.cpp', '.S', '.s'))), None)
            calls.append(dict(kind='rust' if crate else 'native' if source else 'probe',
                              name=crate or source or 'compiler probe',
                              start_seconds=(raw['start_ns'] - origin_ns) / 1e9,
                              seconds=(raw['end_ns'] - raw['start_ns']) / 1e9,
                              user_seconds=raw['user_us'] / 1e6, system_seconds=raw['system_us'] / 1e6,
                              exit_code=raw['exit_code'],
                              nano_decisions=[line.strip() for line in stderr.splitlines()
                                              if line.strip().startswith('nanocompile:')],
                              record=path.name))
        service = []
        if row['implementation'] == 'kache':
            allowed = ('crate_name', 'package', 'result', 'elapsed_ms', 'compile_time_ms', 'key_ms', 'lookup_ms',
                       'restore_ms', 'store_ms', 'startup_ms', 'dep_info_ms', 'permit_wait_ms', 'flight_wait_ms')
            for line in events.splitlines():
                raw = json.loads(line)
                service.append({k: v for k, v in raw.items() if k in allowed or isinstance(v, (int, float))})
        row['trace'] = dict(capture_directory=str(self.directory), requests=calls, cargo_units=units,
                            kache_service_events=service, diagnostic=True,
                            limitations='Captured request CPU excludes daemon work. Cargo intervals are rounded and approximately aligned to process launch. Overlapping durations cannot be added to infer build savings. Cache service events are not joined to requests.')
        # Local audit manifest: retain every byte, including empty streams, and
        # make missing/truncated records discoverable without publishing logs.
        files = {str(p.relative_to(self.directory)): dict(bytes=p.stat().st_size,
                 sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                 for p in sorted(self.directory.rglob('*')) if p.is_file()}
        manifest = dict(schema=1, files=files, compiler_records=len(calls),
                        cargo_units=len(units), build_log_captured=build_log is not None,
                        direct_compiler_records_captured=row['implementation'] != 'direct',
                        scope='Cargo console, timings, compiler frontends and build-script streams; no syscall or arbitrary subprocess tracing')
        (self.directory / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        row['trace']['capture_coverage'] = {k: v for k, v in manifest.items() if k != 'files'}
        if row['implementation'] != 'direct' and not calls:
            raise RuntimeError('No wrapper calls captured')


def analyze(report, output):
    data = json.loads(report.read_text())
    output.mkdir(parents=True, exist_ok=True)
    traces, grouped = [], collections.defaultdict(list)
    service_summaries = []
    build_script_runs = []
    for index, build in enumerate(data['builds']):
        traces.append(dict(name='process_name', ph='M', pid=index, tid=0, args=dict(name=f"{index}: {build['implementation']} {build['phase']}")))
        trace = build.get('trace', {})
        service_events = trace.get('kache_service_events', [])
        if service_events:
            build_script_runs.extend(dict(build=index, phase=build['phase'], **event) for event in service_events if event.get('crate_name') == 'build_script_run')
            metrics = sorted({key for event in service_events for key, value in event.items() if key.endswith('_ms') and isinstance(value, (int, float))})
            service_summaries.append(dict(build=index, phase=build['phase'], results=dict(collections.Counter(event.get('result', 'unknown') for event in service_events)), stages={key: dict(samples=len(values), median_ms=statistics.median(values), sum_ms=sum(values)) for key in metrics if (values := [e[key] for e in service_events if isinstance(e.get(key), (int, float)) and (key != 'compile_time_ms' or e.get('result') in ('miss', 'passthrough'))])}))
        for kind, rows in [('request', trace.get('requests', [])), ('cargo', trace.get('cargo_units', []))]:
            for row in rows:
                name = row['name']
                if kind == 'cargo':
                    name += ' ' + row.get('version', '') + ' ' + str(row.get('target', '')) + ' features=' + ','.join(row.get('features', []))
                mode = row.get('kind', row.get('mode', 'unknown'))
                duration = row.get('seconds', row.get('duration', 0))
                start = row.get('start_seconds', row.get('start', 0))
                grouped[(build['phase'], kind, mode, name, build['implementation'])].append(duration)
                traces.append(dict(name=name, cat=kind + ':' + mode, ph='X', ts=max(0, start)*1e6,
                                   dur=duration*1e6, pid=index, tid=kind, args=dict(implementation=build['implementation'], phase=build['phase'])))
    comparison = []
    identities = sorted({key[:4] for key in grouped})
    for key in identities:
        row = dict(zip(('phase', 'kind', 'mode', 'name'), key))
        for implementation in ('direct', 'nanocompile', 'kache'):
            values = grouped.get((*key, implementation), [])
            row[implementation] = dict(samples=len(values), median_seconds=statistics.median(values),
                                       min_seconds=min(values), max_seconds=max(values)) if values else None
        n, k = row['nanocompile'], row['kache']
        row['nano_minus_kache_seconds'] = n['median_seconds'] - k['median_seconds'] if n and k else None
        comparison.append(row)
    comparison.sort(key=lambda r: r['nano_minus_kache_seconds'] or 0, reverse=True)
    experiments = []
    for row in comparison:
        if len(experiments) == 12:
            break
        gap = row['nano_minus_kache_seconds']
        if gap is None or gap <= 0:
            continue
        experiments.append(dict(priority=len(experiments)+1,
            observation={k: row[k] for k in ('phase', 'kind', 'mode', 'name', 'nanocompile', 'kache', 'nano_minus_kache_seconds')},
            hypothesis='Execution reuse may remove repeated work' if row['mode'] == 'run-custom-build' else 'Identity, coordination or restore work may explain the interval gap',
            next_measurement='Inspect matching private records and instrument Nano stages; run one controlled ablation before changing behavior',
            acceptance=['repeated alternating untraced A/B against frozen production and kache',
                        'real input edits and reverts invalidate correctly',
                        'loader, toolchain and environment changes invalidate correctly',
                        'source hashes stable and own-cold artifact hashes equal',
                        'report cold and warm regressions and rejected variations'],
            claim='Diagnostic hypothesis; interval gap is not predicted wall-time savings'))
    provenance = {key: data[key] for key in ('commit', 'nanocompile_sha256', 'kache_sha256',
                  'kache_version', 'rustc', 'script_sha256', 'jobs', 'timestamp',
                  'diagnostic_trace', 'native_clang', 'nanocompile_proc_macros',
                  'nanocompile_proc_macro_producers', 'nanocompile_executable_producers',
                  'build_script_contract_sha256', 'kache_build_script_cache') if key in data}
    provenance['report_sha256'] = hashlib.sha256(report.read_bytes()).hexdigest()
    (output / 'experiments.json').write_text(json.dumps(dict(schema=1, provenance=provenance,
        instruction='Reproduce this configuration before changing one cause; freeze the baseline binary and keep diagnostic and untraced benchmark results separate',
        candidate_limit=12, complete_comparisons='analysis.json', experiments=experiments), indent=2)+'\n')
    (output / 'trace.json').write_text(json.dumps({'traceEvents': traces}))
    analysis = dict(diagnostic=True, comparisons=comparison, kache_service_summaries=service_summaries, kache_build_script_runs=build_script_runs,
                    build_coverage=[dict(implementation=b["implementation"], phase=b["phase"], events=b.get("events", {}), capture_coverage=b.get('trace', {}).get('capture_coverage'), request_kinds=dict(collections.Counter(r["kind"] for r in b.get("trace", {}).get("requests", []))), own_artifact_checks={k: v for k, v in b.items() if k.startswith("matches_own_cold")}) for b in data["builds"]],
                    limitations='compile_time_ms on cache hits can describe the stored original compilation; stage summaries exclude hit/dup compile_time_ms. Per-unit medians are scheduling-sensitive, unpaired diagnostic observations. Request durations overlap. Missing counterparts are unknown, not zero. No optimization or overall speed win is established by this capture.')
    (output / 'analysis.json').write_text(json.dumps(analysis, indent=2) + '\n')
    brief = ['# Instructions for the next variation', '', analysis['limitations'], '',
             'Use the installed production binary as baseline. Change one measured cause at a time. Preserve full content hashing, loader selection, native include discovery and artifact validation. Never optimize by skipping an unverified input.', '',
             'Investigate these observed Nano-minus-kache interval gaps; a long overlapping interval does not establish critical-path savings:', '']
    for row in [r for r in comparison if r['nano_minus_kache_seconds'] and r['nano_minus_kache_seconds'] > 0][:12]:
        brief.append(f"- {row['phase']} / {row['kind']} / {row['mode']} / {row['name']}: {row['nano_minus_kache_seconds']:.6f}s median interval gap; samples Nano={row['nanocompile']['samples']}, kache={row['kache']['samples']}.")
    brief += ['', 'Kache service stage measurements (sums overlap and do not predict wall savings):', '', *[json.dumps(row, sort_keys=True) for row in service_summaries], '', 'Inspect the private compiler records and build-script logs for each candidate. Use kache service breakdowns to distinguish key, lookup, compile and restore costs; do not infer Nano stage costs from kache events. Add Nano phase instrumentation if that distinction is missing.', '',
              'Require repeated alternating untraced cold and warm pairs, actual source edits and reverts, zero cold hits, expected warm coverage, unchanged source hashes, and matching own-cold artifact bytes. Report rejected variations and uncertainty. Promote only repeatable improvements without correctness regressions.']
    nano_native = [sum(r['kind'] == 'native' for r in b.get('trace', {}).get('requests', [])) for b in data['builds'] if b['phase'] == 'warm' and b['implementation'] == 'nanocompile']
    kache_native = [sum(r['kind'] == 'native' for r in b.get('trace', {}).get('requests', [])) for b in data['builds'] if b['phase'] == 'warm' and b['implementation'] == 'kache']
    if nano_native and kache_native and min(nano_native) > 0 and max(kache_native) == 0:
        brief += ['', '## Build-script execution candidate', '', f'Warm Nano issues {nano_native} native requests per round; kache issues {kache_native}. Inspect per-package build_script_run events, build-script intervals and own-cold native artifact checks. Investigate build-script execution reuse after verifying the exact mechanism and input contract. Native bundle audit fields alone do not prove execution reuse. Require an ablation before estimating whole-build impact. Require C/header/assembly include edits, toolchain/loader changes, environment changes and output tampering to invalidate correctly. Missing native requests alone do not prove the mechanism or a speed win.']
    (output / 'next-experiments.md').write_text('\n'.join(brief)+'\n')
    # Escape all captured names. No raw logs or environment are embedded in the report.
    body = ''.join('<tr>' + ''.join('<td>'+html.escape(str(v))+'</td>' for v in
                   (r['phase'], r['kind'], r['mode'], r['name'],
                    r['nanocompile'], r['kache'], r['nano_minus_kache_seconds'])) + '</tr>' for r in comparison)
    (output / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Build trace comparison</title><style>body{font:15px system-ui;margin:32px}td,th{padding:8px;text-align:left;border-bottom:1px solid #ddd}input{padding:10px;width:400px}</style><h1>Whole-build diagnostic comparison</h1><p>'+html.escape(analysis['limitations'])+'</p><p>Open trace.json in Perfetto for overlapping request and Cargo timelines. Full logs stay in the private capture directory.</p><input placeholder="Filter crate, mode or phase" oninput="for(const row of document.querySelectorAll(\'tbody tr\'))row.hidden=!row.textContent.toLowerCase().includes(this.value.toLowerCase())"><table><thead><tr>'+''.join('<th>'+v+'</th>' for v in ('Phase','Layer','Mode','Name','Nano','kache','Gap (s)'))+'</tr></thead><tbody>'+body+'</tbody></table>')
    return analysis


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    capture = sub.add_parser('capture', help='forward comparison arguments after --')
    capture.add_argument('arguments', nargs=argparse.REMAINDER)
    report = sub.add_parser('analyze')
    report.add_argument('report', type=Path)
    report.add_argument('--output', required=True, type=Path)
    verify = sub.add_parser('verify-capture', help='check private captured file sets, sizes and hashes')
    verify.add_argument('directory', type=Path)
    args = parser.parse_args()
    if args.action == 'capture':
        forwarded = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
        subprocess.run([sys.executable, str(ROOT / 'tests/project_comparison.py'), *forwarded, '--trace-builds'], check=True)
    elif args.action == 'analyze':
        analyze(args.report, args.output)
    else:
        print(json.dumps(verify_capture(args.directory)))

if __name__ == '__main__':
    main()
