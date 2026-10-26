"""Next.js compiler hints: no dependency downloads or real framework required."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import nextjs_cache as cache

BUILD = """
from pathlib import Path
import sys
p = Path('.')
count = p / 'build-count'
count.write_text(str(int(count.read_text()) + 1) if count.exists() else '1')
if (p / 'check-seed').exists():
    assert (p / '.next/cache/swc/hint').read_text() == 'seed'
for name in ('swc', 'webpack', 'fetch-cache'):
    target = p / '.next/cache' / name
    target.mkdir(parents=True, exist_ok=True)
    (target / 'hint').write_text('seed')
(p / '.next/server').mkdir(parents=True, exist_ok=True)
(p / '.next/server/output').write_text('not shared')
if (p / 'change-input').exists():
    (p / (p / 'change-input').read_text()).write_text('changed')
sys.exit(7 if (p / 'fail').exists() else 0)
"""


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for name in ('node', 'npm', 'pnpm', 'yarn', 'bun'):
            path = self.bin / name
            path.write_text('#!' + sys.executable + '\nprint("v1.0.0")\n')
            path.chmod(0o755)
        self.backend = self.bin / 'nanocompile'
        self.backend.write_text('''#!%s
import os, pathlib, shutil, sys
_, artifact, op, namespace, key, file = sys.argv
assert artifact == 'artifact' and namespace == 'nextjs-worktree-v1'
root = pathlib.Path(os.environ['NANOCOMPILE_DIR'])
root.mkdir(parents=True, exist_ok=True)
if (root / 'broken').exists():
    sys.exit(1)
p = root / key
if op == 'get':
    if not p.exists():
        sys.exit(3)
    shutil.copyfile(p, file)
else:
    shutil.copyfile(file, p)
print('{}')
''' % sys.executable)
        self.backend.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ.get('PATH', ''))
        self.env.pop('NANOCOMPILE_DISABLE', None)
        self.backend_root = self.root / 'artifacts'
        self.project = self.make_project('one')

    def make_project(self, name):
        project = self.root / name
        project.mkdir()
        subprocess.run(['git', 'init', '-q', str(project)], check=True)
        (project / 'package.json').write_text('{"dependencies":{"next":"1"}}')
        (project / 'package-lock.json').write_text('{"lockfileVersion":3}')
        (project / 'next.config.js').write_text('module.exports = {}')
        return project

    def run_build(self, project=None, **kwargs):
        return cache.run_build(project or self.project, [sys.executable, '-c', BUILD],
                               self.backend, self.backend_root,
                               env=kwargs.pop('env', self.env), **kwargs)

    def clear_local(self):
        shutil.rmtree(self.project / '.next')

    def test_relocatable_hit_always_builds_and_only_compiler_caches(self):
        first = self.run_build()
        self.assertEqual(first['cache'], 'miss')
        self.assertTrue(first['stored'])
        with tarfile.open(self.backend_root / first['key']) as tar:
            names = tar.getnames()
        self.assertEqual(set(names), {'swc', 'swc/hint', 'webpack', 'webpack/hint'})
        other = self.make_project('two')
        (other / 'check-seed').touch()
        (other / 'source.js').write_text('source is intentionally not keyed')
        env = dict(self.env, PWD=str(other), OLDPWD='/elsewhere',
                   NANOCOMPILE_DIR='/different/cache')
        second = self.run_build(other, env=env)
        self.assertEqual(first['key'], second['key'])
        self.assertEqual(second['cache'], 'restored')
        self.assertEqual((other / 'build-count').read_text(), '1')
        self.assertEqual(second['returncode'], 0)

    def test_key_invalidates_effective_inputs(self):
        command = [sys.executable, '-c', BUILD]
        key = lambda env=self.env: cache._key(self.project, command, '.next', env)
        baseline = key()
        for name in ('package-lock.json', 'package.json', 'next.config.js',
                     'open-next.config.ts', 'wrangler.toml', 'tsconfig.json', '.npmrc',
                     '.env.production'):
            with self.subTest(name=name):
                path = self.project / name
                old = path.read_bytes() if path.exists() else None
                path.write_text('different')
                self.assertNotEqual(baseline, key())
                if old is None:
                    path.unlink()
                else:
                    path.write_bytes(old)
        self.assertNotEqual(baseline, key(dict(self.env, SECRET_TOKEN='never printed')))
        self.assertNotEqual(baseline, key(dict(self.env, NODE_OPTIONS='--no-warnings')))
        self.assertNotEqual(baseline, key(dict(self.env, NANOCOMPILE_BUILD_SETTING='x')))
        self.assertEqual(baseline, key(dict(self.env, NANOCOMPILE_TASK_REPORT='/elsewhere')))
        with patch.object(cache.platform, 'machine', return_value='other-arch'):
            self.assertNotEqual(baseline, key())
        with patch.object(cache.platform, 'system', return_value='other-os'):
            self.assertNotEqual(baseline, key())
        npm = self.bin / 'npm'
        original = npm.read_text()
        npm.write_text('#!' + sys.executable + '\nprint("v9")\n')
        self.assertNotEqual(baseline, key())
        npm.write_text(original)
        (self.bin / 'node').write_text('#!' + sys.executable + '\nprint("v2")\n')
        self.assertNotEqual(baseline, key())

    def test_existing_mutable_caches_are_not_replaced(self):
        first = self.run_build()
        self.clear_local()
        existing = self.project / '.next/cache/swc'
        existing.mkdir(parents=True)
        (existing / 'live').write_text('live')
        with patch.object(cache, '_artifact', wraps=cache._artifact) as artifact:
            result = self.run_build()
        self.assertEqual(result['key'], first['key'])
        self.assertEqual(result['cache'], 'miss')
        self.assertEqual((existing / 'live').read_text(), 'live')
        self.assertEqual([call.args[1] for call in artifact.call_args_list], ['put'])

    def test_disabled_and_missing_lock_still_build(self):
        result = self.run_build(env=dict(self.env, NANOCOMPILE_DISABLE='1'))
        self.assertEqual(result, {'returncode': 0, 'cache': 'disabled', 'stored': False})
        (self.project / 'package-lock.json').unlink()
        result = self.run_build()
        self.assertEqual(result['cache'], 'disabled')
        self.assertEqual((self.project / 'build-count').read_text(), '2')
        self.assertFalse(self.backend_root.exists())

    def test_failure_never_stored_and_backend_errors_fall_back(self):
        (self.project / 'fail').touch()
        result = self.run_build()
        self.assertEqual(result['returncode'], 7)
        self.assertFalse(result['stored'])
        self.assertFalse(self.backend_root.joinpath(result['key']).exists())
        (self.project / 'fail').unlink()
        (self.backend_root / 'broken').touch()
        result = self.run_build()
        self.assertEqual(result['returncode'], 0)
        self.assertFalse(result['stored'])
        result = cache.run_build(self.project, [sys.executable, '-c', BUILD],
                                 self.bin / 'missing', self.backend_root, env=self.env)
        self.assertEqual(result['returncode'], 0)
        self.assertFalse(result['stored'])

    def test_changed_inputs_suppress_save(self):
        for name in ('package-lock.json', 'next.config.js', 'package.json'):
            with self.subTest(name=name):
                (self.project / 'change-input').write_text(name)
                result = self.run_build()
                self.assertEqual(result['returncode'], 0)
                self.assertFalse(result['stored'])
                self.assertFalse((self.backend_root / result['key']).exists())
                (self.project / name).write_text('original')

    def test_changed_environment_suppresses_save(self):
        original = cache._key
        calls = []

        def key(*args):
            value = original(*args)
            calls.append(value)
            if len(calls) == 1:
                self.env['BUILD_SETTING'] = 'changed during build'
            return value

        with patch.object(cache, '_key', side_effect=key):
            result = self.run_build()
        self.assertFalse(result['stored'])
        self.assertNotEqual(calls[0], calls[1])

    def write_archive(self, members):
        archive = self.root / 'malicious.tar'
        with tarfile.open(archive, 'w:') as tar:
            for name, kind in members:
                info = tarfile.TarInfo(name)
                info.type = kind
                if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                    info.linkname = '../../outside'
                if kind == tarfile.REGTYPE:
                    info.size = 1
                    tar.addfile(info, io.BytesIO(b'x'))
                else:
                    tar.addfile(info)
        return archive

    def test_archive_rejects_unsafe_names_links_and_nodes(self):
        for name, kind in [('../outside', tarfile.REGTYPE),
                           ('/swc/x', tarfile.REGTYPE),
                           ('swc/../../outside', tarfile.REGTYPE),
                           ('fetch-cache/x', tarfile.REGTYPE),
                           ('webpack/x', tarfile.SYMTYPE),
                           ('swc/x', tarfile.LNKTYPE), ('swc/x', tarfile.FIFOTYPE),
                           ('swc//x', tarfile.REGTYPE), ('swc\\x', tarfile.REGTYPE)]:
            with self.subTest(name=name, kind=kind):
                archive = self.write_archive([('swc/good', tarfile.REGTYPE), (name, kind)])
                with self.assertRaises(ValueError):
                    cache._restore(archive, self.project, '.next')
                self.assertFalse((self.project / '.next').exists())
        self.assertFalse((self.root / 'outside').exists())

    def test_archive_limits_and_malformed_backend_are_misses(self):
        archive = self.write_archive([('swc/x', tarfile.REGTYPE)])
        with patch.object(cache, 'MAX_BYTES', 0):
            with self.assertRaises(ValueError):
                cache._restore(archive, self.project, '.next')
        with patch.object(cache, 'MAX_MEMBERS', 0):
            with self.assertRaises(ValueError):
                cache._restore(archive, self.project, '.next')
        first = self.run_build()
        self.clear_local()
        (self.backend_root / first['key']).write_bytes(b'not a tar')
        result = self.run_build()
        self.assertEqual(result['cache'], 'miss')
        self.assertEqual(result['returncode'], 0)

    def test_no_store_symlinks_hardlinks_or_special_nodes(self):
        for kind in ('symlink', 'hardlink', 'fifo'):
            with self.subTest(kind=kind):
                if (self.project / '.next').exists():
                    self.clear_local()
                target = self.project / '.next/cache/swc'
                target.mkdir(parents=True)
                (target / 'a').write_text('content')
                if kind == 'symlink':
                    (target / 'b').symlink_to(target / 'a')
                elif kind == 'hardlink':
                    os.link(target / 'a', target / 'b')
                else:
                    os.mkfifo(target / 'b')
                result = self.run_build()
                self.assertEqual(result['returncode'], 0)
                self.assertFalse(result['stored'])

    def test_dist_dir_rejects_unsafe_paths_and_symlinks(self):
        for dist in ('/tmp/next', '../next', '.next/../../next', '.', '', 'C:\\next'):
            with self.subTest(dist=dist), self.assertRaises(ValueError):
                self.run_build(dist_dir=dist)
        (self.project / '.next').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.run_build()

    def test_custom_dist_dir_contains_only_compiler_caches(self):
        target = self.project / 'output/cache/swc'
        target.mkdir(parents=True)
        (target / 'hint').write_text('custom')
        result = self.run_build(dist_dir='output')
        self.assertTrue(result['stored'])
        shutil.rmtree(self.project / 'output')
        result = self.run_build(dist_dir='output')
        self.assertEqual(result['cache'], 'restored')
        self.assertEqual((target / 'hint').read_text(), 'custom')
        self.assertFalse((self.project / 'output/cache/fetch-cache').exists())

    def test_build_holds_worktree_lock(self):
        command = [sys.executable, '-c', '''
import fcntl
from pathlib import Path
with Path('.git/nanocompile-nextjs.lock').open('a+b') as lock:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        pass
    else:
        raise AssertionError('build did not hold the worktree lock')
''']
        result = cache.run_build(self.project, command, self.backend, self.backend_root,
                                 env=self.env)
        self.assertEqual(result['returncode'], 0)

    def test_lock_is_exclusive_and_private_to_worktree(self):
        import fcntl
        with cache._worktree_lock(self.project):
            lock = self.project / '.git/nanocompile-nextjs.lock'
            with lock.open('a+b') as other:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        subprocess.run(['git', 'add', '.'], cwd=self.project, check=True)
        subprocess.run(['git', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                        'commit', '-qm', 'fixture'], cwd=self.project, check=True)
        worktree = self.root / 'linked'
        subprocess.run(['git', 'worktree', 'add', '--detach', '-q', str(worktree)],
                       cwd=self.project, check=True)
        with cache._worktree_lock(self.project), cache._worktree_lock(worktree):
            private = subprocess.check_output(['git', 'rev-parse', '--git-path',
                                               'nanocompile-nextjs.lock'], cwd=worktree)
            self.assertNotEqual(Path(os.fsdecode(private).strip()),
                                self.project / '.git/nanocompile-nextjs.lock')


if __name__ == '__main__':
    unittest.main()
