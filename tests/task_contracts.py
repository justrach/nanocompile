"""Focused declared-task contracts/reporting checks; only Python's standard library.

Run: python3 tests/task_contracts.py /path/to/nanocompile
The execution log is an intentional test-only side effect, not a cached output.
"""
import copy
import json
import os
import platform
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

BINARY = Path(sys.argv.pop(1)).resolve()
RUNNER = r'''import json, os, sys
from pathlib import Path
assert 'NANOCOMPILE_TASK_REPORT' not in os.environ
name, output, *args = sys.argv[1:]
with Path('executions').open('a') as f: f.write(name + '\n')
print('child-out')
print('child-err', file=sys.stderr)
if 'fail' in args: sys.exit(7)
if 'format-spec' in args:
    p = Path('tasks.json'); p.write_text(json.dumps(json.loads(p.read_text()), indent=3))
if 'change-input' in args: Path('source').write_text('changed during child')
source = next((arg[len('consume:'):] for arg in args if arg.startswith('consume:')), 'source')
data = Path(source).read_bytes() + '|'.join(args).encode()
Path(output).write_bytes(data)
Path(output + '.extra').write_bytes(b'extra')
'''


class Contracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='nano task contracts ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cache = self.root / 'cache'
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('NANOCOMPILE_')}
        self.env['NANOCOMPILE_DIR'] = str(self.cache)
        self.env['CONTRACT_ENV'] = 'original'
        (self.root / 'runner.py').write_text(RUNNER)
        (self.root / 'source').write_bytes(b'input bytes\n')
        (self.root / 'resource-a').write_bytes(b'tool data a')
        (self.root / 'resource-b').write_bytes(b'tool data b')
        self.spec = {'schema': 1, 'tasks': [self.task()]}
        self.serial = 0
        self.save()

    def task(self, name='sensitive-contract-name', args=(), depends=()):
        output = name + '.out'
        return {'name': name, 'command': [sys.executable, 'runner.py', name, output, *args],
                'inputs': ['runner.py', 'source'], 'outputs': [output, output + '.extra'],
                'tool_resources': ['resource-a', 'resource-b'], 'depends_on': list(depends)}

    def save(self, **kwargs):
        (self.root / 'tasks.json').write_text(json.dumps(self.spec, **kwargs))

    def executed(self):
        p = self.root / 'executions'
        return p.read_text().splitlines() if p.exists() else []

    def run_task(self, *, expected=0, report=True, destination=None, env=None, filename='tasks.json'):
        self.serial += 1
        current = dict(self.env if env is None else env)
        path = self.root / f'report-{self.serial}.json' if destination is None else Path(destination)
        if report:
            current['NANOCOMPILE_TASK_REPORT'] = str(path)
        result = subprocess.run([str(BINARY), 'task', filename], cwd=self.root,
                                env=current, capture_output=True, timeout=45)
        self.assertEqual(result.returncode, expected, result.stderr.decode(errors='replace'))
        data = json.loads(path.read_text()) if report and destination is None and path.exists() else None
        if report and destination is None and expected in (0, 7):
            self.assertIsNotNone(data, result.stderr)
        if data:
            self.assertEqual(data['schema'], 1)
            self.assertGreaterEqual(data['maintenance_lock_ns'], 0)
            for row in data['tasks']:
                self.assertTrue(all(isinstance(v, int) and v >= 0 for v in row['timings'].values()))
            encoded = json.dumps(data)
            for private in (str(self.root), sys.executable, 'sensitive-contract-name', 'CONTRACT_ENV', 'runner.py'):
                self.assertNotIn(private, encoded)
        return result, data

    def clean(self):
        for task in self.spec['tasks']:
            for out in task['outputs']:
                (self.root / out).unlink(missing_ok=True)

    def test_cold_hit_report_toggle_and_exact_bytes(self):
        cold, report = self.run_task()
        row = report['tasks'][0]
        self.assertEqual((row['outcome'], row['lookup'], row['storage']), ('miss', 'entry_absent', 'stored'))
        size = sum((self.root / p).stat().st_size for p in self.spec['tasks'][0]['inputs'])
        self.assertEqual(row['input_bytes_hashed'], size)
        self.assertEqual(row['revalidation_input_bytes_hashed'], size)
        self.assertEqual(row['stored_output_bytes'], len(b'input bytes\nextra'))
        self.assertEqual(row['child_stdout_bytes'], len(cold.stdout))
        self.assertEqual(row['child_stderr_bytes'], len(cold.stderr))
        for stage in ('input_hash_ns', 'tool_identity_ns', 'lock_wait_ns', 'lookup_restore_ns',
                      'child_ns', 'revalidation_ns', 'storage_ns'):
            self.assertGreater(row['timings'][stage], 0, stage)
        self.clean()
        warm, report = self.run_task()
        self.assertEqual(report['tasks'][0]['outcome'], 'hit')
        self.assertEqual(report['tasks'][0]['restored_output_bytes'], row['stored_output_bytes'])
        self.assertEqual(report['tasks'][0]['timings']['child_ns'], 0)
        self.assertEqual((cold.stdout, cold.stderr), (warm.stdout, warm.stderr))
        self.clean()
        off, _ = self.run_task(report=False)
        self.assertEqual((off.stdout, off.stderr), (cold.stdout, cold.stderr))
        self.assertEqual(len(self.executed()), 1)
        events = (self.cache / 'events').read_text().splitlines()
        self.assertEqual(events, ['task_miss', 'task_hit', 'task_hit'])

    def test_report_off_then_on_same_key(self):
        off, _ = self.run_task(report=False)
        self.clean()
        on, report = self.run_task()
        self.assertEqual(report['tasks'][0]['outcome'], 'hit')
        self.assertEqual((off.stdout, off.stderr), (on.stdout, on.stderr))
        self.assertEqual(len(self.executed()), 1)

    def test_format_key_order_and_spec_filename_are_not_key_inputs(self):
        self.run_task()
        self.save(indent=4, sort_keys=True)
        self.clean()
        _, report = self.run_task()
        self.assertEqual(report['tasks'][0]['outcome'], 'hit')
        (self.root / 'renamed-spec.json').write_text((self.root / 'tasks.json').read_text())
        self.clean()
        _, report = self.run_task(filename='renamed-spec.json')
        self.assertEqual(report['tasks'][0]['outcome'], 'hit')
        self.assertEqual(len(self.executed()), 1)

    def test_unrelated_task_edit_only_misses_that_task(self):
        self.spec['tasks'].append(self.task('unrelated', ['before']))
        self.save()
        self.run_task()
        self.spec['tasks'][1]['command'][-1] = 'after'
        self.save()
        self.clean()
        _, report = self.run_task()
        self.assertEqual([r['outcome'] for r in report['tasks']], ['hit', 'miss'])
        self.assertEqual(self.executed(), ['sensitive-contract-name', 'unrelated', 'unrelated'])

    def test_ordered_contract_fields_and_selected_task_identity_miss(self):
        self.spec['tasks'][0]['command'] += ['first', 'second']
        self.save()
        self.run_task()
        for field in ('command', 'inputs', 'outputs', 'tool_resources'):
            original = copy.deepcopy(self.spec)
            if field == 'command':
                self.spec['tasks'][0][field][-2:] = ['second', 'first']
            else:
                self.spec['tasks'][0][field].reverse()
            self.save()
            _, report = self.run_task()
            self.assertEqual(report['tasks'][0]['outcome'], 'miss', field)
            self.spec = original
        self.spec['tasks'][0]['name'] = 'renamed-task'
        self.save()
        _, report = self.run_task()
        self.assertEqual(report['tasks'][0]['outcome'], 'miss')

    def test_ordered_dependency_edges_are_key_inputs(self):
        self.spec['tasks'] = [self.task('a'), self.task('b'), self.task('c')]
        self.save()
        self.run_task()
        self.spec['tasks'][2]['depends_on'] = ['a', 'b']
        self.save()
        _, report = self.run_task()
        self.assertEqual([r['outcome'] for r in report['tasks']], ['hit', 'hit', 'miss'])
        self.spec['tasks'][2]['depends_on'].reverse()
        self.save()
        _, report = self.run_task()
        self.assertEqual([r['outcome'] for r in report['tasks']], ['hit', 'hit', 'miss'])

    def test_declared_predecessor_output_drives_consumer_key(self):
        producer = self.task('producer', ['original'])
        consumer = self.task('consumer', ['consume:producer.out'], depends=['producer'])
        consumer['inputs'] = ['runner.py', 'producer.out']
        self.spec['tasks'] = [producer, consumer]
        self.save()
        self.run_task()
        producer['command'][-1] = 'changed'
        self.save()
        self.clean()
        _, report = self.run_task()
        self.assertEqual([r['outcome'] for r in report['tasks']], ['miss', 'miss'])
        self.assertIn(b'changed', (self.root / 'consumer.out').read_bytes())
        self.clean()
        _, report = self.run_task()
        self.assertEqual([r['outcome'] for r in report['tasks']], ['hit', 'hit'])

    def test_changed_input_and_output_declarations_miss_without_command_edit(self):
        self.run_task()
        original = copy.deepcopy(self.spec)
        self.spec['tasks'][0]['outputs'].pop()
        self.save()
        _, report = self.run_task()
        self.assertEqual(report['tasks'][0]['outcome'], 'miss')
        self.spec = original
        self.spec['tasks'][0]['inputs'].append('resource-a')
        self.save()
        _, report = self.run_task()
        self.assertEqual(report['tasks'][0]['outcome'], 'miss')

    def test_disabled_cache_reports_bypass_and_never_stores(self):
        _, report = self.run_task(env=dict(self.env, NANOCOMPILE_DISABLE='1'))
        row = report['tasks'][0]
        self.assertEqual((row['outcome'], row['lookup'], row['storage']),
                         ('bypass', 'disabled', 'not_attempted'))
        self.assertFalse(list((self.cache / 'entries').iterdir()))

    def test_large_input_preserved_mtime_and_environment_changes_miss(self):
        source = self.root / 'source'
        source.write_bytes(b'a' * (128 * 1024))
        self.run_task()
        st = source.stat()
        source.write_bytes(b'b' * (128 * 1024))
        os.utime(source, ns=(st.st_atime_ns, st.st_mtime_ns))
        _, report = self.run_task()
        self.assertEqual(report['tasks'][0]['outcome'], 'miss')
        _, report = self.run_task(env=dict(self.env, CONTRACT_ENV='changed'))
        self.assertEqual(report['tasks'][0]['outcome'], 'miss')

    def test_tool_resource_content_change_misses(self):
        self.run_task()
        (self.root / 'resource-a').write_text('changed tool bytes')
        _, report = self.run_task()
        self.assertEqual(report['tasks'][0]['outcome'], 'miss')

    def test_nonzero_child_reports_and_never_stores(self):
        self.spec['tasks'][0]['command'].append('fail')
        self.save()
        off, _ = self.run_task(expected=7, report=False)
        on, report = self.run_task(expected=7)
        row = report['tasks'][0]
        self.assertEqual((row['outcome'], row['exit_code'], row['storage']), ('failed', 7, 'not_attempted'))
        self.assertEqual((off.stdout, off.stderr), (on.stdout, on.stderr))
        self.assertFalse(list((self.cache / 'entries').iterdir()))

    def test_corrupt_manifest_and_blob_fall_back_without_false_reasons(self):
        cold, _ = self.run_task()
        entry = next((self.cache / 'entries').iterdir())
        entry.write_bytes(b'not a sealed manifest')
        _, report = self.run_task()
        self.assertEqual(report['tasks'][0]['lookup'], 'entry_unusable')
        for blob in (self.cache / 'blobs').glob('*/*'):
            if blob.read_bytes() == b'input bytes\n':
                blob.write_bytes(b'corrupt')
                break
        else:
            self.fail('fixture output blob missing')
        self.clean()
        fallback, report = self.run_task()
        self.assertEqual(report['tasks'][0]['lookup'], 'entry_unusable')
        self.assertEqual(report['tasks'][0]['storage'], 'stored')
        self.assertEqual((fallback.stdout, fallback.stderr), (cold.stdout, cold.stderr))
        self.assertEqual(len(self.executed()), 3)

    def test_mid_execution_formatting_and_input_edits_suppress_storage(self):
        for mode, reason in (('format-spec', 'spec_changed'), ('change-input', 'inputs_or_tools_changed')):
            self.spec['tasks'][0]['command'].append(mode)
            self.save()
            _, report = self.run_task()
            self.assertEqual(report['tasks'][0]['storage'], reason)
            self.assertFalse(list((self.cache / 'entries').iterdir()))
            self.spec['tasks'][0]['command'].pop()

    def test_earlier_task_spec_edit_refuses_later_task(self):
        self.spec['tasks'] = [self.task('a', ['format-spec']), self.task('b', depends=['a'])]
        self.save()
        _, report = self.run_task(expected=1)
        self.assertEqual(self.executed(), ['a'])
        self.assertEqual(report['tasks'][0]['storage'], 'spec_changed')
        self.assertFalse(list((self.cache / 'entries').iterdir()))

    def test_complete_graph_rejected_before_any_execution(self):
        variants = [
            [self.task('a'), self.task('b', depends=['unknown'])],
            [self.task('a', depends=['b']), self.task('b')],
            [self.task('a'), self.task('a')],
            [self.task('a'), dict(self.task('b'), command=[])],
        ]
        for tasks in variants:
            self.spec['tasks'] = tasks
            self.save()
            self.run_task(expected=1, report=False)
            self.assertEqual(self.executed(), [])

    def test_explicit_native_identity_keeps_default_cache_key(self):
        self.run_task()
        self.spec['tasks'][0]['host_identity'] = 'native'
        self.save()
        self.clean()
        _, report = self.run_task()
        self.assertEqual(report['tasks'][0]['outcome'], 'hit')
        self.assertEqual(len(self.executed()), 1)

    def test_platform_identity_requires_explicit_supported_host(self):
        task = self.spec['tasks'][0]
        for invalid in ('unknown', True, None):
            task['host_identity'] = invalid
            self.save()
            self.run_task(expected=1, report=False)
            self.assertEqual(self.executed(), [])
        task['host_identity'] = 'platform'
        self.save()
        if sys.platform != 'linux' or platform.machine().lower() not in ('x86_64', 'amd64'):
            # A later invalid task must prevent the earlier native one running.
            self.spec['tasks'].insert(0, self.task('earlier-native'))
            self.save()
            self.run_task(expected=1, report=False)
            self.assertEqual(self.executed(), [])
            return
        _, report = self.run_task()
        self.assertEqual(report['tasks'][0]['outcome'], 'miss')
        self.clean()
        _, report = self.run_task()
        self.assertEqual(report['tasks'][0]['outcome'], 'hit')
        mutations = [lambda: (self.root / 'source').write_bytes(b'changed input'),
                     lambda: task['command'].append('fixed-target'),
                     lambda: task['command'].append('baseline-cpu'),
                     lambda: self.env.update(CONTRACT_ENV='changed'),
                     lambda: (self.root / 'resource-a').write_bytes(b'changed tool')]
        for mutate in mutations:
            mutate()
            self.save()
            self.clean()
            _, report = self.run_task()
            self.assertEqual(report['tasks'][0]['outcome'], 'miss')

    def test_report_destinations_never_overwrite_or_materialize_missing_output(self):
        self.run_task()
        for protected in ('source', 'tasks.json', 'resource-a', self.spec['tasks'][0]['outputs'][0]):
            path = self.root / protected
            before = path.read_bytes()
            self.run_task(destination=path)
            self.assertEqual(path.read_bytes(), before)
        existing = self.root / 'existing-report'
        existing.write_text('do not replace')
        self.run_task(destination=existing)
        self.assertEqual(existing.read_text(), 'do not replace')
        # A failed task has no output: reporting must not create one in its place.
        self.spec['tasks'][0]['command'].append('fail')
        self.save()
        self.clean()
        out = self.root / self.spec['tasks'][0]['outputs'][0]
        self.run_task(expected=7, destination=out)
        self.assertFalse(out.exists())
        alias = self.root / 'alias'
        try:
            alias.symlink_to(self.root, target_is_directory=True)
        except OSError:
            return  # Symlink creation can require privileges on Windows.
        self.run_task(expected=7, destination=alias / out.name)
        self.assertFalse(out.exists())
        self.run_task(expected=7, destination=self.root / 'missing-parent' / 'report.json')
        self.assertFalse((self.root / 'missing-parent').exists())


if __name__ == '__main__':
    unittest.main()
