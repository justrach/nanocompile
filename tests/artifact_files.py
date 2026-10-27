"""File-granular opaque artifact CLI integration; isolated native stores only."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

BINARY = Path(sys.argv.pop(1)).resolve()


class ArtifactFiles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nano artifact files ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / 'cache'
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('NANOCOMPILE_')}
        self.env.update(NANOCOMPILE_DIR=str(self.cache), NANOCOMPILE_MAX_SIZE=str(2 * 1024 * 1024))
        self.serial = 0

    def run_cli(self, *args, expected=0):
        p = subprocess.run([str(BINARY), *map(str, args)], cwd=self.root,
                           env=self.env, capture_output=True, timeout=30)
        self.assertEqual(p.returncode, expected, p.stderr.decode(errors='replace'))
        return json.loads(p.stdout) if p.stdout.strip() else None

    def inventory(self, files=None, directories=None):
        self.serial += 1
        paths = []
        for index, (name, data) in enumerate((files or {}).items()):
            source = self.root / f'source-{self.serial}-{index}'
            source.write_bytes(data)
            paths.append({'path': name, 'source': str(source)})
        spec = self.root / f'inventory-{self.serial}.json'
        spec.write_text(json.dumps({'schema': 1, 'directories': directories or [], 'files': paths}))
        return spec

    def put(self, key, spec, metadata='{}', expected=0):
        return self.run_cli('artifact', 'put-files', 'files-test', key, spec, metadata, expected=expected)

    def entry(self, key):
        for p in (self.cache / 'entries').iterdir():
            obj = json.loads(p.read_bytes().split(b'\n', 1)[1])
            info = obj.get('artifact') or {}
            if info.get('namespace') == 'files-test' and info.get('key') == key:
                return p, obj
        self.fail('expected sealed artifact entry')

    def blob(self, digest):
        return self.cache / 'blobs' / digest[:2] / digest

    def test_roundtrip_empty_dirs_metadata_copy_isolation_and_identity(self):
        spec = self.inventory({'cache/a': b'first', 'cache/b': b'second'}, ['cache', 'empty'])
        row = self.put('one', spec, '{"fixture":true}')
        self.assertEqual((row['files'], row['bytes']), (2, 11))
        entry_path, entry = self.entry('one')
        self.assertNotIn(str(self.root), entry_path.read_text())
        self.assertEqual(len(entry['outputs']), 2)
        target = self.root / 'restore'
        row = self.run_cli('artifact', 'get-files', 'files-test', 'one', target)
        self.assertEqual(json.loads(row['metadata']), {'fixture': True})
        self.assertEqual((target / 'cache/a').read_bytes(), b'first')
        self.assertTrue((target / 'empty').is_dir())
        (target / 'cache/a').write_bytes(b'user mutation')
        other = self.root / 'other'
        self.run_cli('artifact', 'get-files', 'files-test', 'one', other)
        self.assertEqual((other / 'cache/a').read_bytes(), b'first')
        self.run_cli('artifact', 'head', 'files-test', 'one', expected=3)
        source = self.root / 'single'
        source.write_bytes(b'legacy single file')
        self.run_cli('artifact', 'put', 'files-test', 'one', source)
        self.run_cli('artifact', 'head', 'files-test', 'one')
        self.run_cli('artifact', 'head-files', 'files-test', 'one')
        self.run_cli('artifact', 'head-files', 'other-namespace', 'one', expected=3)

    def test_missing_corrupt_blobs_and_seal_never_create_destination(self):
        for case in ('missing', 'corrupt', 'seal'):
            with self.subTest(case=case):
                spec = self.inventory({'data': case.encode()})
                self.put(case, spec)
                path, entry = self.entry(case)
                payload = self.blob(entry['outputs'][0]['hash'])
                if case == 'missing':
                    payload.unlink()
                elif case == 'corrupt':
                    st = payload.stat()
                    payload.write_bytes(b'!' * st.st_size)
                    os.utime(payload, ns=(st.st_atime_ns, st.st_mtime_ns))
                else:
                    path.write_bytes(b'0' * 64 + path.read_bytes()[64:])
                target = self.root / ('miss-' + case)
                self.run_cli('artifact', 'get-files', 'files-test', case, target, expected=3)
                self.assertFalse(target.exists())
                self.run_cli('artifact', 'head-files', 'files-test', case, expected=3)

    def test_rejects_unsafe_inventory_without_replacing_prior_entry(self):
        good = self.inventory({'safe': b'owned'})
        self.put('stable', good)
        bad_names = ('../escape', '/absolute', 'C:stream', 'a\\b', 'a//b', 'a/./b',
                     'a/../b', 'name.', 'name ', 'NUL', 'COM1.txt', 'CONIN$', 'caf\u00e9', 'tab\tname')
        for name in bad_names:
            with self.subTest(name=name):
                self.put('stable', self.inventory({name: b'bad'}), expected=1)
        for files, dirs in (({'a': b'x'}, ['a']), ({'A': b'x', 'a': b'y'}, []),
                            ({'a/b': b'x'}, []), ({'foo/x': b'x'}, ['Foo']), ({}, ['a', 'a'])):
            self.put('stable', self.inventory(files, dirs), expected=1)
        self.put('stable', good, 'not JSON', expected=1)
        self.put('stable', good, '"' + 'x' * 8192 + '"', expected=1)
        target = self.root / 'safe-restore'
        self.run_cli('artifact', 'get-files', 'files-test', 'stable', target)
        self.assertEqual((target / 'safe').read_bytes(), b'owned')
        self.assertFalse((self.root / 'escape').exists())

    def test_sources_and_existing_destinations_are_protected(self):
        spec = self.inventory({'data': b'original'})
        source = Path(json.loads(spec.read_text())['files'][0]['source'])
        link = self.root / 'link'
        link.symlink_to(source)
        bad = json.loads(spec.read_text())
        bad['files'][0]['source'] = str(link)
        linked = self.root / 'linked.json'
        linked.write_text(json.dumps(bad))
        self.put('linked', linked, expected=1)
        self.put('source', spec)
        target = self.root / 'live'
        target.mkdir()
        (target / 'user').write_text('keep')
        self.run_cli('artifact', 'get-files', 'files-test', 'source', target, expected=1)
        self.assertEqual((target / 'user').read_text(), 'keep')
        self.assertEqual(source.read_bytes(), b'original')
        huge = self.root / 'huge'
        with huge.open('wb') as stream:
            stream.truncate(1024 * 1024 * 1024 + 1)
        bad['files'][0]['source'] = str(huge)
        linked.write_text(json.dumps(bad))
        self.put('source', linked, expected=1)
        self.run_cli('artifact', 'head-files', 'files-test', 'source')

    def test_shared_files_keep_three_snapshots_inside_same_budget(self):
        self.env['NANOCOMPILE_MAX_SIZE'] = '40000'
        shared = b's' * 24000
        for index in range(3):
            spec = self.inventory({'shared': shared, 'version': bytes([index]) * 2000})
            self.put(str(index), spec)
        for index in range(3):
            self.run_cli('artifact', 'head-files', 'files-test', str(index))
        managed = sum(p.stat().st_size for folder in ('entries', 'blobs')
                      for p in (self.cache / folder).rglob('*') if p.is_file())
        self.assertLessEqual(managed, 40000)
        self.assertEqual(sum(p.stat().st_size == 24000 for p in (self.cache / 'blobs').rglob('*') if p.is_file()), 1)
        # Eviction still uses ordinary output references, including shared blobs.
        self.env['NANOCOMPILE_MAX_SIZE'] = '27000'
        p = subprocess.run([str(BINARY), 'stats'], env=self.env, capture_output=True)
        self.assertEqual(p.returncode, 0)
        managed = sum(p.stat().st_size for folder in ('entries', 'blobs')
                      for p in (self.cache / folder).rglob('*') if p.is_file())
        self.assertLessEqual(managed, 27000)
        self.run_cli('artifact', 'head-files', 'files-test', '2')

    def test_concurrent_snapshots_and_empty_directories(self):
        spec = self.inventory({'cache/data': b'concurrent bytes'}, ['cache'])
        def job(index):
            for _ in range(3):
                self.put(str(index), spec)
                self.run_cli('artifact', 'head-files', 'files-test', str(index))
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(job, range(4)))
        empty = self.inventory({}, ['empty', 'empty/nested'])
        self.put('empty', empty)
        target = self.root / 'empty-target'
        self.run_cli('artifact', 'get-files', 'files-test', 'empty', target)
        self.assertTrue((target / 'empty/nested').is_dir())


if __name__ == '__main__':
    unittest.main()
