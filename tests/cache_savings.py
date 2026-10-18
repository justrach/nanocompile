#!/usr/bin/env python3
"""Unit checks: python3 tests/cache_savings.py (no native binary required)."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('savings_tool', Path(__file__).resolve().parents[1] / 'tools/cache_savings.py')
savings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(savings)


def native(outcome='hit'):
    return {'schema': 1, 'setup_ns': 100000000, 'total_ns': 800000000,
            'maintenance_lock_ns': 1000000, 'tasks': [{
                'task_index': 0, 'outcome': outcome,
                'lookup': {'hit': 'hit', 'miss': 'entry_absent', 'bypass': 'disabled', 'failed': 'entry_absent'}[outcome],
                'storage': 'stored' if outcome == 'miss' else 'not_attempted',
                'exit_code': 7 if outcome == 'failed' else 0,
                'timings': {stage + '_ns': (200000000 if stage == 'child' and outcome != 'hit' else 0)
                            for stage in savings.STAGES},
                'output_bytes': 123, 'input_bytes_hashed': 45, 'revalidation_input_bytes_hashed': 45}]}


def record(outcome='hit', wall=1, **kwargs):
    return savings.make_record(native(outcome), wall, 7 if outcome == 'failed' else 0, host='linux', **kwargs)


class Metrics(unittest.TestCase):
    def test_separate_timings_and_no_inclusive_sum(self):
        report = native('miss')
        report['tasks'][0]['timings'].update(lookup_restore_ns=500000000,
            lookup_ns=200000000, restore_ns=100000000, diagnostic_replay_ns=200000000)
        row = savings.make_record(report, 1, 0)
        result = savings.summary([row])['aggregate']['metrics']
        self.assertEqual(result['task_lookup_restore_seconds']['total'], .5)
        self.assertEqual(result['task_lookup_seconds']['total'], .2)
        self.assertEqual(result['task_restore_seconds']['total'], .1)
        self.assertEqual(result['process_overhead_seconds']['total'], .8)
        self.assertEqual(result['native_setup_seconds']['total'], .1)
        self.assertEqual(result['artifact_bytes']['total'], 123)

    def test_unknown_external_costs_never_zero(self):
        row = record()
        self.assertIsNone(row['external_setup_seconds'])
        result = savings.summary([row])['aggregate']
        self.assertEqual(result['metrics']['observed_total_seconds']['total'], 1)
        self.assertIsNone(result['metrics']['complete_total_seconds']['total'])
        self.assertIsNone(result['metrics']['external_transfer_seconds']['total'])
        self.assertEqual(result['incomplete_external_cost_samples'], 1)
        full = savings.summary([record(setup_seconds=2, transfer_seconds=0)])['aggregate']
        self.assertEqual(full['metrics']['complete_total_seconds']['total'], 3)

    def test_older_native_report_is_incomplete_not_zero(self):
        report = native()
        del report['setup_ns']
        del report['tasks'][0]['timings']['lookup_ns']
        del report['tasks'][0]['output_bytes']
        row = savings.make_record(report, 1, 0)
        self.assertEqual(row['status'], 'ok')
        self.assertIsNone(row['metrics']['native_setup_seconds'])
        self.assertIsNone(row['metrics']['task_lookup_seconds'])
        self.assertIsNone(row['metrics']['artifact_bytes'])

    def test_lookup_hit_rate_excludes_bypass(self):
        result = savings.summary([record(), record('miss'), record('bypass')])['aggregate']
        self.assertEqual(result['hit_rate'], .5)
        self.assertEqual(result['lookup_attempts'], 2)
        self.assertEqual(result['task_counts']['bypass'], 1)

    def test_cold_miss_hit_is_not_a_speedup(self):
        result = savings.summary([record('miss', 4), record('hit', 1)])
        self.assertIsNone(result['estimated_savings'])
        self.assertIsNone(result['measured_speedup'])

    def test_historical_estimate_explicit_negative_and_not_measured(self):
        current, baseline = [record(wall=3)], [record('bypass', 1)]
        for args in ((current, baseline, False), (current, [record('hit')], True),
                     (current, [record('miss'), record('bypass')], True),
                     (current, [record('bypass', target='aarch64')], True),
                     (current, [], True), ([record('failed')], baseline, True)):
            with self.assertRaises(ValueError):
                savings.summary(*args)
        result = savings.summary(current, baseline, True)
        self.assertEqual(result['estimated_savings']['seconds'], -2)
        self.assertEqual(result['estimated_savings']['baseline_samples'], 1)
        self.assertFalse(result['estimated_savings']['controlled_measurement'])
        self.assertIsNone(result['measured_speedup'])

    def test_historical_misses_are_labelled_estimates_with_sample_counts(self):
        result = savings.summary([record('hit', 1), record('hit', 1)],
                                 [record('miss', 3), record('miss', 5)], True)
        estimate = result['estimated_savings']
        self.assertEqual(estimate['seconds'], 6)
        self.assertEqual(estimate['baseline_kind'], 'miss')
        self.assertEqual(estimate['baseline_samples'], 2)
        self.assertEqual(estimate['evaluated_samples'], 2)
        self.assertEqual(estimate['compiler_cache_condition'], 'historical_uncontrolled')
        self.assertFalse(estimate['controlled_measurement'])
        self.assertIsNone(result['measured_speedup'])

    def test_nonfinite_negative_bool_metrics_rejected(self):
        for value in (True, False, -1, float('nan'), float('inf'), -float('inf'), 'secret', 10 ** 1000):
            with self.subTest(value=type(value)):
                row = record()
                row['process_seconds'] = value
                with self.assertRaises(ValueError):
                    savings.summary([row])
                row = record()
                row['metrics']['task_child_seconds'] = value
                with self.assertRaises(ValueError):
                    savings.anonymous_export([row] * 5, True)
                report = native()
                report['tasks'][0]['timings']['restore_ns'] = value
                self.assertEqual(savings.make_record(report, 1, 0)['status'], 'report_invalid')

    def test_impossible_counts_and_overhead_rejected(self):
        for mutate in (lambda r: r.update(lookup_attempts=0),
                       lambda r: r['task_counts'].update(hit=True),
                       lambda r: r['metrics'].update(task_child_seconds=2),
                       lambda r: r.update(schema=True),
                       lambda r: r.update(platform='private-host')):
            row = record()
            mutate(row)
            with self.assertRaises(ValueError):
                savings.summary([row])

    def test_failure_and_missing_report(self):
        self.assertEqual(record('failed')['status'], 'command_failed')
        row = savings.make_record(None, .5, 0)
        self.assertEqual(row['status'], 'report_missing')
        self.assertIsNone(savings.summary([row])['aggregate']['metrics']['process_overhead_seconds']['total'])
        self.assertEqual(savings.make_record({}, .5, 0)['status'], 'report_invalid')


class Privacy(unittest.TestCase):
    def test_export_requires_opt_in_and_five_samples(self):
        with self.assertRaises(ValueError):
            savings.anonymous_export([record()] * 5)
        for count in range(5):
            with self.assertRaises(ValueError):
                savings.anonymous_export([record()] * count, True)
        self.assertEqual(savings.anonymous_export([record()] * 5, True)['aggregate']['samples'], 5)

    def test_unknown_fields_are_never_forwarded(self):
        secret = 'SECRET-private-path-command-key-hash-machine-name'
        report = native()
        report['private'] = secret
        report['tasks'][0]['name'] = secret
        report['tasks'][0]['timings']['private'] = secret
        row = savings.make_record(report, 1, 0)
        row['private'] = secret
        row['metrics']['private'] = secret
        row['task_counts']['private'] = secret
        for output in (savings.summary([row]), savings.anonymous_export([row] * 5, True)):
            self.assertNotIn(secret, json.dumps(output))
            self.assertNotIn('private', json.dumps(output))

    def test_breakdown_and_metric_observation_thresholds(self):
        rows = [record(target='x86_64') for _ in range(5)] + [record(target='aarch64', setup_seconds=9)]
        result = savings.anonymous_export(rows, True)
        self.assertEqual(len(result['breakdowns']), 1)
        self.assertEqual(result['breakdowns'][0]['target'], 'x86_64')
        self.assertIsNone(result['aggregate']['metrics']['external_setup_seconds'])
        self.assertNotIn('aarch64', json.dumps(result))
        rows[0]['metrics']['artifact_bytes'] = None
        self.assertIsNone(savings.anonymous_export(rows[:5], True)['aggregate']['metrics']['artifact_bytes'])

    def test_json_duplicate_and_nonfinite_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.json'
            for text in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    savings.load(path)

    def test_setup_import_allowlist_and_private_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'private-secret.json'
            path.write_text(json.dumps({'setup_seconds': 4, 'key': 'secret', 'hash': 'secret'}))
            output = io.StringIO()
            with mock.patch.object(savings, 'run_record', return_value=(record(setup_seconds=4), 0)) as run, contextlib.redirect_stdout(output):
                self.assertEqual(savings.main(['record', '--binary', 'private-binary', '--spec', 'private-spec', '--setup-report', str(path)]), 0)
            self.assertEqual(run.call_args.args[2], 4)
            self.assertNotIn('secret', output.getvalue())
            path.write_text('{"setup_seconds":-1,"key":"secret"}')
            errors = io.StringIO()
            with mock.patch.object(savings, 'run_record') as run, contextlib.redirect_stderr(errors):
                self.assertEqual(savings.main(['record', '--binary', 'private-binary', '--spec', 'private-spec', '--setup-report', str(path)]), 2)
                run.assert_not_called()
            self.assertNotIn('private', errors.getvalue())
            self.assertNotIn('secret', errors.getvalue())

    def test_argument_errors_do_not_echo_private_values(self):
        for argv in (['record', '--binary', 'secret-path', '--spec', 'secret-spec', '--target', 'secret-host'],
                     ['record', '--binary', 'secret-path', '--spec', 'secret-spec', '--setup-seconds', 'secret'],
                     ['secret-command']):
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
                savings.main(argv)
            self.assertEqual(raised.exception.code, 2)
            self.assertNotIn('secret', errors.getvalue())

    def test_failed_command_is_recorded_and_child_logs_discarded(self):
        with mock.patch.object(savings.subprocess, 'run', return_value=subprocess.CompletedProcess([], 7)) as run:
            row, code = savings.run_record('private-binary', 'private-spec')
        self.assertEqual(code, 7)
        self.assertEqual(row['status'], 'command_failed')
        self.assertEqual(run.call_args.kwargs['stdout'], subprocess.DEVNULL)
        self.assertEqual(run.call_args.kwargs['stderr'], subprocess.DEVNULL)
        self.assertNotIn('private', json.dumps(row))
        self.assertFalse(Path(run.call_args.kwargs['env']['NANOCOMPILE_TASK_REPORT']).parent.exists())


class Paired(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.spec, self.source, self.artifact = [root / p for p in ('spec', 'source', 'out')]
        for path in (self.spec, self.source, self.artifact):
            path.write_bytes(b'fixed')
        self.kwargs = dict(binary='unused', spec=str(self.spec), prepare=['prepare'],
            artifacts=[str(self.artifact)], sources=[str(self.source)], pairs=2,
            compiler_condition='fresh', attest=True)

    def fake_run(self, *args, **kwargs):
        bypass = kwargs['env'].get('NANOCOMPILE_DISABLE') == '1'
        return record('bypass' if bypass else 'hit', 1 if bypass else 2), 0

    def test_alternating_same_prepare_negative_measured_savings(self):
        with mock.patch.object(savings, 'run_record', side_effect=self.fake_run) as run, mock.patch.object(savings.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as prepare:
            result = savings.compare(**self.kwargs)
        self.assertEqual([c.kwargs['env'].get('NANOCOMPILE_DISABLE') for c in run.call_args_list], [None, '1', '1', None])
        self.assertEqual(prepare.call_count, 4)
        self.assertTrue(all(c.args[0] == ['prepare'] for c in prepare.call_args_list))
        self.assertEqual(result['preparation']['samples_per_mode'], 2)
        self.assertGreaterEqual(result['preparation']['enabled_seconds'], 0)
        self.assertGreaterEqual(result['preparation']['bypass_seconds'], 0)
        self.assertFalse(result['preparation']['included_in_process_speedup'])
        self.assertEqual(result['measured_speedup']['saved_seconds'], -2)
        self.assertEqual(result['measured_speedup']['ratio_bypass_over_enabled'], .5)
        self.assertNotIn(str(self.source), json.dumps(result))

    def test_bogus_pair_contracts(self):
        for change in ({'attest': False}, {'prepare': []}, {'sources': []}, {'artifacts': []},
                       {'pairs': True}, {'compiler_condition': 'automatic'}):
            kwargs = dict(self.kwargs, **change)
            with self.assertRaises(ValueError):
                savings.compare(**kwargs)

    def test_failures_never_yield_speedup(self):
        cases = [(record('failed'), 7), (savings.make_record(None, 1, 0), 0), (record('bypass'), 0)]
        for result in cases:
            with mock.patch.object(savings, 'run_record', return_value=result), mock.patch.object(savings.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
                with self.assertRaises(ValueError):
                    savings.compare(**self.kwargs)
        with mock.patch.object(savings.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)), mock.patch.object(savings, 'run_record') as run:
            with self.assertRaises(ValueError):
                savings.compare(**self.kwargs)
            run.assert_not_called()

    def test_snapshot_mutation_and_artifact_mismatch(self):
        def changed(*args, **kwargs):
            self.source.write_bytes(b'changed')
            return self.fake_run(*args, **kwargs)
        with mock.patch.object(savings, 'run_record', side_effect=changed), mock.patch.object(savings.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaises(ValueError):
                savings.compare(**self.kwargs)
        def mismatch(*args, **kwargs):
            self.artifact.write_bytes(b'bypass' if kwargs['env'].get('NANOCOMPILE_DISABLE') else b'enabled')
            return self.fake_run(*args, **kwargs)
        with mock.patch.object(savings, 'run_record', side_effect=mismatch), mock.patch.object(savings.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaises(ValueError):
                savings.compare(**self.kwargs)

    @unittest.skipIf(os.name == 'nt', 'POSIX mode bits')
    def test_permission_mismatch(self):
        def mismatch(*args, **kwargs):
            self.artifact.chmod(0o600 if kwargs['env'].get('NANOCOMPILE_DISABLE') else 0o700)
            return self.fake_run(*args, **kwargs)
        with mock.patch.object(savings, 'run_record', side_effect=mismatch), mock.patch.object(savings.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaises(ValueError):
                savings.compare(**self.kwargs)


if __name__ == '__main__':
    unittest.main()
