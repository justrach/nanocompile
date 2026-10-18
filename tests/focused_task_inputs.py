"""Executable complete, focused input contract (Python standard library only).

Run: python3 tests/focused_task_inputs.py /path/to/nanocompile
See docs/focused-task-inputs.md. All fixtures/cache files live in a temporary tree.
"""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import sysconfig
import tempfile
import unittest


BINARY = Path(sys.argv.pop(1)).resolve() if __name__ == '__main__' else None
PYTHON_FLAGS = ['-I', '-S', '-B']

# No imports beyond built-in sys: the runtime probe below covers startup modules.
# Names and lengths are serialized too, so membership and empty files matter.
SCRIPT = '''import sys
with open(sys.argv[1], 'wb') as output:
    output.write(b'{marker}\\n')
    for name in sys.argv[2:]:
        with open(name, 'rb') as source:
            data = source.read()
        encoded = name.encode('utf-8')
        output.write(str(len(encoded)).encode('ascii') + b':' + encoded)
        output.write(str(len(data)).encode('ascii') + b':' + data)
'''


def members(root, directory):
    """Caller-owned discovery, rerun before EVERY cache invocation.

    There are no symlink/metadata/optional-path semantics in this example.
    All files under each selected root are data; nothing is filtered by suffix.
    """
    result = []
    for path in sorted((root / directory).rglob('*')):
        if path.is_symlink():
            raise ValueError('fixture discovery does not accept symlinks')
        mode = path.stat().st_mode
        if stat.S_ISREG(mode):
            result.append(path.relative_to(root).as_posix())
        elif not stat.S_ISDIR(mode):
            raise ValueError('fixture discovery requires regular files')
    return result


def python_resources():
    """Resources for this no-extra-imports Python command, not arbitrary Python.

    Include source and any existing bytecode used by isolated interpreter
    startup, plus conventional Python shared-library locations. Native OS
    libraries belong to the trusted host installation (see the documentation).
    """
    probe = ('import sys; print(repr(sorted(set(p for m in sys.modules.values() '
             'for p in (getattr(m, "__file__", None), '
             'getattr(m, "__cached__", None)) if isinstance(p, str)))))')
    import ast
    completed = subprocess.run([sys.executable, *PYTHON_FLAGS, '-c', probe],
                               check=True, capture_output=True, text=True, timeout=45)
    candidates = [Path(p) for p in ast.literal_eval(completed.stdout)]
    base = Path(sys.base_prefix)
    candidates += [base / 'Python', base / 'Python3',
                   base / ('python%d%d.dll' % sys.version_info[:2]),
                   base / 'python3.dll']
    library = sysconfig.get_config_var('LDLIBRARY')
    libdir = sysconfig.get_config_var('LIBDIR')
    if library:
        candidates += [base / library]
        if libdir:
            candidates.append(Path(libdir) / library)
    return sorted({str(p.resolve()) for p in candidates if p.is_file()})


class FocusedInputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime_resources = python_resources()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='nano focused inputs ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('NANOCOMPILE_')}
        self.env['NANOCOMPILE_DIR'] = str(self.root / 'cache')
        for name, data in {
            'scripts/generate.py': SCRIPT.format(marker='generate-v1'),
            'scripts/build.py': SCRIPT.format(marker='build-v1'),
            'schema/model.txt': 'field: name\n',
            'src/main.txt': 'main source\n',
            'src/optional.txt': 'optional source\n',
            'config/build.json': '{"mode":"release"}\n',
            'deps.lock': 'demo-package=1\n',
            'vendor/demo/package.json': '{"name":"demo-package","version":1}\n',
            'vendor/demo/payload.txt': 'installed package contents\n',
            'generated-external/vendor.inc': 'externally supplied generated source\n',
            'tool/banner.txt': 'installed tool resource v1\n',
            'docs/guide.md': 'documentation not consumed by this build\n',
        }.items():
            self.write(name, data)
        (self.root / 'out').mkdir()
        self.spec = None

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding='utf-8')

    def discover(self):
        schemas = members(self.root, 'schema')
        build_data = (members(self.root, 'src') + members(self.root, 'config')
                      + ['deps.lock'] + members(self.root, 'vendor')
                      + members(self.root, 'generated-external') + ['out/model.txt'])
        resources = ['tool/banner.txt', *self.runtime_resources]
        self.spec = {'schema': 1, 'tasks': [
            {'name': 'generate',
             'command': [sys.executable, *PYTHON_FLAGS, 'scripts/generate.py',
                         'out/model.txt', *schemas],
             'inputs': ['scripts/generate.py', *schemas],
             'outputs': ['out/model.txt'],
             'tool_resources': self.runtime_resources,
             'depends_on': []},
            {'name': 'build',
             'command': [sys.executable, *PYTHON_FLAGS, 'scripts/build.py',
                         'out/artifact.bin', *build_data, 'tool/banner.txt'],
             'inputs': ['scripts/build.py', *build_data],
             'outputs': ['out/artifact.bin'],
             'tool_resources': resources,
             'depends_on': ['generate']},
        ]}
        (self.root / 'tasks.json').write_text(json.dumps(self.spec, indent=2), encoding='utf-8')

    def clean_outputs(self):
        for task in self.spec['tasks']:
            for name in task['outputs']:
                (self.root / name).unlink(missing_ok=True)

    def outputs(self):
        return {name: (self.root / name).read_bytes()
                for task in self.spec['tasks'] for name in task['outputs']}

    def run_checked(self, outcomes):
        # Re-discovery, not an exclusion list or nanocompile glob, captures
        # additions/deletions. The ordered command names also encode membership.
        self.discover()
        self.clean_outputs()
        events = self.root / 'cache' / 'events'
        before = len(events.read_text().splitlines()) if events.exists() else 0
        result = subprocess.run([str(BINARY), 'task', 'tasks.json'], cwd=self.root,
                                env=self.env, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        actual_events = events.read_text().splitlines()[before:]
        self.assertEqual(actual_events, ['task_' + outcome for outcome in outcomes])
        cached = self.outputs()
        self.assertTrue(cached['out/artifact.bin'].startswith(b'build-'))
        self.assertIn(cached['out/model.txt'], cached['out/artifact.bin'])
        # A hit must restore real output, not merely report an eligible key.
        # Compare every file against a fresh uncached execution of the same DAG.
        self.clean_outputs()
        for task in self.spec['tasks']:
            subprocess.run(task['command'], cwd=self.root, env=self.env,
                           check=True, capture_output=True, timeout=45)
        self.assertEqual(cached, self.outputs())
        return cached

    def cold(self):
        return self.run_checked(['miss', 'miss'])

    def test_documentation_edit_is_a_hit_with_identical_restored_bytes(self):
        initial = self.cold()
        self.write('docs/guide.md', 'completely rewritten unrelated documentation\n')
        self.write('docs/new-page.md', 'new unrelated documentation\n')
        self.assertEqual(initial, self.run_checked(['hit', 'hit']))
        (self.root / 'docs/guide.md').unlink()
        self.assertEqual(initial, self.run_checked(['hit', 'hit']))

    def test_source_config_lock_package_and_generated_input_edits_miss(self):
        previous = self.cold()
        for name in ('src/main.txt', 'config/build.json', 'deps.lock',
                     'vendor/demo/package.json', 'vendor/demo/payload.txt',
                     'generated-external/vendor.inc'):
            with self.subTest(input=name):
                self.write(name, 'changed bytes: ' + name + '\n')
                current = self.run_checked(['hit', 'miss'])
                self.assertNotEqual(previous['out/artifact.bin'], current['out/artifact.bin'])
                previous = current
                self.assertEqual(current, self.run_checked(['hit', 'hit']))

    def test_build_and_generator_scripts_and_schema_are_inputs(self):
        previous = self.cold()
        self.write('scripts/build.py', SCRIPT.format(marker='build-v2'))
        current = self.run_checked(['hit', 'miss'])
        self.assertNotEqual(previous['out/artifact.bin'], current['out/artifact.bin'])
        for name, data in (
            ('scripts/generate.py', SCRIPT.format(marker='generate-v2')),
            ('schema/model.txt', 'field: changed model\n'),
        ):
            with self.subTest(input=name):
                previous = current
                self.write(name, data)
                current = self.run_checked(['miss', 'miss'])
                self.assertNotEqual(previous['out/model.txt'], current['out/model.txt'])
                self.assertNotEqual(previous['out/artifact.bin'], current['out/artifact.bin'])
                self.assertEqual(current, self.run_checked(['hit', 'hit']))

    def test_installed_tool_resource_change_misses(self):
        previous = self.cold()
        # Trusted installed tools use metadata identities: use a different size,
        # not a same-metadata rewrite that is outside the installation contract.
        self.write('tool/banner.txt', 'installed tool resource replacement, version two\n')
        current = self.run_checked(['hit', 'miss'])
        self.assertNotEqual(previous['out/artifact.bin'], current['out/artifact.bin'])
        self.assertEqual(current, self.run_checked(['hit', 'hit']))

    def test_discovery_additions_and_deletions_change_membership(self):
        previous = self.cold()
        for directory, original, outcomes in (
            ('src', 'src/optional.txt', ['hit', 'miss']),
            ('config', 'config/build.json', ['hit', 'miss']),
            ('vendor/demo', 'vendor/demo/payload.txt', ['hit', 'miss']),
            ('generated-external', 'generated-external/vendor.inc', ['hit', 'miss']),
            ('schema', 'schema/model.txt', ['miss', 'miss']),
        ):
            with self.subTest(directory=directory):
                # Empty additions still change semantics: the program encodes names.
                added = directory + '/added.txt'
                self.write(added, '')
                current = self.run_checked(outcomes)
                task = self.spec['tasks'][0 if directory == 'schema' else 1]
                self.assertIn(added, task['inputs'])
                self.assertNotEqual(previous['out/artifact.bin'], current['out/artifact.bin'])
                previous = current
                # Delete an ORIGINAL member, not the newly added one: this is a
                # never-seen contract, so a miss (rather than a valid old hit) is expected.
                (self.root / original).unlink()
                current = self.run_checked(outcomes)
                task = self.spec['tasks'][0 if directory == 'schema' else 1]
                self.assertNotIn(original, task['inputs'])
                self.assertNotEqual(previous['out/artifact.bin'], current['out/artifact.bin'])
                previous = current
                self.assertEqual(current, self.run_checked(['hit', 'hit']))


if __name__ == '__main__':
    unittest.main()
