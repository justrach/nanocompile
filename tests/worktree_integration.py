#!/usr/bin/env python3
"""Real Next.js worktrees and compiler seeds through the native CLI.

Run: python3 tests/worktree_integration.py zig-out/bin/nanocompile [--opennext] [--turbopack]
Requires Git, npm, Node >=20.9, and registry access for the initial installs.
--turbopack uses Next's default engine and opts into native compiler snapshots.
--opennext also packages with @opennextjs/aws locally; nothing is deployed.
All repositories, installs, outputs and caches live in an isolated .tmp fixture.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = 'WORKTREE_ORIGINAL_72b8'
CHANGED = 'WORKTREE_CHANGED_19a3'
DIRTY = 'WORKTREE_DIRTY_NOT_COMMITTED_53c1'

# Run before either framework, including before OpenNext creates .open-next.
# A warm build must see a compiler seed, but no generated output/fetch-cache.
CHECK_SEED = """const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
function files(dir) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, {withFileTypes: true}).flatMap(entry => {
    const name = path.join(dir, entry.name);
    return entry.isDirectory() ? files(name) : [name];
  });
}
if (fs.existsSync('.fixture-expect-seed')) {
  if (fs.existsSync('.fixture-turbopack')) {
    const engines = fs.readdirSync('.next/cache/turbopack');
    assert.equal(engines.length, 1, 'expected one exact native engine snapshot');
    assert.equal(engines[0], fs.readFileSync('.fixture-expect-seed', 'utf8').trim());
    const engine = path.join('.next/cache/turbopack', engines[0]);
    const current = fs.readFileSync(path.join(engine, 'CURRENT'));
    assert(current.length > 0 && current.length <= 64 * 1024, 'invalid CURRENT size');
    assert.equal(typeof JSON.parse(current).commit_time, 'string');
    assert(files(engine).some(name => path.basename(name) !== 'CURRENT'),
           'native Turbopack payload missing before Next');
  } else {
    assert(files('.next/cache/webpack').length > 0, 'compiler seed missing before Next');
  }
  for (const name of ['.next/cache/fetch-cache', '.next/server', '.open-next']) {
    assert(!fs.existsSync(name), 'non-compiler output restored: ' + name);
  }
  fs.unlinkSync('.fixture-expect-seed');
}
"""

RECORD_BUILD = """const fs = require('node:fs');
const path = require('node:path');
fs.appendFileSync('.fixture-builds', 'build\\n');
for (const dir of ['.next/cache/fetch-cache', '.next/server', '.open-next']) {
  fs.mkdirSync(dir, {recursive: true});
  fs.writeFileSync(path.join(dir, 'fixture-not-shared'), 'private worktree output');
}
"""


def page(marker):
    return ("import dependency from './dependency';\n"
            'export default function Page() { return <main>' + marker
            + '<span>{dependency}</span><span>{process.env.WORKTREE_FIXTURE_VARIANT}</span>'
            + '</main>; }\n')


def fixture(project, opennext, turbopack=False):
    project.mkdir()
    (project / 'app').mkdir()
    package = {
        'name': 'nanocompile-worktree-fixture', 'version': '1.0.0', 'private': True,
        'scripts': {
            'build': 'node check-seed.cjs && node record-build.cjs && next build'
                     + ('' if turbopack else ' --webpack'),
            'dev': 'next dev --webpack --hostname 127.0.0.1',
            'probe': 'node probe.cjs',
        },
        'dependencies': {'next': '16.4.1', 'react': '19.2.0', 'react-dom': '19.2.0'},
    }
    if opennext:
        package['devDependencies'] = {'@opennextjs/aws': '4.1.12'}
        package['scripts']['open-next'] = 'node check-seed.cjs && open-next build'
        # OpenNext bundles this configuration itself; no TypeScript app or
        # generated tsconfig/next-env input changes are needed.
        (project / 'open-next.config.ts').write_text('export default { default: {} };\n')
    (project / 'package.json').write_text(json.dumps(package, indent=2) + '\n')
    (project / '.gitignore').write_text(
        'node_modules/\n.next/\n.open-next/\n.env*\n.fixture-*\n')
    (project / 'next.config.js').write_text(
        'module.exports = { experimental: { cpus: 1, workerThreads: false } };\n')
    (project / 'app/layout.js').write_text(
        'export default function Layout({ children }) {\n'
        '  return <html lang="en"><body>{children}</body></html>;\n}\n')
    (project / 'app/page.js').write_text(page(ORIGINAL))
    (project / 'app/dependency.js').write_text("export default 'DEPENDENCY_" + ORIGINAL + "';\n")
    if turbopack:
        (project / '.fixture-turbopack').write_text('native snapshots enabled\n')
    (project / 'check-seed.cjs').write_text(CHECK_SEED)
    (project / 'record-build.cjs').write_text(RECORD_BUILD)
    (project / 'probe.cjs').write_text(
        "const fs = require('node:fs');\n"
        "require('node:assert/strict').deepEqual(process.argv.slice(2), ['forwarded']);\n"
        "fs.appendFileSync('.fixture-probes', 'probe\\n');\n")


def run(command, cwd, env, timeout=900):
    result = subprocess.run([str(arg) for arg in command], cwd=cwd, env=env,
                            capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, (
        'Command failed: ' + ' '.join(str(arg) for arg in command) + '\n'
        + result.stdout + result.stderr)
    return result.stdout


def summary(binary, cache, arguments, cwd, env):
    output = run([binary, 'worktree', '--cache', cache, *arguments], cwd, env)
    lines = output.rstrip().splitlines()
    assert lines, 'CLI did not print a summary'
    try:
        value = json.loads(lines[-1])
    except ValueError:
        raise AssertionError('Last stdout line is not JSON:\n' + output) from None
    assert isinstance(value, dict), value
    return value


def assert_setup(value, project, install):
    assert value['project'] == str(project), value
    assert value['manager'] == 'npm', value
    assert value['install'] == install, value


def assert_build(value, state):
    assert value['returncode'] == 0, value
    assert value['cache'] == state, value
    assert value['stored'] is True, value
    assert isinstance(value['key'], str) and len(value['key']) == 64, value


def regular_nodes(directory):
    """Reject dependencies/outputs linked outside their owning tree."""
    assert directory.is_dir() and not directory.is_symlink(), directory
    nodes = set()
    for root, directories, files in os.walk(directory, followlinks=False):
        for name in directories + files:
            path = Path(root) / name
            if path.is_symlink():
                assert directory in path.resolve().parents, path
            elif path.is_file():
                stat = path.stat()
                nodes.add((stat.st_dev, stat.st_ino))
    assert nodes, 'No files in ' + str(directory)
    return nodes


def assert_private(first, second, directory):
    assert regular_nodes(first / directory).isdisjoint(regular_nodes(second / directory)), (
        'Shared hardlinked files in ' + directory)


def assert_output(project, marker, stale, opennext=False):
    output = project / '.next/server/app/index.html'
    assert output.is_file(), 'Missing prerendered Next page'
    html = output.read_text()
    assert marker in html and stale not in html and DIRTY not in html, html
    assert 'DEPENDENCY_' + marker in html, 'Imported source dependency is stale'
    if opennext:
        # AWS packages prerendered pages as JSON cache assets, not .html files.
        pages = list((project / '.open-next/cache').rglob('*.cache'))
        assert pages, 'Missing packaged OpenNext pages'
        packaged_html = [json.loads(p.read_text()).get('html', '') for p in pages]
        assert any(marker in text for text in packaged_html), 'Packaged marker missing'
        assert all(stale not in text and DIRTY not in text for text in packaged_html)
    return html


def build_pair(binary, cache, first, second, root, env, opennext=False, turbopack=False):
    """Cold store then restore into a different tree with different source."""
    options = ['--script', 'open-next'] if opennext else []
    if turbopack:
        options.append('--turbopack-cache')
    for project in (first, second):
        for directory in ('.next', '.open-next'):
            shutil.rmtree(project / directory, ignore_errors=True)
    (second / '.fixture-expect-seed').write_text('require real seed before Next\n')
    before = [len((p / '.fixture-builds').read_text().splitlines())
              if (p / '.fixture-builds').exists() else 0 for p in (first, second)]
    cold = summary(binary, cache, ['build', '--project', first, *options], root, env)
    assert_build(cold, 'miss')
    original = assert_output(first, ORIGINAL, CHANGED, opennext)
    if turbopack:
        assert cold.get('turbopack_cache', '').startswith('v'), cold
        (second / '.fixture-expect-seed').write_text(cold['turbopack_cache'] + '\n')
    warm = summary(binary, cache, ['build', '--project', second, *options], root, env)
    assert_build(warm, 'restored')
    assert cold['key'] == warm['key'], (cold, warm)
    if turbopack:
        assert warm.get('turbopack_cache') == cold['turbopack_cache'], (cold, warm)
    assert_output(second, CHANGED, ORIGINAL, opennext)
    assert (first / '.next/server/app/index.html').read_text() == original
    for index, project in enumerate((first, second)):
        assert len((project / '.fixture-builds').read_text().splitlines()) == before[index] + 1, (
            'Cache hit must still execute the real framework build')
    assert_private(first, second, '.next')
    if opennext:
        assert_private(first, second, '.open-next')
    assert not (second / '.fixture-expect-seed').exists(), 'Pre-build seed check did not run'
    print('PASS: ' + ('OpenNext packaging' if opennext else 'Next Turbopack' if turbopack else 'Next webpack')
          + ' cold store, cross-worktree seed restore, current-source outputs', flush=True)
    return warm


def invalidation(binary, cache, project, root, env, turbopack=False):
    # A tiny real npm script exercises key changes without extra Next builds.
    arguments = ['build', '--project', project, '--script', 'probe']
    if turbopack:
        arguments.append('--turbopack-cache')
    arguments += ['--', 'forwarded']
    baseline = summary(binary, cache, arguments, root, env)
    changed_env = summary(binary, cache, arguments, root,
                          dict(env, WORKTREE_FIXTURE_VARIANT='changed'))
    config = project / 'next.config.js'
    original = config.read_text()
    try:
        config.write_text(original + '// compatibility input changed\n')
        changed_config = summary(binary, cache, arguments, root, env)
    finally:
        config.write_text(original)
    for value in (baseline, changed_env, changed_config):
        assert_build(value, 'miss')
    assert len({v['key'] for v in (baseline, changed_env, changed_config)}) == 3
    assert (project / '.fixture-probes').read_text().splitlines() == ['probe'] * 3
    print('PASS: script/argument forwarding and environment/config invalidation', flush=True)


def dev(binary, cache, project, root, env):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    with (root / 'dev.log').open('w+') as log:
        process = subprocess.Popen(
            [binary, 'worktree', '--cache', str(cache), 'dev', '--project', str(project),
             '--port', str(port)], cwd=root, env=env, stdout=log, stderr=log,
            start_new_session=True)
        try:
            deadline = time.monotonic() + 120
            # Ignore proxy configuration even on machines with a global proxy.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            while time.monotonic() < deadline:
                assert process.poll() is None, 'Dev command exited before serving the app'
                try:
                    with opener.open('http://127.0.0.1:' + str(port), timeout=5) as response:
                        html = response.read().decode()
                    assert CHANGED in html and ORIGINAL not in html and DIRTY not in html
                    print('PASS: native dev command serves the worktree on the requested port',
                          flush=True)
                    break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.2)
            else:
                raise AssertionError('Dev server startup timeout')
        except BaseException:
            log.flush()
            log.seek(0)
            print(log.read())
            raise
        finally:
            # npm and Next are descendants; terminate the whole local group.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary')
    parser.add_argument('--opennext', action='store_true')
    parser.add_argument('--turbopack', action='store_true')
    args = parser.parse_args()
    binary = str(Path(args.binary).resolve())
    assert Path(binary).is_file(), 'Build the native nanocompile binary first'
    # This project resolves tools in its native project environment, not a
    # system temporary directory. Never create commits in the user's repository.
    temp_root = ROOT / '.tmp'
    temp_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='worktree-integration-', dir=temp_root) as temp:
        root = Path(temp).resolve()
        source, first, second, cache = (root / name for name in ('source', 'first', 'second', 'cache'))
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('NANOCOMPILE_', 'NEXT_', 'OPEN_NEXT_', 'R2_', 'TURBO_ENGINE_'))}
        env.update(NEXT_TELEMETRY_DISABLED='1', NPM_CONFIG_AUDIT='false', NPM_CONFIG_FUND='false',
                   GIT_AUTHOR_NAME='Test', GIT_AUTHOR_EMAIL='test@example.invalid',
                   GIT_COMMITTER_NAME='Test', GIT_COMMITTER_EMAIL='test@example.invalid')
        fixture(source, args.opennext, args.turbopack)
        run(['git', 'init', '-q', source], root, env)
        run(['git', 'config', 'user.name', 'Test'], source, env)
        run(['git', 'config', 'user.email', 'test@example.invalid'], source, env)
        # A normal install creates the lockfile. CLI creates/prepares must use
        # the real frozen npm ci installer and share downloads, not node_modules.
        run(['npm', 'install', '--cache', cache / 'downloads/npm'], source, env)
        run(['git', 'add', '.'], source, env)
        run(['git', '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture'], source, env)
        (source / 'app/page.js').write_text(page(DIRTY))
        (source / '.env').write_text('FIXTURE_LOCAL_ONLY=not-copied\n')
        created = summary(binary, cache,
                          ['create', first, '--project', source, '--branch', 'fixture-first'], root, env)
        assert_setup(created, first, 'installed')
        skipped = summary(binary, cache,
                          ['create', second, '--project', source, '--branch', 'fixture-second',
                           '--ref', 'HEAD', '--no-install'], root, env)
        assert_setup(skipped, second, 'skipped')
        assert not (second / 'node_modules').exists(), '--no-install installed dependencies'
        prepared = summary(binary, cache, ['prepare', '--project', second], root, env)
        assert_setup(prepared, second, 'installed')
        for project in (first, second):
            assert (project / '.git').is_file(), 'Expected a real linked Git worktree'
            assert (project / 'app/page.js').read_text() == page(ORIGINAL)
            assert not (project / '.env').exists(), 'Ignored environment file was copied'
            assert not (project / '.next').exists(), 'Generated output was copied'
        for project in (first, second):
            assert_private(source, project, 'node_modules')
        assert_private(first, second, 'node_modules')
        assert any(p.is_file() for p in (cache / 'downloads/npm/_cacache').rglob('*')), 'No npm download cache'
        (second / 'app/page.js').write_text(page(CHANGED))
        (second / 'app/dependency.js').write_text("export default 'DEPENDENCY_" + CHANGED + "';\n")
        if args.turbopack:
            # Ignored fixture control files are deliberately not copied by Git.
            for project in (first, second):
                (project / '.fixture-turbopack').write_text('native snapshots enabled\n')
        print('PASS: real Git worktrees, frozen installs, private dependencies and uncopied dirty/env files',
              flush=True)
        warm = build_pair(binary, cache, first, second, root, env, turbopack=args.turbopack)
        if args.opennext:
            build_pair(binary, cache, first, second, root, env, opennext=True,
                       turbopack=args.turbopack)
        if args.turbopack:
            # One extra real build checks an environment value consumed by Next.
            for directory in ('.next', '.open-next'):
                shutil.rmtree(second / directory, ignore_errors=True)
            changed_env = summary(binary, cache,
                                  ['build', '--project', second, '--turbopack-cache'], root,
                                  dict(env, WORKTREE_FIXTURE_VARIANT='ENV_CHANGED_91e2'))
            assert_build(changed_env, 'miss')
            assert changed_env['key'] != warm['key'], (warm, changed_env)
            assert 'ENV_CHANGED_91e2' in assert_output(second, CHANGED, ORIGINAL)
            print('PASS: Turbopack real-page environment invalidation', flush=True)
        invalidation(binary, cache, second, root, env, turbopack=args.turbopack)
        dev(binary, cache, second, root, env)
        assert (source / 'app/page.js').read_text() == page(DIRTY)
        assert (source / '.env').read_text() == 'FIXTURE_LOCAL_ONLY=not-copied\n'
        assert not (source / '.next').exists()
        print('PASS: worktree CLI integration' + (' including OpenNext AWS packaging' if args.opennext else ''),
              flush=True)


if __name__ == '__main__':
    main()
