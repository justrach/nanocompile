#!/usr/bin/env python3
"""Native automatic cache-budget integration checks (Python stdlib only).

Run: python3 tests/cache_budget.py /path/to/nanocompile
Uses isolated temporary stores and real artifact/task CLI operations; never builds
Nano or invokes a compiler. The budget counts logical bytes in entries + blobs,
not allocated filesystem blocks, download stores, or in-flight concurrent writes.
"""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

BINARY = Path(sys.argv.pop(1)).resolve()
BUDGET = 20_000
PAYLOAD_SIZE = 8 * 1024
UNSET = object()

NESTED_RUNNER = r'''import os, subprocess, sys
from pathlib import Path
binary = sys.argv[1]
source = Path('private-input').read_bytes()
assert len(source) > int(os.environ['NANOCOMPILE_MAX_SIZE'])
for arguments in (
    ['artifact', 'put', 'nested-budget', 'inner', 'private-input'],
    ['artifact', 'head', 'nested-budget', 'inner'],
    ['artifact', 'get', 'nested-budget', 'inner', 'user-output'],
):
    result = subprocess.run([binary, *arguments], capture_output=True, timeout=10)
    assert result.returncode == 0, (arguments[:2], result.returncode, result.stderr)
assert Path('user-output').read_bytes() == source
assert Path('private-input').read_bytes() == source
with Path('executions').open('a') as stream:
    stream.write('ran\n')
'''


class CacheBudget(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nano cache budget ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / 'cache'
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith('NANOCOMPILE_')}
        self.env['NANOCOMPILE_DIR'] = str(self.cache)
        self.env['NANOCOMPILE_MAX_SIZE'] = str(BUDGET)
        self.entry_paths = {}
        self.serial = 0

    def environment(self, budget=UNSET):
        env = dict(self.env)
        if budget is None:
            env.pop('NANOCOMPILE_MAX_SIZE', None)
        elif budget is not UNSET:
            env['NANOCOMPILE_MAX_SIZE'] = str(budget)
        return env

    def invoke(self, *args, expected=0, budget=UNSET, timeout=30):
        result = subprocess.run([str(BINARY), *map(str, args)], cwd=self.root,
                                env=self.environment(budget), capture_output=True,
                                timeout=timeout)
        self.assertEqual(result.returncode, expected,
                         f'{args[:3]}: stdout={result.stdout!r}, stderr={result.stderr!r}')
        return result

    def files(self, subdirectory):
        directory = self.cache / subdirectory
        return sorted(path for path in directory.rglob('*') if path.is_file())

    def logical_bytes(self):
        return sum(path.stat().st_size for sub in ('entries', 'blobs')
                   for path in self.files(sub))

    def assert_budget(self, limit=BUDGET):
        self.assertLessEqual(self.logical_bytes(), limit,
                             'settled entries + blobs exceed the logical-byte budget')

    def payload(self, label, size=PAYLOAD_SIZE):
        # Distinct deterministic content, without external randomness or tools.
        unit = (label + '\n').encode()
        return (unit * (size // len(unit) + 1))[:size]

    def put(self, key, data, *, budget=UNSET):
        self.serial += 1
        source = self.root / f'private-source-{self.serial}'
        source.write_bytes(data)
        before = set(self.files('entries'))
        result = self.invoke('artifact', 'put', 'budget-tests', key, source,
                             '{"fixture":"budget"}', budget=budget)
        self.assertTrue(json.loads(result.stdout)['stored'])
        new_entries = set(self.files('entries')) - before
        if len(new_entries) == 1:
            self.entry_paths[key] = new_entries.pop()
        self.assertEqual(source.read_bytes(), data, 'put changed the private input')
        return source

    def head(self, key, *, hit=True, budget=UNSET):
        result = self.invoke('artifact', 'head', 'budget-tests', key,
                             expected=0 if hit else 3, budget=budget)
        row = json.loads(result.stdout)
        self.assertEqual(row['hit'], hit)
        return row

    def get(self, key, data, *, budget=UNSET):
        self.serial += 1
        destination = self.root / f'user-output-{self.serial}'
        result = self.invoke('artifact', 'get', 'budget-tests', key, destination,
                             budget=budget)
        row = json.loads(result.stdout)
        self.assertTrue(row['hit'])
        self.assertEqual(row['bytes'], len(data))
        self.assertEqual(destination.read_bytes(), data)
        return destination

    def age(self, key, seconds):
        # Set both timestamps so this does not depend on host atime policy.
        path = self.entry_paths[key]
        os.utime(path, ns=(seconds * 1_000_000_000,) * 2)

    def nonempty_blob_contents(self):
        return [path.read_bytes() for path in self.files('blobs')
                if path.stat().st_size]

    def test_default_without_environment_stores_and_hits(self):
        data = self.payload('default')
        self.put('default', data, budget=None)
        self.assertEqual(len(self.files('entries')), 1)
        row = self.head('default', budget=None)
        self.assertEqual(row['bytes'], len(data))
        self.assertEqual(json.loads(row['metadata']), {'fixture': 'budget'})
        self.get('default', data, budget=None)

    def test_read_refreshes_entry_mtime_and_evicts_coldest(self):
        first, second, third = (self.payload(label) for label in ('first', 'second', 'third'))
        self.put('first', first)
        self.put('second', second)
        self.assertEqual(len(self.files('entries')), 2)
        self.assert_budget()
        self.age('first', 100)
        self.age('second', 200)
        old_mtime = self.entry_paths['first'].stat().st_mtime_ns
        self.get('first', first)
        self.assertGreater(self.entry_paths['first'].stat().st_mtime_ns, old_mtime,
                           'a hit must explicitly refresh entry recency')
        self.put('third', third)
        self.assert_budget()
        self.assertEqual(len(self.files('entries')), 2)
        self.head('second', hit=False)
        self.get('first', first)
        self.get('third', third)

    def test_shared_payload_deduplicated_until_final_reference_evicted(self):
        shared = self.payload('shared')
        independent = self.payload('independent')
        newest = self.payload('newest')
        final = self.payload('final')
        self.put('shared-a', shared)
        self.put('shared-b', shared)
        self.assertEqual(self.nonempty_blob_contents(), [shared])
        self.put('independent', independent)
        self.assertEqual(len(self.files('entries')), 3,
                         'shared payload bytes must be counted only once')
        self.assert_budget()
        self.age('shared-a', 100)
        self.age('independent', 200)
        self.age('shared-b', 300)
        self.put('newest', newest)
        self.assert_budget()
        self.head('shared-a', hit=False)
        self.head('independent', hit=False)
        self.get('shared-b', shared)
        self.get('newest', newest)
        self.assertCountEqual(self.nonempty_blob_contents(), [shared, newest])
        self.age('shared-b', 100)
        self.age('newest', 200)
        self.put('final', final)
        self.assert_budget()
        self.head('shared-b', hit=False)
        self.assertCountEqual(self.nonempty_blob_contents(), [newest, final])
        self.get('newest', newest)
        self.get('final', final)

    def test_same_key_replacement_collects_orphans_when_limit_exceeded(self):
        versions = [self.payload(f'version-{index}') for index in range(3)]
        for data in versions:
            self.put('replace', data)
        # The three physical payloads would exceed 20 KB without orphan cleanup.
        self.head('replace')  # Explicit final quiescent reconciliation.
        self.assert_budget()
        self.assertEqual(len(self.files('entries')), 1)
        self.assertEqual(self.nonempty_blob_contents(), [versions[-1]])
        self.get('replace', versions[-1])

    def test_oversized_payload_not_retained_but_input_and_outputs_survive(self):
        data = self.payload('oversized-private', BUDGET + 4096)
        user_output = self.root / 'existing-user-output'
        user_output.write_bytes(b'user-owned output must survive')
        source = self.put('oversized', data)
        self.assert_budget()
        self.head('oversized', hit=False)
        self.assertEqual(self.files('entries'), [])
        self.assertEqual(self.files('blobs'), [])
        self.assertEqual(source.read_bytes(), data)
        self.assertEqual(user_output.read_bytes(), b'user-owned output must survive')

    def test_oversized_artifact_does_not_flush_useful_small_entries(self):
        first, second = self.payload('useful-first'), self.payload('useful-second')
        self.put('first', first)
        self.put('second', second)
        self.put('oversized', self.payload('too-large', BUDGET + 4096))
        self.assert_budget()
        self.head('oversized', hit=False)
        self.get('first', first)
        self.get('second', second)
        self.assertCountEqual(self.nonempty_blob_contents(), [first, second])

    def test_manifest_bytes_count_toward_automatic_budget(self):
        data = self.payload('exactly-blob-budget')
        self.put('manifest-overhead', data, budget=len(data))
        self.assert_budget(len(data))
        self.head('manifest-overhead', hit=False, budget=len(data))
        self.assertEqual(self.files('entries'), [],
                         'a blob that fits alone still needs manifest space')
        self.assertEqual(self.files('blobs'), [])

    def test_zero_retains_neither_payloads_nor_empty_artifacts(self):
        for key, data in [('nonempty', self.payload('zero')), ('empty', b'')]:
            with self.subTest(key=key):
                self.put(key, data, budget=0)
                self.head(key, hit=False, budget=0)
                self.assert_budget(0)
                self.assertEqual(self.files('entries'), [])
                self.assertEqual(self.files('blobs'), [])

    def test_invalid_budget_rejected_before_any_child_execution(self):
        sentinel = self.root / 'child-ran'
        child = 'from pathlib import Path; Path("child-ran").write_text("ran")'
        for value in ('', '-1', 'not-bytes', '1.5', '18446744073709551616'):
            with self.subTest(value=value):
                result = subprocess.run([str(BINARY), sys.executable, '-c', child],
                                        cwd=self.root, env=self.environment(value),
                                        capture_output=True, timeout=15)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr, 'invalid configuration needs a diagnostic')
                self.assertFalse(sentinel.exists(), 'Context.init must fail before launching children')
                self.assertEqual(self.files('entries'), [])
                self.assertEqual(self.files('blobs'), [])

    def test_automatic_eviction_preserves_download_dependency_and_user_files(self):
        protected = {}
        for relative in ('downloads/package.tar', 'dependencies/installed.dat',
                         'node_modules/package/index.js', 'user-build/output.bin'):
            # Download/dependency stores can live under NANOCOMPILE_DIR, but are
            # outside the logical entries + blobs budget and must not be swept.
            path = self.cache / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            data = self.payload('protected-' + relative, BUDGET + 1)
            path.write_bytes(data)
            protected[path] = data
        source = self.put('keep', self.payload('keep'))
        restored = self.get('keep', source.read_bytes())
        for index in range(4):
            self.put(f'pressure-{index}', self.payload(f'pressure-{index}'))
        self.head('quiescent-missing', hit=False)
        self.assert_budget()
        for path, data in protected.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertEqual(source.read_bytes(), self.payload('keep'))
        self.assertEqual(restored.read_bytes(), self.payload('keep'))
        # A restored user file must not share mutable bytes with the immutable CAS.
        restored.write_bytes(b'user edit after cache restore')
        self.assertEqual(source.read_bytes(), self.payload('keep'))

    def test_concurrent_artifact_writers_and_reads_settle_within_budget(self):
        payloads = {f'key-{index}': self.payload(f'concurrent-{index}') for index in range(12)}
        sources = {}
        for key, data in payloads.items():
            source = self.root / (key + '.private')
            source.write_bytes(data)
            sources[key] = source
        self.put('key-0', payloads['key-0'])

        def operation(index):
            key = f'key-{index % len(payloads)}'
            env = self.environment()
            if index < len(payloads):
                args = ['artifact', 'put', 'budget-tests', key, str(sources[key])]
            else:
                args = ['artifact', 'get', 'budget-tests', key,
                        str(self.root / f'concurrent-output-{index}')]
            result = subprocess.run([str(BINARY), *args], cwd=self.root, env=env,
                                    capture_output=True, timeout=30)
            return index, key, args[1], result

        # Interleave puts and gets in the work queue; get may safely miss if
        # another completed operation already evicted its entry.
        order = [item for pair in zip(range(12), range(12, 24)) for item in pair]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(operation, order))
        for index, key, op, result in results:
            with self.subTest(index=index, op=op):
                self.assertIn(result.returncode, (0,) if op == 'put' else (0, 3), result.stderr)
                row = json.loads(result.stdout)
                if op == 'put':
                    self.assertTrue(row['stored'])
                else:
                    destination = self.root / f'concurrent-output-{index}'
                    self.assertEqual(row['hit'], result.returncode == 0)
                    if result.returncode == 0:
                        self.assertEqual(destination.read_bytes(), payloads[key])
                    else:
                        self.assertFalse(destination.exists())
        # Only a quiescent completed operation is required to reconcile pending
        # concurrent writes; this is deliberately not an in-flight quota test.
        self.head('final-quiescent-missing', hit=False)
        self.assert_budget()
        self.assertGreater(len(self.files('entries')), 0)
        for key, source in sources.items():
            self.assertEqual(source.read_bytes(), payloads[key])
        live = self.live_artifact_keys(payloads)
        self.assertGreater(len(live), 0)
        self.assertEqual(len(live), len(self.files('entries')))
        for key in live:
            self.get(key, payloads[key])
        self.assert_budget()

    def live_artifact_keys(self, candidates):
        # Probe through the CLI rather than depending on sealed-manifest format.
        live = set()
        for key in candidates:
            result = subprocess.run([str(BINARY), 'artifact', 'head', 'budget-tests', key],
                                    cwd=self.root, env=self.environment(), capture_output=True,
                                    timeout=30)
            self.assertIn(result.returncode, (0, 3), result.stderr)
            if result.returncode == 0:
                live.add(key)
        return live

    def test_nested_declared_task_native_artifact_cli_does_not_deadlock(self):
        source = self.root / 'private-input'
        data = self.payload('nested-private-input', BUDGET + 4096)
        source.write_bytes(data)
        runner = self.root / 'runner.py'
        runner.write_text(NESTED_RUNNER)
        spec = {'schema': 1, 'tasks': [{
            'name': 'outer',
            'command': [sys.executable, 'runner.py', str(BINARY)],
            'inputs': ['runner.py', 'private-input'],
            'outputs': ['user-output'],
        }]}
        spec_path = self.root / 'tasks.json'
        spec_path.write_text(json.dumps(spec))
        originals = {path: path.read_bytes() for path in (source, runner, spec_path)}
        self.invoke('task', spec_path, timeout=40)
        # The inner oversize artifact must be usable while its parent holds the
        # shared maintenance lock. Once the parent exits, its outputs survive
        # even though both oversize cache entries must be trimmed.
        self.assertEqual((self.root / 'executions').read_text(), 'ran\n')
        self.assertEqual((self.root / 'user-output').read_bytes(), data)
        self.assert_budget()
        self.head('final-quiescent-missing', hit=False)
        self.assertEqual(self.files('entries'), [])
        self.assertEqual(self.files('blobs'), [])
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original, 'task changed a private declared input')

    def test_events_rotate_above_one_mib_and_stats_are_recent_window(self):
        self.put('events', self.payload('events'))
        events = self.cache / 'events'
        historic_hits = (1024 * 1024 // len(b'hit\n')) + 1
        events.write_bytes(b'hit\n' * historic_hits)
        self.assertGreater(events.stat().st_size, 1024 * 1024)
        self.head('events')
        self.assertLessEqual(events.stat().st_size if events.exists() else 0, 1024 * 1024)
        result = self.invoke('stats')
        counters = dict(line.split(': ', 1) for line in result.stdout.decode().splitlines()
                        if ': ' in line)
        self.assertIn('hits', counters)
        self.assertLess(int(counters['hits']), historic_hits,
                        'stats must not continue counting the discarded historical window')
        self.assert_budget()

    def test_manual_gc_still_reports_blob_logical_bytes(self):
        self.put('manual-a', self.payload('manual-a'), budget=None)
        self.put('manual-b', self.payload('manual-b'), budget=None)
        blob_bytes = sum(path.stat().st_size for path in self.files('blobs'))
        self.assertGreater(self.logical_bytes(), blob_bytes)
        result = self.invoke('gc', blob_bytes, budget=None)
        counters = dict(line.split(': ', 1) for line in result.stdout.decode().splitlines()
                        if ': ' in line)
        self.assertEqual(int(counters['evicted entries']), 0)
        self.assertEqual(int(counters['remaining logical bytes']), blob_bytes)
        self.assertEqual(len(self.files('entries')), 2)
        self.get('manual-a', self.payload('manual-a'), budget=None)
        self.get('manual-b', self.payload('manual-b'), budget=None)


if __name__ == '__main__':
    if not BINARY.is_file():
        raise SystemExit('nanocompile binary is not ready; pass a built native CLI executable')
    unittest.main()
