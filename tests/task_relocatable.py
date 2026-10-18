"""Opt-in cross-checkout task reuse and conservative invalidation checks.

Run: python3 tests/task_relocatable.py /path/to/nanocompile
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

BINARY = Path(sys.argv.pop(1)).resolve()
RUNNER = '''import os, sys
from pathlib import Path
assert 'EXCLUDED_RESOURCE' not in os.environ
assert 'NANOCOMPILE_TASK_REPORT' not in os.environ
with Path('executions').open('a') as f: f.write('run\\n')
data = Path('source').read_bytes() + Path(sys.argv[1]).read_bytes()
data += os.environ.get('CONTRACT_VALUE', '<absent>').encode()
data += '|'.join(sys.argv[2:]).encode()
Path('out').write_bytes(data)
Path('sidecar').write_bytes(b'sidecar:' + data)
Path('out').chmod(0o755)
print('portable diagnostics')
'''


class RelocatableTasks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nano-relocatable-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.a = self.root / 'checkout-a'
        self.b = self.root / 'checkout-b'
        self.cache = self.root / 'cache'
        self.sdk = self.root / 'installed-sdk-resource'
        self.sdk.write_bytes(b'sdk-v1')
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('NANOCOMPILE_')}
        self.env.update(NANOCOMPILE_DIR=str(self.cache), CONTRACT_VALUE='v1',
                        EXCLUDED_RESOURCE='/undeclared/resource')
        self.spec = {'schema': 1, 'tasks': [{
            'name': 'portable', 'command': [sys.executable, '-S', '-B', 'runner.py', str(self.sdk)],
            'inputs': ['runner.py', 'source'], 'outputs': ['out', 'sidecar'],
            'tool_resources': [str(self.sdk)],
            'relocatable': {'path_independent': True, 'resources_complete': True,
                            'environment': ['CONTRACT_VALUE', 'SYSTEMROOT']},
        }]}
        for root in (self.a, self.b):
            root.mkdir()
            (root / 'runner.py').write_text(RUNNER)
            (root / 'source').write_bytes(b'source-v1')
            self.save(root)
        self.serial = 0

    def save(self, root, spec=None):
        (root / 'tasks.json').write_text(json.dumps(self.spec if spec is None else spec))

    def invoke(self, root, expected='miss', env=None):
        self.serial += 1
        report = self.root / ('report-%d.json' % self.serial)
        current = dict(self.env if env is None else env)
        current['NANOCOMPILE_TASK_REPORT'] = str(report)
        result = subprocess.run([str(BINARY), 'task', 'tasks.json'], cwd=root,
                                env=current, capture_output=True, timeout=45)
        if expected == 'reject':
            self.assertNotEqual(result.returncode, 0, result.stdout)
            return result
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        row = json.loads(report.read_text())['tasks'][0]
        self.assertEqual(row['outcome'], expected, row)
        self.assertEqual(row['storage'], 'stored' if expected == 'miss' else 'not_attempted')
        return result

    def test_cross_root_restore_without_original_checkout(self):
        cold = self.invoke(self.a)
        expected = [(self.a / name).read_bytes() for name in ('out', 'sidecar')]
        mode = (self.a / 'out').stat().st_mode
        shutil.rmtree(self.a)
        warm = self.invoke(self.b, 'hit')
        self.assertEqual((cold.stdout, cold.stderr), (warm.stdout, warm.stderr))
        self.assertFalse((self.b / 'executions').exists())
        self.assertEqual([(self.b / name).read_bytes() for name in ('out', 'sidecar')], expected)
        self.assertEqual((self.b / 'out').stat().st_mode, mode)
        # No original checkout path in a relocatable manifest.
        for entry in (self.cache / 'entries').iterdir():
            self.assertNotIn(str(self.a).encode(), entry.read_bytes())

    def test_source_sdk_declared_environment_and_command_invalidate(self):
        self.invoke(self.a)
        self.invoke(self.b, 'hit')
        (self.b / 'source').write_bytes(b'source-v2')
        self.invoke(self.b)
        self.assertTrue((self.b / 'out').read_bytes().startswith(b'source-v2'))
        self.sdk.write_bytes(b'sdk-v2-different-size')
        self.invoke(self.b)
        self.assertIn(b'sdk-v2-different-size', (self.b / 'out').read_bytes())
        self.env['CONTRACT_VALUE'] = 'v2'
        self.invoke(self.b)
        self.assertTrue((self.b / 'out').read_bytes().endswith(b'v2'))
        # Native CPU and output-affecting arguments are never stripped.
        self.spec['tasks'][0]['command'].append('-mcpu=native')
        self.save(self.b)
        self.invoke(self.b)
        self.assertIn(b'-mcpu=native', (self.b / 'out').read_bytes())
        del self.env['CONTRACT_VALUE']
        self.invoke(self.b)
        self.assertIn(b'<absent>', (self.b / 'out').read_bytes())

    def test_excluded_environment_is_absent_not_just_unhashed(self):
        self.invoke(self.a)
        self.env['EXCLUDED_RESOURCE'] = '/different/undeclared/resource'
        self.invoke(self.b, 'hit')
        # Changing the declared name set is itself a key change, even if unset.
        self.spec['tasks'][0]['relocatable']['environment'].append('UNSET_OPTION')
        self.save(self.b)
        self.invoke(self.b)

    def test_absolute_arguments_are_not_rewritten(self):
        for root in (self.a, self.b):
            spec = copy.deepcopy(self.spec)
            spec['tasks'][0]['command'].append(str(root / 'source'))
            self.save(root, spec)
            self.invoke(root)
            self.assertIn(str(root).encode(), (root / 'out').read_bytes())

    def test_strict_default_preserves_path_sensitive_builds(self):
        self.spec['tasks'][0].pop('relocatable')
        for root in (self.a, self.b):
            self.save(root)
            (root / 'runner.py').write_text(
                "from pathlib import Path\nPath('out').write_text(str(Path.cwd()))\n"
                "Path('sidecar').write_text('strict')\n")
            self.invoke(root)
            self.assertEqual((root / 'out').read_text(), str(root))

    def test_incomplete_contract_rejects_before_any_task_executes(self):
        for field in ('path_independent', 'resources_complete'):
            spec = copy.deepcopy(self.spec)
            spec['tasks'][0]['relocatable'][field] = False
            self.save(self.a, spec)
            self.invoke(self.a, 'reject')
        self.assertFalse((self.a / 'executions').exists())
        # A later invalid contract also prevents a valid earlier child running.
        spec = copy.deepcopy(self.spec)
        spec['tasks'].append(copy.deepcopy(spec['tasks'][0]))
        spec['tasks'][1]['name'] = 'invalid'
        spec['tasks'][1]['relocatable']['resources_complete'] = False
        self.save(self.a, spec)
        self.invoke(self.a, 'reject')
        self.assertFalse((self.a / 'executions').exists())

    def test_external_project_paths_and_relative_tools_reject(self):
        for field, value in (('inputs', ['runner.py', '../installed-sdk-resource']),
                             ('inputs', ['runner.py', str(self.sdk)]),
                             ('outputs', ['../escaped']),
                             ('tool_resources', ['source']),
                             ('command', ['python3', 'runner.py']),
                             ('cwd', '..')):
            spec = copy.deepcopy(self.spec)
            spec['tasks'][0][field] = value
            self.save(self.a, spec)
            self.invoke(self.a, 'reject')
        self.assertFalse((self.a / 'executions').exists())
        self.assertFalse((self.root / 'escaped').exists())

    def test_symlink_inputs_and_output_ancestors_reject(self):
        alias = self.a / 'alias'
        try:
            alias.symlink_to(self.sdk)
        except OSError:
            self.skipTest('symlink creation not available')
        self.spec['tasks'][0]['inputs'].append('alias')
        self.save(self.a)
        self.invoke(self.a, 'reject')
        self.spec['tasks'][0]['inputs'].pop()
        alias.unlink()
        alias.symlink_to(self.b, target_is_directory=True)
        self.spec['tasks'][0]['outputs'] = ['alias/escaped']
        self.save(self.a)
        self.invoke(self.a, 'reject')
        self.assertFalse((self.b / 'escaped').exists())

    def test_nested_working_directory_relocates(self):
        self.spec['tasks'][0]['cwd'] = 'nested'
        for root in (self.a, self.b):
            nested = root / 'nested'
            nested.mkdir()
            for name in ('source', 'runner.py'):
                (root / name).rename(nested / name)
            self.save(root)
        self.invoke(self.a)
        self.invoke(self.b, 'hit')
        self.assertEqual((self.a / 'nested/out').read_bytes(), (self.b / 'nested/out').read_bytes())

    def test_disable_still_bypasses_filtered_child_environment(self):
        self.env['NANOCOMPILE_DISABLE'] = '1'
        self.invoke(self.a, 'bypass')
        del self.env['NANOCOMPILE_DISABLE']
        self.invoke(self.b)
        self.invoke(self.a, 'hit')

    def test_duplicate_and_reporting_environment_names_reject(self):
        for names in (['CONTRACT_VALUE', 'CONTRACT_VALUE'], [''], ['X=Y'],
                      ['NANOCOMPILE_TASK_REPORT']):
            self.spec['tasks'][0]['relocatable']['environment'] = names
            self.save(self.a)
            self.invoke(self.a, 'reject')

    def test_corrupt_relocatable_blob_rebuilds_in_new_checkout(self):
        self.invoke(self.a)
        payload = (self.a / 'out').read_bytes()
        blobs = [p for p in (self.cache / 'blobs').glob('*/*') if p.read_bytes() == payload]
        self.assertEqual(len(blobs), 1)
        blobs[0].write_bytes(b'corrupt')
        self.invoke(self.b)
        self.assertEqual((self.b / 'out').read_bytes(), payload)
        self.assertTrue((self.b / 'executions').exists())


if __name__ == '__main__':
    unittest.main()
