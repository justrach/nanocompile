#!/usr/bin/env python3
"""Worktree setup contracts; package-manager commands never access the network."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('worktree_setup', ROOT / 'tools/worktree_setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class WorktreeTests(unittest.TestCase):
    def test_real_worktree_ref_and_failures_preserve_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            repo = root / 'repo'
            repo.mkdir()

            def git(*args):
                return subprocess.run(['git', '-C', str(repo), *args], check=True,
                                      capture_output=True, text=True).stdout.strip()

            git('init')
            git('config', 'user.name', 'Test')
            git('config', 'user.email', 'test@example.invalid')
            (repo / 'file').write_text('first')
            git('add', 'file')
            git('commit', '-m', 'first')
            first = git('rev-parse', 'HEAD')
            (repo / 'file').write_text('second')
            git('commit', '-am', 'second')
            (repo / '.env').write_text('local only')
            (repo / 'node_modules').mkdir()
            target = setup.create_worktree(repo, root / 'tree', 'work', first)
            self.assertEqual(target, root / 'tree')
            self.assertEqual(setup.project_root(target), target)
            self.assertEqual((target / 'file').read_text(), 'first')
            self.assertFalse((target / '.env').exists())
            self.assertFalse((target / 'node_modules').exists())
            self.assertEqual(git('rev-parse', 'work'), first)
            (target / 'file').write_text('keep dirty')
            with self.assertRaises(subprocess.CalledProcessError):
                setup.create_worktree(repo, target, 'other')
            self.assertEqual((target / 'file').read_text(), 'keep dirty')
            occupied = root / 'occupied'
            occupied.mkdir()
            (occupied / 'keep').write_text('preserve')
            with self.assertRaises(subprocess.CalledProcessError):
                setup.create_worktree(repo, occupied, 'occupied')
            self.assertEqual((occupied / 'keep').read_text(), 'preserve')
            with self.assertRaises(subprocess.CalledProcessError):
                setup.create_worktree(repo, root / 'missing', 'bad', 'no-such-ref')
            self.assertEqual((repo / '.env').read_text(), 'local only')
            self.assertEqual((repo / 'file').read_text(), 'second')
            with self.assertRaises(subprocess.CalledProcessError):
                setup.project_root(root)


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / 'project'
        self.project.mkdir()
        self.cache = self.root / 'shared'
        self.package()

    def package(self, manager=None):
        data = {} if manager is None else {'packageManager': manager}
        (self.project / 'package.json').write_text(json.dumps(data))

    def lock(self, name):
        for existing in setup.LOCKFILES:
            (self.project / existing).unlink(missing_ok=True)
        (self.project / name).touch()

    def test_selection_and_script_arguments(self):
        for lock, manager in setup.LOCKFILES.items():
            with self.subTest(lock=lock):
                self.lock(lock)
                self.package(manager + '@1.2.3')
                with mock.patch.object(setup.shutil, 'which', return_value='/bin/' + manager):
                    expected = ['/bin/' + manager, 'run', 'build']
                    if manager == 'npm':
                        expected.append('--')
                    self.assertEqual(setup.script_command(self.project, 'build', ['--debug']),
                                     expected + ['--debug'])

    def test_missing_conflicting_and_mismatched_lockfiles(self):
        with self.assertRaisesRegex(ValueError, 'lockfile is required'):
            setup.prepare(self.project, self.cache, install=False)
        self.lock('package-lock.json')
        (self.project / 'yarn.lock').touch()
        with self.assertRaisesRegex(ValueError, 'conflicting lockfiles'):
            setup.prepare(self.project, self.cache, install=False)
        self.lock('bun.lock')
        (self.project / 'bun.lockb').touch()
        with self.assertRaisesRegex(ValueError, 'conflicting lockfiles'):
            setup.prepare(self.project, self.cache, install=False)
        self.lock('package-lock.json')
        self.package('pnpm@9.0.0')
        with self.assertRaisesRegex(ValueError, 'does not match'):
            setup.prepare(self.project, self.cache, install=False)
        self.package('unsupported')
        with self.assertRaisesRegex(ValueError, 'unsupported packageManager'):
            setup.prepare(self.project, self.cache, install=False)

    def test_frozen_installs_and_download_caches(self):
        cases = [('package-lock.json', 'npm', ['ci', '--cache'], None),
                 ('pnpm-lock.yaml', 'pnpm', ['install', '--frozen-lockfile', '--store-dir'], None),
                 ('yarn.lock', 'yarn', ['install', '--frozen-lockfile'], '1.22.22'),
                 ('yarn.lock', 'yarn', ['install', '--immutable'], '4.5.0'),
                 ('bun.lock', 'bun', ['install', '--frozen-lockfile'], None),
                 ('bun.lockb', 'bun', ['install', '--frozen-lockfile'], None)]
        for lock, manager, args, version in cases:
            with self.subTest(lock=lock, version=version):
                self.lock(lock)
                cache = str(self.cache / manager)
                expected = ['/bin/' + manager, *args]
                if manager in ('npm', 'pnpm'):
                    expected.append(cache)
                with mock.patch.object(setup.shutil, 'which', return_value='/bin/' + manager), \
                        mock.patch.object(setup.subprocess, 'run') as run:
                    run.return_value.stdout = version
                    result = setup.prepare(self.project, self.cache)
                    self.assertEqual(result, {'project': str(self.project), 'manager': manager,
                                              'install': 'installed'})
                    self.assertEqual(run.call_args.args[0], expected)
                    self.assertEqual(run.call_args.kwargs['cwd'], self.project)
                    self.assertTrue(run.call_args.kwargs['check'])
                    env = run.call_args.kwargs['env']
                    if manager == 'bun':
                        self.assertEqual(env['BUN_INSTALL_CACHE_DIR'], cache)
                    if manager == 'yarn':
                        self.assertEqual(env['YARN_CACHE_FOLDER'], cache)
                        if version.startswith('4'):
                            self.assertEqual(env['YARN_ENABLE_GLOBAL_CACHE'], 'false')
                            self.assertEqual(env['YARN_NODE_LINKER'], 'node-modules')
                        self.assertEqual(run.call_args_list[0].args[0], ['/bin/yarn', '--version'])
                    before = run.call_count
                    (self.project / 'node_modules').mkdir(exist_ok=True)
                    setup.prepare(self.project, self.cache)
                    self.assertEqual(run.call_count - before, 2 if version else 1)

    def test_no_install_needs_no_executable_or_cache(self):
        self.lock('package-lock.json')
        with mock.patch.object(setup.shutil, 'which') as which, \
                mock.patch.object(setup.subprocess, 'run') as run:
            self.assertEqual(setup.prepare(self.project, self.cache, install=False)['install'],
                             'skipped')
            which.assert_not_called()
            run.assert_not_called()
        self.assertFalse(self.cache.exists())

    def test_missing_executable_and_failed_installer(self):
        self.lock('package-lock.json')
        with mock.patch.object(setup.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(ValueError, 'executable not found: npm'):
                setup.prepare(self.project, self.cache)
            with self.assertRaisesRegex(ValueError, 'executable not found: npm'):
                setup.script_command(self.project, 'build')
        (self.project / 'keep').write_text('untouched')
        with mock.patch.object(setup.shutil, 'which', return_value='/bin/npm'), \
                mock.patch.object(setup.subprocess, 'run',
                                  side_effect=subprocess.CalledProcessError(1, 'npm')):
            with self.assertRaises(subprocess.CalledProcessError):
                setup.prepare(self.project, self.cache)
        self.assertEqual((self.project / 'keep').read_text(), 'untouched')

    def test_unknown_yarn_version_fails_before_install(self):
        self.lock('yarn.lock')
        with mock.patch.object(setup.shutil, 'which', return_value='/bin/yarn'), \
                mock.patch.object(setup.subprocess, 'run') as run:
            run.return_value.stdout = 'unknown'
            with self.assertRaisesRegex(ValueError, 'Yarn version'):
                setup.prepare(self.project, self.cache)
            self.assertEqual(run.call_count, 1)

    @unittest.skipIf(os.name == 'nt', 'symlink privilege not assumed')
    def test_shared_node_modules_symlink_rejected(self):
        self.lock('package-lock.json')
        shared = self.root / 'shared_modules'
        shared.mkdir()
        (self.project / 'node_modules').symlink_to(shared, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'node_modules must not be a symlink'):
            setup.prepare(self.project, self.cache)
        self.assertTrue(shared.is_dir())


if __name__ == '__main__':
    unittest.main()
