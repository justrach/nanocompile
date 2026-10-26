"""Relocatable Next.js compiler-cache hints, not cached build results.

Only cache/swc and cache/webpack are shared. Frameworks must validate these
incremental hints against source inputs on every real build; source contents
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


def _key(project, command, dist_dir, env):
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
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _targets(project, dist_dir):
    path = PurePosixPath(dist_dir)
    if (not dist_dir or path.is_absolute() or PureWindowsPath(dist_dir).is_absolute()
            or '\\' in dist_dir or '..' in path.parts or str(path) == '.'):
        raise ValueError('unsafe dist_dir')
    targets = [project / path / 'cache' / name for name in CACHE_DIRS]
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


def _restore(archive, project, dist_dir):
    targets = _targets(project, dist_dir)
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
                if (not name.parts or name.parts[0] not in CACHE_DIRS
                        or member.name != name.as_posix() or name.is_absolute()
                        or '..' in name.parts or '\\' in member.name
                        or not (member.isdir() or member.isreg())
                        or member.name in seen or member.size < 0
                        or (len(name.parts) == 1 and not member.isdir())):
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
        targets = _targets(project, dist_dir)
        if any(target.exists() for target in targets):
            return False
        restored = False
        for name, target in zip(CACHE_DIRS, targets):
            if (stage / name).is_dir():
                target.parent.mkdir(parents=True, exist_ok=True)
                # Stage resides on the project filesystem. Only absent targets
                # are published; no live cache directory is removed or merged.
                if target.exists():
                    raise ValueError('compiler cache appeared during restore')
                os.rename(stage / name, target)
                restored = True
        return restored


def _store_archive(archive, targets):
    total, count = 0, 0
    with tarfile.open(archive, 'w:', format=tarfile.USTAR_FORMAT) as tar:
        for name, target in zip(CACHE_DIRS, targets):
            if not target.exists():
                continue
            for root, dirs, files in os.walk(target, followlinks=False):
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
                    if info.isreg():
                        with path.open('rb') as source:
                            tar.addfile(info, source)
                    else:
                        tar.addfile(info)
    return count > 0 and archive.stat().st_size <= MAX_BYTES


def run_build(project, command, binary, cache_root, dist_dir='.next', env=None):
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
        key = None
        if build_env.get('NANOCOMPILE_DISABLE') != '1':
            try:
                key = _key(project, command, dist_dir, build_env)
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        with tempfile.TemporaryDirectory(prefix='nextjs-artifact-') as temp:
            archive = Path(temp) / 'compiler.tar'
            if key is not None:
                result.update(cache='miss', key=key)
                try:
                    if (not any(p.exists() for p in _targets(project, dist_dir))
                            and _artifact(binary, 'get', key, archive, cache_root, build_env)
                            and _restore(archive, project, dist_dir)):
                        result['cache'] = 'restored'
                except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError):
                    pass
            result['returncode'] = subprocess.run(command, cwd=project, env=build_env).returncode
            if key is not None and result['returncode'] == 0:
                try:
                    # Re-read inputs after the build: changed compatibility inputs
                    # must never poison the pre-build key.
                    if (key == _key(project, command, dist_dir, _environment(env))
                            and _store_archive(archive, _targets(project, dist_dir))):
                        result['stored'] = _artifact(binary, 'put', key, archive,
                                                     cache_root, build_env)
                except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError):
                    pass
    return result
