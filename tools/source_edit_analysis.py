"""Verified source-edit observations and instructions for subsequent experiments."""
import hashlib
import json
from pathlib import Path


def analyze(report, state, output):
    from build_trace import verify_logs
    data = json.loads(report.read_text())
    integrity = verify_logs(report, state)
    samples = []
    groups = {}
    for index, build in enumerate(data['builds']):
        sample = {key: build[key] for key in (
            'implementation', 'phase', 'scenario', 'seconds', 'exit_code',
            'events', 'build_log') if key in build}
        sample['index'] = index
        sample['checks'] = {key: value for key, value in build.items()
                            if key.startswith('matches_') or key in (
                                'empty_cache_has_no_hits', 'cli_help_valid')}
        samples.append(sample)
        # Fresh correctness references are retained, but never pooled with hits.
        if build.get('verification') or build['phase'] == 'empty-cache-reference':
            continue
        key = (build.get('scenario', 'unknown'), build['phase'])
        group = groups.setdefault(key, {})
        impl = build['implementation']
        if impl in group:
            raise ValueError('Duplicate implementation in a source-edit case')
        group[impl] = sample
    comparisons = []
    for (scenario, phase), group in groups.items():
        nano, kache = group.get('nanocompile'), group.get('kache')
        valid = bool(nano and kache and all(
            row['exit_code'] == 0 and row['checks'].get('cli_help_valid') is True
            for row in (nano, kache)))
        comparisons.append(dict(scenario=scenario, phase=phase,
            timings_seconds={name: row['seconds'] for name, row in group.items()},
            comparable=valid,
            nano_minus_kache_seconds=nano['seconds']-kache['seconds'] if valid else None))
    complete = data.get('completed') is True
    source_checks = {key: data.get(key) for key in (
        'original_tracked_sources_unchanged', 'original_snapshot_inputs_unchanged',
        'snapshot_sources_unchanged_except_declared_edits',
        'snapshot_declared_sources_restored')}
    analysis = dict(schema=1, completed=complete, integrity=integrity,
        source_checks=source_checks, samples=samples, comparisons=comparisons,
        provenance={key: data.get(key) for key in (
            'commit', 'jobs', 'nanocompile_sha256', 'kache_sha256', 'rustc',
            'kache_version', 'source_date_epoch')},
        report_sha256=hashlib.sha256(report.read_bytes()).hexdigest(),
        analyzer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        limitations='One source-edit sequence; single observations, not repeated '
        'medians or a proven speedup. Fresh references are correctness checks. '
        'Build logs establish console integrity, not per-request attribution. '
        'No compiler critical path or cause is inferred from cache counts.')
    lines = ['# Source-edit observations', '', analysis['limitations'], '',
             'Session: '+('complete' if complete else 'INCOMPLETE; provisional observations'), '',
             '| Case | Phase | Nano (s) | kache (s) | Nano − kache (s) |',
             '| --- | --- | ---: | ---: | ---: |']
    for row in comparisons:
        def seconds(name):
            value = row['timings_seconds'].get(name)
            return f'{value:.3f}' if value is not None else 'unavailable'
        gap = row['nano_minus_kache_seconds']
        lines.append(f"| {row['scenario']} | {row['phase']} | {seconds('nanocompile')} | {seconds('kache')} | "+(f'{gap:+.3f}' if gap is not None else 'unavailable')+' |')
    lines += ['', '## Instructions for the next variation', '',
        '1. Preserve this report hash, frozen binaries, source snapshot, toolchain, flags, job count and native contracts. Keep complete logs for both tools and every failure.',
        '2. Reproduce the largest observed Nano loss first in alternating repeated untraced trials. A single gap is a hypothesis; do not claim it is repeatable yet.']
    losses = sorted((r for r in comparisons if r['nano_minus_kache_seconds'] is not None
                     and r['nano_minus_kache_seconds'] > 0),
                    key=lambda r: r['nano_minus_kache_seconds'], reverse=True)
    if losses:
        row = losses[0]
        lines.append(f"   Priority case: {row['scenario']} / {row['phase']}, observed gap {row['nano_minus_kache_seconds']:.3f}s.")
    lines += ['3. Capture matched complete compiler/Cargo timelines separately from speed trials. Attribute elapsed time to actual requests; distinguish compilation, input validation, publication and postcompile storage. Nested or overlapping spans cannot be summed into projected savings.',
        '4. Change one measured cause. Retain full input validation and fallback behavior. Compare the candidate with frozen Nano and kache, then run an independent confirmation.',
        '5. Require fresh/cached artifact bytes and modes, leaf/shared edits, reverts, expected executable behavior, unchanged original sources, corruption/failure and concurrency gates before adopting it.',
        '', 'All observations, failed checks and console digests are retained in analysis.json. Raw consoles remain private in the supplied state directory.']
    output.mkdir(parents=True, exist_ok=True)
    (output / 'analysis.json').write_text(json.dumps(analysis, indent=2)+'\n')
    (output / 'next-experiments.md').write_text('\n'.join(lines)+'\n')
    return analysis
