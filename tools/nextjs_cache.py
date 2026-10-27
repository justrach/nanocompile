"""Relocatable Next.js compiler-cache hints, not cached build results.

SWC/Webpack hints are shared by default. Opt-in Turbopack snapshots use the
installed compiler's exact engine-version directory after a completed build.
Frameworks must validate hints against source inputs on every real build; source contents
are deliberately not part of the key. No fetch-cache or remote data cache is
restored. This helper serializes its own invocations, not external dev servers.
POSIX only (flock); each Git worktree has its own private lock.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile

NAMESPACE = 'nextjs-worktree-v1'
CACHE_DIRS = ('swc', 'webpack')
MAX_BYTES = 1024 * 1024 * 1024
MAX_MEMBERS = 100000
LOCKFILES = ('package-lock.json', 'npm-shrinkwrap.json', 'yarn.lock',
             'pnpm-lock.yaml', 'bun.lock', 'bun.lockb')
CONFIGS = ('next.config.*', 'open-next.config.*', 'wrangler.*', 'tsconfig.*',
           'jsconfig.*', '.npmrc', '.yarnrc*', 'pnpm-workspace.yaml',
           'babel.config.*', '.babelrc*', 'postcss.config.*', 'tailwind.config.*',
           '.env*')


def _digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _environment(env):
    return dict(os.environ if env is None else env)


def _identity(name, project, env, required=False):
    path = shutil.which(name, path=env.get('PATH', os.defpath))
    if path is None:
        if required:
            raise ValueError('runtime unavailable')
        return None
    path = Path(path).resolve()
    result = subprocess.run([str(path), '--version'], cwd=project, env=env,
                            capture_output=True, timeout=15, check=True)
    return [_digest(path), hashlib.sha256(result.stdout).hexdigest()]


def _turbopack_version(project, env):
    # Follow Next's own worktree seeder: version is the framework version AND
    # native compiler build, not merely the package.json semver. Unknown/wasm
    # runtimes and custom engine-directory overrides fall back to normal builds.
    if any(env.get(name) for name in ('TURBO_ENGINE_VERSION',
                                      'TURBO_ENGINE_DISABLE_VERSIONING',
                                      'TURBO_ENGINE_IGNORE_DIRTY')):
        return None
    node = shutil.which('node', path=env.get('PATH', os.defpath))
    if node is None:
        return None
    probe = '''const {createRequire} = require('node:module');
const load = createRequire(process.cwd() + '/package.json');
(async () => {
  const swc = load('next/dist/build/swc');
  await swc.loadBindings();
  const version = swc.getTurbopackCacheVersion?.();
  if (typeof version !== 'string') process.exit(1);
  process.stdout.write(version);
})().catch(() => process.exit(1));'''
    result = subprocess.run([node, '-e', probe], cwd=project, env=env,
                            capture_output=True, text=True, check=True, timeout=15)
    version = result.stdout.strip()
    if not re.fullmatch(r'v[0-9][A-Za-z0-9._-]{0,126}', version):
        return None
    return version


def _key(project, command, dist_dir, env, turbopack_version=None):
    locks = [project / name for name in LOCKFILES if (project / name).is_file()]
    if not locks or not (project / 'package.json').is_file():
        raise ValueError('dependency lockfile and package.json required')
    files = set(locks + [project / 'package.json'])
    for pattern in CONFIGS:
        files.update(project.glob(pattern))
    inputs = {}
    for path in sorted(files):
        if not path.is_file():
            raise ValueError('configuration is not a file')
        inputs[path.name] = _digest(path)
    # Hash values only inside the final digest; never log or persist raw env.
    effective = {k: v for k, v in env.items()
                 if k not in ('PWD', 'OLDPWD', 'NANOCOMPILE_DIR')
                 and not (k.startswith('NANOCOMPILE_') and k.endswith('_REPORT'))}
    managers = {'package-lock.json': 'npm', 'npm-shrinkwrap.json': 'npm',
                'pnpm-lock.yaml': 'pnpm', 'yarn.lock': 'yarn',
                'bun.lock': 'bun', 'bun.lockb': 'bun'}
    # Never invoke unrelated manager shims: Corepack can try to download tools.
    selected = sorted({managers[path.name] for path in locks})
    data = {'schema': NAMESPACE, 'os': platform.system(),
            'arch': platform.machine(), 'node': _identity('node', project, env, True),
            'managers': {name: _identity(name, project, env) for name in selected},
            'inputs': inputs, 'env': effective, 'dist': dist_dir,
            'command': list(command)}
    if turbopack_version is not None:
        data['turbopack_version'] = turbopack_version
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _targets(project, dist_dir, cache_dirs=CACHE_DIRS):
    path = PurePosixPath(dist_dir)
    if (not dist_dir or path.is_absolute() or PureWindowsPath(dist_dir).is_absolute()
            or '\\' in dist_dir or '..' in path.parts or str(path) == '.'):
        raise ValueError('unsafe dist_dir')
    targets = [project / path / 'cache' / name for name in cache_dirs]
    for target in targets:
        current = project
        for part in target.relative_to(project).parts:
            current = current / part
            # Reject even in-project symlinks: caches are mutable directories.
            if current.is_symlink():
                raise ValueError('symlink in compiler cache path')
            if current.exists() and not current.is_dir():
                raise ValueError('compiler cache path is not a directory')
    return targets


@contextmanager
def _worktree_lock(project):
    if os.name != 'posix':
        raise RuntimeError('Next.js worktree cache requires POSIX flock')
    import fcntl
    result = subprocess.run(['git', 'rev-parse', '--git-path', 'nanocompile-nextjs.lock'],
                            cwd=project, capture_output=True, check=True)
    lock = Path(os.fsdecode(result.stdout).strip())
    if not lock.is_absolute():
        lock = project / lock
    with lock.open('a+b') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _artifact(binary, op, key, archive, cache_root, env):
    backend_env = dict(env, NANOCOMPILE_DIR=str(cache_root))
    # Zig's get verifies the CAS payload before returning success.
    return subprocess.run([binary, 'artifact', op, NAMESPACE, key, str(archive)],
                          env=backend_env, capture_output=True, timeout=120).returncode == 0


def _validate_turbopack_snapshot(target):
    current = target / 'CURRENT'
    if current.is_symlink() or not current.is_file():
        raise ValueError('incomplete Turbopack snapshot')
    # CURRENT is tiny metadata, never read an unbounded compiler payload as JSON.
    with current.open('rb') as source:
        data = source.read(64 * 1024 + 1)
    if len(data) > 64 * 1024:
        raise ValueError('oversized Turbopack snapshot metadata')
    state = json.loads(data)
    if not isinstance(state, dict) or not isinstance(state.get('commit_time'), str):
        raise ValueError('incomplete Turbopack snapshot')


def _restore(archive, project, dist_dir, cache_dirs=CACHE_DIRS):
    targets = _targets(project, dist_dir, cache_dirs)
    if any(target.exists() for target in targets):
        return False
    if archive.stat().st_size > MAX_BYTES:
        raise ValueError('archive size limit')
    with tempfile.TemporaryDirectory(prefix='.nextjs-seed-', dir=project) as temp:
        stage = Path(temp)
        with tarfile.open(archive, 'r:') as tar:
            members, seen, total = [], set(), 0
            for member in tar:
                name = PurePosixPath(member.name)
                allowed = any(name == PurePosixPath(root) or PurePosixPath(root) in name.parents
                              for root in cache_dirs)
                if (not name.parts or not allowed
                        or member.name != name.as_posix() or name.is_absolute()
                        or '..' in name.parts or '\\' in member.name
                        or not (member.isdir() or member.isreg())
                        or member.name in seen or member.size < 0
                        or (any(name == PurePosixPath(root) for root in cache_dirs)
                            and not member.isdir())):
                    raise ValueError('unsafe compiler cache archive')
                seen.add(member.name)
                total += member.size
                if total > MAX_BYTES or len(seen) > MAX_MEMBERS:
                    raise ValueError('archive expansion limit')
                members.append(member)
            # Validate the entire archive before writing anything, never extractall.
            for member in members:
                destination = stage / member.name
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(member) as source, destination.open('xb') as output:
                        shutil.copyfileobj(source, output, 64 * 1024)
        for name in cache_dirs:
            if name.startswith('turbopack/') and (stage / name).exists():
                _validate_turbopack_snapshot(stage / name)
        targets = _targets(project, dist_dir, cache_dirs)
        if any(target.exists() for target in targets):
            return False
        restored = False
        for name, target in zip(cache_dirs, targets):
            if (stage / name).is_dir():
                target.parent.mkdir(parents=True, exist_ok=True)
                # Stage resides on the project filesystem. Only absent targets
                # are published; no live cache directory is removed or merged.
                if target.exists():
                    raise ValueError('compiler cache appeared during restore')
                os.rename(stage / name, target)
                restored = True
        return restored


def _store_archive(archive, targets, cache_dirs=CACHE_DIRS):
    total, count = 0, 0
    with tarfile.open(archive, 'w:', format=tarfile.USTAR_FORMAT, copybufsize=1024*1024) as tar:
        for name, target in zip(cache_dirs, targets):
            if not target.exists():
                continue
            if name.startswith('turbopack/'):
                _validate_turbopack_snapshot(target)
            for root, dirs, files in os.walk(target, followlinks=False):
                dirs.sort()
                files.sort()
                for path in [Path(root)] + [Path(root) / p for p in dirs + files]:
                    node = path.lstat()
                    if (not (stat.S_ISDIR(node.st_mode) or stat.S_ISREG(node.st_mode))
                            or (stat.S_ISREG(node.st_mode) and node.st_nlink != 1)):
                        raise ValueError('unsafe compiler cache node')
                # Add each directory once; tar.add must not recurse into links.
                for path in [Path(root)] + [Path(root) / p for p in files]:
                    info = tar.gettarinfo(str(path), str(Path(name) / path.relative_to(target)))
                    if not (info.isdir() or info.isreg()):
                        raise ValueError('unsafe compiler cache node')
                    total += info.size
                    count += 1
                    if total > MAX_BYTES or count > MAX_MEMBERS:
                        raise ValueError('compiler cache size limit')
                    info.uid = info.gid = 0
                    info.uname = info.gname = ''
                    info.mtime = 0
                    info.mode = 0o755 if info.isdir() else 0o644
                    if info.isreg():
                        with path.open('rb') as source:
                            tar.addfile(info, source)
                    else:
                        tar.addfile(info)
    return count > 0 and archive.stat().st_size <= MAX_BYTES


def run_build(project, command, binary, cache_root, dist_dir='.next', env=None,
              turbopack_cache=False):
    """Run argv (no shell) in project, returning returncode/cache/stored[/key].

    env is a full subprocess environment, or None to inherit os.environ.
    cache is restored, miss, or disabled. Backend/invalid archive failures are
    misses; missing compatibility inputs disable caching. Invalid dist_dir and
    unavailable Git locking are caller errors. The build's output is inherited.
    """
    project = Path(project).resolve()
    cache_root = Path(cache_root).resolve()
    binary = os.fspath(binary)
    if os.path.dirname(binary):
        binary = str(Path(binary).resolve())
    command = list(command)
    _targets(project, dist_dir)
    result = {'returncode': None, 'cache': 'disabled', 'stored': False}
    with _worktree_lock(project):
        build_env = _environment(env)
        cache_dirs = CACHE_DIRS
        version = None
        if turbopack_cache and build_env.get('NANOCOMPILE_DISABLE') != '1':
            try:
                version = _turbopack_version(project, build_env)
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            result['turbopack_cache'] = version or 'unavailable'
            if version is not None:
                cache_dirs += ('turbopack/' + version,)
                _targets(project, dist_dir, cache_dirs)
        key = None
        if build_env.get('NANOCOMPILE_DISABLE') != '1':
            try:
                key = _key(project, command, dist_dir, build_env, version)
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        with tempfile.TemporaryDirectory(prefix='nextjs-artifact-') as temp:
            archive = Path(temp) / 'compiler.tar'
            if key is not None:
                result.update(cache='miss', key=key)
                try:
                    if (not any(p.exists() for p in _targets(project, dist_dir, cache_dirs))
                            and _artifact(binary, 'get', key, archive, cache_root, build_env)
                            and _restore(archive, project, dist_dir, cache_dirs)):
                        result['cache'] = 'restored'
                except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError):
                    pass
            result['returncode'] = subprocess.run(command, cwd=project, env=build_env).returncode
            if key is not None and result['returncode'] == 0:
                try:
                    # Re-read inputs after the build: changed compatibility inputs
                    # must never poison the pre-build key.
                    after_env = _environment(env)
                    after_version = _turbopack_version(project, after_env) if version is not None else None
                    if (version == after_version
                            and key == _key(project, command, dist_dir, after_env, after_version)
                            and _store_archive(archive, _targets(project, dist_dir, cache_dirs), cache_dirs)):
                        result['stored'] = _artifact(binary, 'put', key, archive,
                                                     cache_root, build_env)
                except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError):
                    pass
    return result
