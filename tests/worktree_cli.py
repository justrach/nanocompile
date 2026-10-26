"""Native CLI, Git worktrees and real Zig artifact-store integration; no downloads."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BINARY = None


class WorktreeCLI(unittest.TestCase):
    def setUp(self):
        (ROOT / '.tmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='worktree-cli-', dir=ROOT / '.tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.cache = self.root / 'cache'
        self.env = dict(os.environ, NEXT_TELEMETRY_DISABLED='1')
        self.env.pop('NANOCOMPILE_DISABLE', None)
        self.git('init', '-q')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        (self.repo / 'package.json').write_text(json.dumps({
            'name': 'worktree-cli-fixture', 'private': True,
            'dependencies': {'next': 'fixture-only'},
            'scripts': {'build': 'node build.cjs', 'dev': 'node dev.cjs',
                        'fail': 'node -e "process.exit(9)"'}}))
        (self.repo / 'package-lock.json').write_text('{"lockfileVersion":3}\n')
        (self.repo / '.gitignore').write_text('.next/\n.open-next/\nnode_modules/\n.env\n')
        (self.repo / 'source').write_text('committed')
        (self.repo / 'build.cjs').write_text('''const fs = require('fs');
const restored = fs.existsSync('.next/cache/webpack/hint');
fs.mkdirSync('.next/cache/webpack', {recursive:true});
fs.writeFileSync('.next/cache/webpack/hint', 'compiler hint');
fs.writeFileSync('.next/cache/fetch-cache-marker', 'not shared');
fs.mkdirSync('.next/server', {recursive:true});
fs.writeFileSync('.next/server/result', fs.readFileSync('source'));
fs.writeFileSync('.next/restored', String(restored));
''')
        (self.repo / 'dev.cjs').write_text("require('fs').writeFileSync('dev-args', JSON.stringify(process.argv.slice(2)));\n")
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def run_cli(self, *args, code=0):
        result = subprocess.run([BINARY, 'worktree', '--cache', str(self.cache), *map(str, args)],
                                env=self.env, cwd=ROOT, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def summary(self, *args, **kwargs):
        result = self.run_cli(*args, **kwargs)
        return json.loads(result.stdout.splitlines()[-1])

    def test_create_and_build_across_dirty_branches(self):
        (self.repo / 'source').write_text('dirty original stays here')
        (self.repo / '.env').write_text('PRIVATE_FIXTURE=local\n')
        trees = [self.root / 'one', self.root / 'two']
        for index, tree in enumerate(trees):
            row = self.summary('create', tree, '--project', self.repo, '--branch', 'work-' + str(index),
                               '--no-install')
            self.assertEqual(row['install'], 'skipped')
            self.assertEqual((tree / 'source').read_text(), 'committed')
            self.assertFalse((tree / '.env').exists())
            self.assertFalse((tree / 'node_modules').exists())
        first = self.summary('build', '--project', trees[0])
        self.assertEqual(first['cache'], 'miss')
        self.assertTrue(first['stored'])
        (trees[1] / 'source').write_text('edited second branch')
        second = self.summary('build', '--project', trees[1])
        self.assertEqual(first['key'], second['key'])
        self.assertEqual(second['cache'], 'restored')
        self.assertEqual((trees[1] / '.next/restored').read_text(), 'true')
        self.assertEqual((trees[1] / '.next/server/result').read_text(), 'edited second branch')
        self.assertEqual((trees[0] / '.next/server/result').read_text(), 'committed')
        self.assertEqual((self.repo / 'source').read_text(), 'dirty original stays here')
        self.assertEqual((self.repo / '.env').read_text(), 'PRIVATE_FIXTURE=local\n')
        # Existing paths are never removed, even on a failed create.
        self.run_cli('create', trees[0], '--project', self.repo, '--branch', 'new', '--no-install', code=128)
        self.assertEqual((trees[0] / '.next/server/result').read_text(), 'committed')
        failed = self.summary('build', '--project', trees[1], '--script', 'fail', code=9)
        self.assertEqual(failed['returncode'], 9)
        self.assertFalse(failed['stored'])
        self.assertEqual(self.summary('prepare', '--project', trees[1], '--no-install')['manager'], 'npm')

    def test_explicit_dev_port_and_argument_forwarding(self):
        self.run_cli('dev', '--project', self.repo, code=2)
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            port = occupied.getsockname()[1]
            self.run_cli('dev', '--project', self.repo, '--port', port, code=1)
            self.assertFalse((self.repo / 'dev-args').exists())
        self.run_cli('dev', '--project', self.repo, '--port', port, '--', '--hostname', '127.0.0.1')
        self.assertEqual(json.loads((self.repo / 'dev-args').read_text()),
                         ['--port', str(port), '--hostname', '127.0.0.1'])

    def test_unsafe_cache_location_rejects_before_running_build(self):
        self.run_cli('build', '--project', self.repo, '--dist-dir', '../outside', code=1)
        self.assertFalse((self.repo / '.next').exists())
        outside = self.root / 'outside'
        outside.mkdir()
        (self.repo / '.next').symlink_to(outside, target_is_directory=True)
        self.run_cli('build', '--project', self.repo, code=1)
        self.assertFalse(list(outside.iterdir()))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('usage: python3 tests/worktree_cli.py NANOCOMPILE_BINARY')
    BINARY = str(Path(sys.argv.pop(1)).resolve())
    unittest.main()
