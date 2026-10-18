#!/usr/bin/env python3
"""Local cache measurements; Python 3.9+, stdlib, no network transport."""
import argparse
import json
import math
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import tempfile
import time

SCHEMA = 1
PLATFORMS = ('linux', 'macos', 'windows', 'other')
TARGETS = ('x86_64', 'aarch64', 'wasm', 'other', 'unknown')
OUTCOMES = ('hit', 'miss', 'failed', 'bypass', 'error')
LOOKUPS = ('hit', 'entry_absent', 'entry_unusable', 'disabled', 'not_attempted')
STORAGE = ('stored', 'not_attempted', 'spec_changed', 'inputs_or_tools_changed',
           'revalidation_failed', 'error')
STAGES = ('input_hash', 'tool_identity', 'lock_wait', 'lookup', 'restore',
          'diagnostic_replay', 'lookup_restore', 'child', 'revalidation', 'storage', 'total')
METRICS = tuple('task_' + s + '_seconds' for s in STAGES) + (
    'native_setup_seconds', 'native_total_seconds', 'maintenance_lock_seconds',
    'artifact_bytes', 'input_bytes_hashed', 'revalidation_input_bytes_hashed')
STATUS = ('ok', 'command_failed', 'report_missing', 'report_invalid')


def number(value, nullable=False, integer=False):
    if value is None and nullable:
        return None
    if type(value) not in (int, float) or (integer and type(value) is not int):
        raise ValueError('invalid numeric metric')
    try:
        valid = math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError('invalid numeric metric')
    return value


def total(values):
    return number(sum(values))


def optional_sum(values):
    return None if any(v is None for v in values) else total(values)


def load(path):
    # Duplicate keys are ambiguous; never accept last-key-wins input.
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON field')
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def write(path, value):
    data = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n'
    if path is None:
        sys.stdout.write(data)
    else:
        # Local output only; do not overwrite an existing file accidentally.
        with open(path, 'x', encoding='utf-8') as stream:
            stream.write(data)


def category(value, allowed):
    if value not in allowed or not isinstance(value, str):
        raise ValueError('invalid coarse category')
    return value


def native_metrics(report):
    if not isinstance(report, dict) or type(report.get('schema')) is not int or report['schema'] != 1:
        raise ValueError('invalid native schema')
    rows = report.get('tasks')
    if not isinstance(rows, list) or not rows:
        raise ValueError('missing native tasks')
    metrics = {}
    counts = {key: 0 for key in OUTCOMES}
    attempted = 0
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('timings'), dict):
            raise ValueError('invalid native task')
        outcome = category(row.get('outcome'), OUTCOMES)
        lookup = category(row.get('lookup'), LOOKUPS)
        category(row.get('storage'), STORAGE)
        counts[outcome] += 1
        attempted += lookup in ('hit', 'entry_absent', 'entry_unusable')
        if (outcome == 'hit') != (lookup == 'hit'):
            raise ValueError('inconsistent native hit')
        if row.get('exit_code') is not None:
            number(row['exit_code'], integer=True)
            if outcome in ('hit', 'miss', 'bypass') and row['exit_code'] != 0:
                raise ValueError('inconsistent native exit')
    for stage in STAGES:
        values = [number(row['timings'].get(stage + '_ns'), nullable=True) for row in rows]
        value = optional_sum(values)
        metrics['task_' + stage + '_seconds'] = None if value is None else value / 1e9
    for source, dest in (('setup_ns', 'native_setup_seconds'), ('total_ns', 'native_total_seconds'),
                         ('maintenance_lock_ns', 'maintenance_lock_seconds')):
        value = number(report.get(source), nullable=True)
        metrics[dest] = None if value is None else value / 1e9
    for source, dest in (('output_bytes', 'artifact_bytes'), ('input_bytes_hashed', 'input_bytes_hashed'),
                         ('revalidation_input_bytes_hashed', 'revalidation_input_bytes_hashed')):
        metrics[dest] = optional_sum([number(row.get(source), nullable=True, integer=True) for row in rows])
    return metrics, counts, attempted


def make_record(report, process_seconds, returncode, setup_seconds=None, transfer_seconds=None,
                target='unknown', host=None):
    wall = number(process_seconds)
    setup = number(setup_seconds, nullable=True)
    transfer = number(transfer_seconds, nullable=True)
    host = host or {'Linux': 'linux', 'Darwin': 'macos', 'Windows': 'windows'}.get(platform.system(), 'other')
    metrics = {key: None for key in METRICS}
    counts = {key: 0 for key in OUTCOMES}
    attempted = 0
    status = 'report_missing' if report is None else 'ok'
    if report is not None:
        try:
            metrics, counts, attempted = native_metrics(report)
            child = metrics['task_child_seconds']
            if child is not None and child > wall:
                raise ValueError('child time exceeds process wall')
        except (ValueError, TypeError, KeyError):
            metrics = {key: None for key in METRICS}
            counts = {key: 0 for key in OUTCOMES}
            attempted = 0
            status = 'report_invalid'
    if returncode != 0:
        status = 'command_failed'
    elif counts['failed'] or counts['error']:
        status = 'report_invalid'
    return {'schema': SCHEMA, 'kind': 'cache_record', 'platform': category(host, PLATFORMS),
            'target': category(target, TARGETS), 'status': status,
            'process_seconds': wall, 'external_setup_seconds': setup,
            'external_transfer_seconds': transfer, 'metrics': metrics,
            'task_counts': counts, 'lookup_attempts': attempted}


def validate_record(record):
    if not isinstance(record, dict) or type(record.get('schema')) is not int or record['schema'] != SCHEMA or record.get('kind') != 'cache_record':
        raise ValueError('invalid record schema')
    # Reconstruct from an allowlist. No passthrough of input metadata, even locally.
    clean = {'schema': SCHEMA, 'kind': 'cache_record',
             'platform': category(record.get('platform'), PLATFORMS),
             'target': category(record.get('target'), TARGETS),
             'status': category(record.get('status'), STATUS)}
    clean['process_seconds'] = number(record.get('process_seconds'))
    for key in ('external_setup_seconds', 'external_transfer_seconds'):
        clean[key] = number(record.get(key), nullable=True)
    metrics = record.get('metrics')
    counts = record.get('task_counts')
    if not isinstance(metrics, dict) or not isinstance(counts, dict):
        raise ValueError('invalid metrics')
    clean['metrics'] = {key: number(metrics.get(key), nullable=True,
                                  integer=key.endswith('bytes') or key.endswith('bytes_hashed')) for key in METRICS}
    clean['task_counts'] = {key: number(counts.get(key), integer=True) for key in OUTCOMES}
    clean['lookup_attempts'] = number(record.get('lookup_attempts'), integer=True)
    n = total(clean['task_counts'].values())
    if not clean['task_counts']['hit'] <= clean['lookup_attempts'] <= n:
        raise ValueError('inconsistent hit counts')
    if clean['status'] == 'ok' and (not n or counts['failed'] or counts['error']):
        raise ValueError('inconsistent successful record')
    child = clean['metrics']['task_child_seconds']
    if child is not None and child > clean['process_seconds']:
        raise ValueError('child time exceeds process wall')
    return clean


def observed(record):
    metrics = dict(record['metrics'])
    metrics['process_seconds'] = record['process_seconds']
    for key in ('external_setup_seconds', 'external_transfer_seconds'):
        metrics[key] = record[key]
    child = metrics['task_child_seconds']
    metrics['process_overhead_seconds'] = None if child is None else metrics['process_seconds'] - child
    metrics['observed_total_seconds'] = total([record['process_seconds']] + [record[k] for k in
        ('external_setup_seconds', 'external_transfer_seconds') if record[k] is not None])
    metrics['complete_total_seconds'] = (metrics['observed_total_seconds'] if all(record[k] is not None for k in
        ('external_setup_seconds', 'external_transfer_seconds')) else None)
    return metrics


def aggregate(records, minimum=1):
    if len(records) < minimum:
        raise ValueError('insufficient samples')
    rows = [observed(r) for r in records]
    metrics = {}
    for key in rows[0]:
        values = [row[key] for row in rows if row[key] is not None]
        # Per-metric thresholds too: null values cannot inflate the cohort.
        metrics[key] = {'observed_samples': len(values), 'total': total(values) if len(values) >= minimum else None,
                        'mean': total(values) / len(values) if len(values) >= minimum else None}
        if len(values) < minimum and minimum > 1:
            metrics[key] = None
    eligible = [r for r in records if r['status'] in ('ok', 'command_failed') and total(r['task_counts'].values()) > 0]
    counts = {key: total(r['task_counts'][key] for r in eligible) for key in OUTCOMES}
    attempts = total(r['lookup_attempts'] for r in eligible)
    return {'samples': len(records), 'successful_samples': sum(r['status'] == 'ok' for r in records),
            'incomplete_external_cost_samples': sum(r['external_setup_seconds'] is None or r['external_transfer_seconds'] is None for r in records),
            'metrics': metrics, 'task_counts': counts if len(eligible) >= minimum else None,
            'lookup_attempts': attempts if len(eligible) >= minimum else None,
            'hit_rate': counts['hit'] / attempts if attempts and len(eligible) >= minimum else None}


def summary(records, baseline=None, attest=False):
    records = [validate_record(r) for r in records]
    result = {'schema': SCHEMA, 'kind': 'local_cache_summary', 'aggregate': aggregate(records),
              'estimated_savings': None, 'measured_speedup': None}
    if baseline is not None:
        baseline = [validate_record(r) for r in baseline]
        if not attest or not baseline or not records:
            raise ValueError('historical baseline requires explicit comparable-workload attestation')
        if any(r['status'] != 'ok' for r in records + baseline):
            raise ValueError('failed samples cannot support savings estimates')
        if len({(r['platform'], r['target']) for r in records + baseline}) != 1:
            raise ValueError('historical estimate requires one comparable platform/target cohort')
        baseline_kind = next((kind for kind in ('bypass', 'miss') if all(
            r['task_counts'][kind] == total(r['task_counts'].values()) for r in baseline)), None)
        if baseline_kind is None:
            raise ValueError('historical baseline must consist entirely of misses or bypasses')
        mean = total(r['process_seconds'] for r in baseline) / len(baseline)
        estimate = mean * len(records) - total(r['process_seconds'] for r in records)
        if not math.isfinite(estimate):
            raise ValueError('nonfinite estimate')
        result['estimated_savings'] = {'provenance': 'caller_selected_comparable_historical_' + baseline_kind,
            'baseline_kind': baseline_kind, 'compiler_cache_condition': 'historical_uncontrolled',
            'baseline_samples': len(baseline), 'evaluated_samples': len(records),
            'scope': 'process_wall_only_external_costs_excluded', 'seconds': estimate,
            'controlled_measurement': False}
    return result


def anonymous_export(records, opt_in=False):
    if not opt_in:
        raise ValueError('anonymous export requires explicit opt-in')
    records = [validate_record(r) for r in records]
    if len(records) < 5:
        raise ValueError('anonymous export requires at least five samples')
    groups = {}
    for record in records:
        groups.setdefault((record['platform'], record['target']), []).append(record)
    # Suppress small groups entirely; never serialize arbitrary category strings.
    return {'schema': SCHEMA, 'kind': 'anonymous_cache_aggregates',
            'aggregate': aggregate(records, minimum=5),
            'breakdowns': [{'platform': host, 'target': target, 'aggregate': aggregate(rows, minimum=5)}
                           for (host, target), rows in sorted(groups.items()) if len(rows) >= 5]}


def run_record(binary, spec, setup_seconds=None, transfer_seconds=None, target='unknown', env=None):
    environment = dict(os.environ if env is None else env)
    with tempfile.TemporaryDirectory(prefix='cache-measure-') as directory:
        destination = Path(directory) / 'report.json'
        environment['NANOCOMPILE_TASK_REPORT'] = str(destination)
        start = time.perf_counter()
        # Child diagnostics are not captured in records or echoed into JSON output.
        try:
            process = subprocess.run([str(binary), 'task', str(spec)], env=environment,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            code = process.returncode
        except OSError:
            code = 127
        wall = time.perf_counter() - start
        try:
            report = load(destination)
        except FileNotFoundError:
            report = None
        except (OSError, ValueError):
            report = {}
        return make_record(report, wall, code, setup_seconds, transfer_seconds, target), code


def snapshot(paths):
    result = []
    for path in paths:
        path = Path(path)
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('snapshot/artifact must be a regular non-symlink file')
        result.append((path.read_bytes(), stat.S_IMODE(info.st_mode)))
    return result


def compare(binary, spec, prepare, artifacts, sources, pairs, compiler_condition, attest=False, target='unknown'):
    if not attest or compiler_condition not in ('fresh', 'warm'):
        raise ValueError('comparison requires comparable-workload and compiler-cache assertions')
    if not prepare or not isinstance(prepare, list) or any(not isinstance(x, str) or not x for x in prepare):
        raise ValueError('prepare must be a nonempty JSON argv array')
    if type(pairs) is not int or pairs < 1 or not artifacts or not sources:
        raise ValueError('comparison requires pairs, artifacts and source snapshots')
    # Explicit file lists are caller-attested complete, not automatic hermeticity.
    source_paths = [spec] + list(sources)
    original = snapshot(source_paths)
    enabled, bypass = [], []
    preparation = {'enabled': [], 'bypass': []}
    env = dict(os.environ)
    env.pop('NANOCOMPILE_DISABLE', None)
    for index in range(pairs):
        outputs = {}
        for mode in (('enabled', 'bypass') if index % 2 == 0 else ('bypass', 'enabled')):
            if snapshot(source_paths) != original:
                raise ValueError('source/spec snapshot changed')
            preparation_start = time.perf_counter()
            prepared = subprocess.run(prepare, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            preparation[mode].append(time.perf_counter() - preparation_start)
            if prepared.returncode != 0:
                raise ValueError('prepare failed; no speedup produced')
            if snapshot(source_paths) != original:
                raise ValueError('prepare changed source/spec snapshot')
            run_env = dict(env)
            if mode == 'bypass':
                run_env['NANOCOMPILE_DISABLE'] = '1'
            record, code = run_record(binary, spec, target=target, env=run_env)
            if code != 0 or record['status'] != 'ok':
                raise ValueError('comparison run failed or report unavailable; no speedup produced')
            counts = record['task_counts']
            if mode == 'bypass' and counts['bypass'] != total(counts.values()):
                raise ValueError('bypass not confirmed by report')
            if mode == 'enabled' and counts['bypass']:
                raise ValueError('enabled run unexpectedly bypassed')
            if snapshot(source_paths) != original:
                raise ValueError('run changed source/spec snapshot')
            outputs[mode] = snapshot(artifacts)
            (enabled if mode == 'enabled' else bypass).append(record)
        if outputs['enabled'] != outputs['bypass']:
            raise ValueError('artifact bytes or permissions differ; no speedup produced')
    e = total(r['process_seconds'] for r in enabled)
    b = total(r['process_seconds'] for r in bypass)
    if e <= 0 or b <= 0:
        raise ValueError('zero duration cannot support speedup')
    return {'schema': SCHEMA, 'kind': 'local_controlled_comparison',
            'enabled': aggregate(enabled), 'bypass': aggregate(bypass),
            'preparation': {'enabled_seconds': total(preparation['enabled']),
                            'bypass_seconds': total(preparation['bypass']),
                            'samples_per_mode': pairs, 'included_in_process_speedup': False},
            'estimated_savings': None,
            'measured_speedup': {'provenance': 'alternating_paired_runs_with_identical_prepare',
                'pairs': pairs, 'compiler_cache_condition': compiler_condition,
                'conditions': 'caller_attested_complete_sources_artifacts_and_reset',
                'artifact_bytes_and_permissions_equal': True,
                'scope': 'process_wall_only_external_setup_transfer_and_prepare_excluded',
                'saved_seconds': b - e, 'ratio_bypass_over_enabled': b / e}}


class PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes invalid values, paths and unknown arguments.
        self.exit(2, 'cache_savings: invalid command arguments; use --help\n')


def main(argv=None):
    parser = PrivateArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    record = sub.add_parser('record', help='execute one declared-task build and write a local record')
    record.add_argument('--binary', required=True)
    record.add_argument('--spec', required=True)
    setup = record.add_mutually_exclusive_group()
    setup.add_argument('--setup-seconds', type=float)
    setup.add_argument('--setup-report', help='read ONLY setup_seconds from a local setup report')
    record.add_argument('--transfer-seconds', type=float)
    record.add_argument('--target', choices=TARGETS, default='unknown')
    local = sub.add_parser('summary', help='aggregate explicitly selected local record files')
    local.add_argument('records', nargs='+')
    local.add_argument('--baseline', nargs='+')
    local.add_argument('--attest-comparable', action='store_true')
    export = sub.add_parser('export', help='write anonymous aggregates locally; never send them')
    export.add_argument('records', nargs='+')
    export.add_argument('--opt-in-anonymous-export', action='store_true', required=True)
    paired = sub.add_parser('compare', help='run controlled enabled/bypass pairs')
    paired.add_argument('--binary', required=True)
    paired.add_argument('--spec', required=True)
    paired.add_argument('--prepare-json', required=True, help='same argv array run before every sample')
    paired.add_argument('--artifact', action='append', required=True)
    paired.add_argument('--snapshot', action='append', required=True)
    paired.add_argument('--pairs', type=int, default=5)
    paired.add_argument('--compiler-cache-condition', choices=('fresh', 'warm'), required=True)
    paired.add_argument('--attest-comparable', action='store_true', required=True)
    paired.add_argument('--target', choices=TARGETS, default='unknown')
    for command in (record, local, export, paired):
        command.add_argument('--output', help='fresh local JSON file; default stdout')
    args = parser.parse_args(argv)
    try:
        code = 0
        if args.command == 'record':
            setup = args.setup_seconds
            if args.setup_report:
                setup_data = load(args.setup_report)
                if not isinstance(setup_data, dict) or 'setup_seconds' not in setup_data:
                    raise ValueError('setup report lacks setup_seconds')
                setup = number(setup_data['setup_seconds'])
            # Reject invalid explicit costs before executing a build.
            number(setup, nullable=True)
            number(args.transfer_seconds, nullable=True)
            result, code = run_record(args.binary, args.spec, setup, args.transfer_seconds, args.target)
            if code == 0 and result['status'] != 'ok':
                code = 2
        elif args.command == 'summary':
            result = summary([load(p) for p in args.records],
                             [load(p) for p in args.baseline] if args.baseline else None, args.attest_comparable)
        elif args.command == 'export':
            result = anonymous_export([load(p) for p in args.records], args.opt_in_anonymous_export)
        else:
            result = compare(args.binary, args.spec, json.loads(args.prepare_json), args.artifact,
                             args.snapshot, args.pairs, args.compiler_cache_condition,
                             args.attest_comparable, args.target)
        write(args.output, result)
        return code if 0 <= code <= 255 else 1
    except (ValueError, TypeError, KeyError, OSError, OverflowError, RecursionError):
        # Do not reflect filenames, malformed values, commands or OS error text.
        print('cache_savings: invalid input, unavailable file, or failed comparison; no result written', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
