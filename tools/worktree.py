#!/usr/bin/env python3
"""Prepare isolated Next.js/OpenNext worktrees and reuse compiler-cache hints.

Python 3.9+, macOS/Linux. Builds always run; deployment is never skipped.
See docs/worktrees.md. Helpers share trusted local caches, not live outputs.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

import nextjs_cache
import worktree_setup


def next_project(path):
    project = Path(path).resolve(strict=True)
    worktree_setup.project_root(project)
    package = json.loads((project / 'package.json').read_text(encoding='utf-8'))
    dependencies = dict(package.get('dependencies', {}), **package.get('devDependencies', {}))
    if 'next' not in dependencies:
        raise ValueError('expected a Next.js app with next declared in package.json; '
                         'monorepo orchestration belongs to the workspace runner')
    if (project / 'node_modules').is_symlink():
        raise ValueError('node_modules must be private to this worktree, not a symlink')
    worktree_setup.package_manager(project)
    return project, package


def default_cache():
    if os.environ.get('NANOCOMPILE_DIR'):
        return Path(os.environ['NANOCOMPILE_DIR'])
    return Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache'))) / 'nanocompile'


def script(project, package, name, arguments):
    if name not in package.get('scripts', {}):
        raise ValueError('package.json has no script named ' + name)
    return worktree_setup.script_command(project, name, arguments)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--nanocompile', default=shutil.which('nanocompile'),
                        help='artifact-store executable (supplied by the native CLI)')
    result.add_argument('--cache', type=Path, default=default_cache(),
                        help='shared trusted cache directory')
    commands = result.add_subparsers(dest='operation', required=True)
    create = commands.add_parser('create', help='create a new branch/worktree and install dependencies')
    create.add_argument('destination', type=Path)
    create.add_argument('--project', type=Path, default=Path('.'))
    create.add_argument('--branch', required=True)
    create.add_argument('--ref', default='HEAD')
    create.add_argument('--no-install', action='store_true')
    prepare = commands.add_parser('prepare', help='frozen install in an existing worktree')
    prepare.add_argument('--project', type=Path, default=Path('.'))
    prepare.add_argument('--no-install', action='store_true')
    build = commands.add_parser('build', help='restore compiler hints, run a build, save fresh hints')
    build.add_argument('--project', type=Path, default=Path('.'))
    build.add_argument('--script', default='build', help='package script, e.g. build:worker for OpenNext')
    build.add_argument('--dist-dir', default='.next', help='must match your Next.js distDir configuration')
    build.add_argument('arguments', nargs=argparse.REMAINDER)
    dev = commands.add_parser('dev', help='run an isolated foreground dev server on an explicit port')
    dev.add_argument('--project', type=Path, default=Path('.'))
    dev.add_argument('--script', default='dev')
    dev.add_argument('--port', type=int, required=True)
    dev.add_argument('arguments', nargs=argparse.REMAINDER)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    if os.name != 'posix':
        raise ValueError('worktree commands currently require macOS or Linux')
    cache = args.cache.resolve()
    project, package = next_project(args.project)
    if args.operation == 'create':
        root = worktree_setup.project_root(project)
        relative = project.relative_to(root)
        destination = worktree_setup.create_worktree(root, args.destination, args.branch, args.ref)
        # Git checks out the requested commit, not ignored files or dirty edits.
        # Keep the worktree on all setup failures so no user work is discarded.
        project, _ = next_project(destination / relative)
        with nextjs_cache._worktree_lock(project):
            summary = worktree_setup.prepare(project, cache / 'downloads', not args.no_install)
    elif args.operation == 'prepare':
        with nextjs_cache._worktree_lock(project):
            summary = worktree_setup.prepare(project, cache / 'downloads', not args.no_install)
    else:
        arguments = args.arguments
        if arguments and arguments[0] == '--':
            arguments = arguments[1:]
        if args.operation == 'dev':
            if not 1 <= args.port <= 65535:
                raise ValueError('--port must be between 1 and 65535')
            if any(arg in ('-p', '--port') or arg.startswith('--port=') for arg in arguments):
                raise ValueError('use the worktree --port option, not a forwarded port')
            command = script(project, package, args.script, ['--port', str(args.port), *arguments])
            with nextjs_cache._worktree_lock(project):
                # Fail early on an occupied port; Next must not silently choose
                # another worktree's endpoint. The server owns the actual bind.
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1', args.port))
                code = subprocess.run(command, cwd=project).returncode
            return code if code >= 0 else 128 - code
        if not args.nanocompile:
            raise ValueError('--nanocompile is required when running the Python helper directly')
        command = script(project, package, args.script, arguments)
        summary = nextjs_cache.run_build(project, command, args.nanocompile, cache, args.dist_dir)
    print(json.dumps(summary, sort_keys=True), flush=True)
    code = summary.get('returncode', 0)
    return code if code >= 0 else 128 - code


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except subprocess.CalledProcessError as error:
        print('nanocompile worktree: command failed (exit {})'.format(error.returncode), file=sys.stderr)
        sys.exit(error.returncode if error.returncode > 0 else 128 - error.returncode)
    except (OSError, ValueError, RuntimeError) as error:
        print('nanocompile worktree: ' + str(error), file=sys.stderr)
        sys.exit(1)
