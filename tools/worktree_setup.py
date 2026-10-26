#!/usr/bin/env python3
"""Git worktree and frozen Node dependency setup (Python 3.9+, no downloads of tools)."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess


LOCKFILES = {'package-lock.json': 'npm', 'pnpm-lock.yaml': 'pnpm',
             'yarn.lock': 'yarn', 'bun.lock': 'bun', 'bun.lockb': 'bun'}


def executable(name):
    found = shutil.which(name)
    if not found:
        raise ValueError('executable not found: ' + name)
    return found


def project_root(path):
    """Return the resolved Git toplevel containing path."""
    result = subprocess.run([executable('git'), '-C', str(Path(path).resolve()),
                             'rev-parse', '--show-toplevel'],
                            check=True, capture_output=True, text=True)
    return Path(result.stdout.strip()).resolve()


def create_worktree(repo, destination, branch, ref='HEAD'):
    """Create a new branch/worktree without overwriting or cleaning up anything."""
    root = project_root(repo)
    destination = Path(destination).resolve()
    if not branch or branch.startswith('-') or not ref or ref.startswith('-'):
        raise ValueError('branch and ref must not be command options')
    subprocess.run([executable('git'), '-C', str(root), 'worktree', 'add',
                    '-b', branch, '--', str(destination), ref], check=True)
    return destination


def package_manager(project):
    package = json.loads((project / 'package.json').read_text(encoding='utf-8'))
    locks = [name for name in LOCKFILES if (project / name).is_file()]
    if not locks:
        raise ValueError('a supported package-manager lockfile is required')
    if len(locks) != 1:
        raise ValueError('conflicting lockfiles: ' + ', '.join(locks))
    manager = LOCKFILES[locks[0]]
    declared = package.get('packageManager')
    if declared is not None:
        if not isinstance(declared, str) or not re.fullmatch(
                r'(npm|pnpm|yarn|bun)@\d+\.\d+\.\d+[^\s]*', declared):
            raise ValueError('unsupported packageManager: ' + str(declared))
        if declared.split('@', 1)[0] != manager:
            raise ValueError('packageManager does not match lockfile')
    return manager


def prepare(project, cache_root, install=True):
    """Return {project, manager, install: 'installed'|'skipped'} after frozen setup.

    Every installing call runs the installer. Only download caches are shared;
    no metadata, environment files, or node_modules are copied between trees.
    """
    project = Path(project).resolve()
    manager = package_manager(project)
    if (project / 'node_modules').is_symlink():
        raise ValueError('node_modules must not be a symlink')
    result = {'project': str(project), 'manager': manager, 'install': 'skipped'}
    if not install:
        return result
    command = executable(manager)
    cache = Path(cache_root).resolve() / manager
    env = os.environ.copy()
    if manager == 'npm':
        args = ['ci', '--cache', str(cache)]
    elif manager == 'pnpm':
        args = ['install', '--frozen-lockfile', '--store-dir', str(cache)]
    elif manager == 'yarn':
        version = subprocess.run([command, '--version'], cwd=project, env=env,
                                 check=True, capture_output=True, text=True).stdout.strip()
        match = re.fullmatch(r'(\d+)\.\d+\.\d+[^\s]*', version)
        if not match or int(match[1]) < 1:
            raise ValueError('cannot determine installed Yarn version')
        modern = int(match[1]) >= 2
        args = ['install', '--immutable' if modern else '--frozen-lockfile']
        env['YARN_CACHE_FOLDER'] = str(cache)
        if modern:
            env['YARN_ENABLE_GLOBAL_CACHE'] = 'false'
            env['YARN_NODE_LINKER'] = 'node-modules'
    else:
        args = ['install', '--frozen-lockfile']
        env['BUN_INSTALL_CACHE_DIR'] = str(cache)
    cache.mkdir(parents=True, exist_ok=True)
    subprocess.run([command, *args], cwd=project, env=env, check=True)
    result['install'] = 'installed'
    return result


def script_command(project, script, arguments=()):
    """Return installed-manager argv; npm needs -- to forward script arguments."""
    manager = package_manager(Path(project).resolve())
    return [executable(manager), 'run', script, *(['--'] if manager == 'npm' else []),
            *arguments]
