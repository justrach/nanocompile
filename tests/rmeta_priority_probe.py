"""Verify rustc's transitive rmeta priority before narrowing cache input hashing."""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path, nargs='?')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--pipelined-companions', action='store_true')
    parser.add_argument('--disable-pipelined-companions', action='store_true')
    parser.add_argument('--toolchain', default='1.97.1')
    args = parser.parse_args()
    companions = not args.disable_pipelined_companions
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))
           and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER', 'RUSTC_BOOTSTRAP')}
    env['RUSTUP_TOOLCHAIN'] = args.toolchain
    if args.disable_pipelined_companions:
        env['NANOCOMPILE_PIPELINED_COMPANIONS'] = '0'
    if args.pipelined_companions:
        env['NANOCOMPILE_PIPELINED_COMPANIONS'] = '1'
    with tempfile.TemporaryDirectory(prefix='nano-rmeta-priority-') as tmp:
        root = Path(tmp)
        if args.binary:
            env.update(NANOCOMPILE_DIR=str(root / 'cache'), NANOCOMPILE_TRACE='1')
        for folder in ('deps', 'out', 'alternate', 'kind-cache', 'symlink-cache'):
            (root / folder).mkdir()

        def run(command, success=True):
            result = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=180)
            assert (result.returncode == 0) == success, result.stderr.decode(errors='replace')
            return result

        def library(name, folder, extra=()):
            return ['rustc', '--edition=2021', name + '.rs', '--crate-name', name,
                    '--crate-type', 'rlib', '--emit=dep-info,metadata,link',
                    '--out-dir', folder, *extra]

        (root / 'dep.rs').write_text('pub struct Value(pub u32); pub fn value()->Value {Value(12)}\n')
        (root / 'middle.rs').write_text('pub use dep::Value; pub fn value()->Value {dep::value()}\n')
        (root / 'top.rs').write_text('pub fn value()->middle::Value {middle::value()}\n')
        (root / 'main.rs').write_text('fn main(){println!("{}",top::value().0);}\n')
        run(library('dep', 'deps'))
        run(library('middle', 'deps', ['--extern', 'dep=deps/libdep.rmeta']))
        top = library('top', 'out', ['--extern', 'middle=deps/libmiddle.rmeta', '-Ldependency=deps'])

        def compile_top(command=top):
            for path in (root / 'out').iterdir():
                path.unlink()
            run(command)
            return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted((root / 'out').iterdir())}

        reference = compile_top()
        def cached(hit):
            for path in (root / 'out').iterdir():
                path.unlink()
            result = run([str(args.binary.resolve()), *top])
            assert (b'nanocompile: hit' in result.stderr) == hit, result.stderr.decode()
            hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted((root / 'out').iterdir())}
            assert hashes == reference
        if args.binary:
            cached(False)
            cached(True)
        archive = root / 'deps/libdep.rlib'
        metadata = root / 'deps/libdep.rmeta'
        original_archive = archive.read_bytes()
        original_metadata = metadata.read_bytes()
        stamp = archive.stat()
        archive.write_bytes(b'not an archive\n')
        os.utime(archive, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        assert compile_top() == reference
        if args.binary:
            cached(True)
        # A final executable must still read the object archives.
        binary = ['rustc', '--edition=2021', 'main.rs', '--extern', 'top=out/libtop.rlib',
                  '-Ldependency=deps', '-o', 'consumer']
        run(binary, success=False)
        # Explicit --extern archive paths retain their full input semantics.
        explicit = library('middle', 'out', ['--extern', 'dep=deps/libdep.rlib'])
        run(explicit, success=False)
        if args.binary and companions:
            archive.unlink()
            assert compile_top() == reference
            cached(True)
            archive.write_bytes(original_archive)
            cached(True)
            # Isolate kind-change variants from the bounded history exercised below.
            regular_cache = env['NANOCOMPILE_DIR']
            env['NANOCOMPILE_DIR'] = str(root / 'kind-cache')
            cached(False)
            cached(True)
            # Only the regular companion entry is omitted. A differently
            # typed directory entry still changes the membership guard.
            alias = root / 'archive-alias'
            alias.write_bytes(original_archive)
            archive.unlink()
            archive.symlink_to(alias)
            assert compile_top() == reference
            cached(False)
            archive.unlink()
            archive.write_bytes(original_archive)
            cached(True)
            env['NANOCOMPILE_DIR'] = regular_cache
        archive.write_bytes(original_archive)
        assert compile_top() == reference
        run(binary)
        assert run([str(root / 'consumer')]).stdout == b'12\n'
        if args.binary:
            # Metadata classifications are not substitutes for byte hashing:
            # trailing bytes leave rustc's root identity unchanged.
            metadata_stamp = metadata.stat()
            metadata.write_bytes(original_metadata + b'padding')
            os.utime(metadata, ns=(metadata_stamp.st_atime_ns, metadata_stamp.st_mtime_ns))
            assert compile_top() == reference
            cached(False)
            cached(True)
            metadata.write_bytes(original_metadata)
            # The original metadata bytes match a retained validated state.
            cached(True)
            # An extra candidate without a proven same-stem metadata match
            # retains its full byte guard, even when rustc ignores it.
            competitor = root / 'deps/libdep-other.rlib'
            competitor.write_bytes(original_archive)
            assert compile_top() == reference
            cached(False)
            cached(True)
            competitor_stamp = competitor.stat()
            competitor.write_bytes(b'not a competing archive\n')
            os.utime(competitor, ns=(competitor_stamp.st_atime_ns, competitor_stamp.st_mtime_ns))
            assert compile_top() == reference
            cached(False)
            competitor.unlink()
            cached(True)
            # Explicit archive inputs must miss even with a valid companion.
            for path in (root / 'out').iterdir():
                path.unlink()
            cold = run([str(args.binary.resolve()), *explicit])
            assert b'nanocompile: hit' not in cold.stderr
            warm = run([str(args.binary.resolve()), *explicit])
            assert b'nanocompile: hit' in warm.stderr, warm.stderr.decode()
            archive.write_bytes(b'not an archive\n')
            failed = run([str(args.binary.resolve()), *explicit], success=False)
            assert b'nanocompile: hit' not in failed.stderr
            archive.write_bytes(original_archive)
        if args.binary and companions:
            seed = root / 'archive-seed'
            seed.write_bytes(original_archive)
            proxy = root / 'late-rustc'
            source = Path(__file__).resolve().parents[1] / 'tools/late_archive_compiler.c'
            subprocess.run(['cc', str(source), '-O2', '-o', str(proxy),
                            '-DREAL_RUSTC=' + json.dumps(shutil.which('rustc')),
                            '-DARCHIVE_SEED=' + json.dumps(str(seed)),
                            '-DARCHIVE_DEST=' + json.dumps(str(archive))], check=True, capture_output=True)
            archive.unlink()
            for path in (root / 'out').iterdir():
                path.unlink()
            late = [str(args.binary.resolve()), str(proxy), *top[1:]]
            first_late = run(late)
            assert archive.read_bytes() == original_archive
            assert b'uncached:' not in first_late.stderr, first_late.stderr.decode()
            assert b'nanocompile: hit' not in first_late.stderr
            for path in (root / 'out').iterdir():
                path.unlink()
            second_late = run(late)
            assert b'nanocompile: hit' in second_late.stderr, second_late.stderr.decode()
            assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / 'out').iterdir()} == reference
        if args.binary:
            # Nonregular metadata retains the full directory guard, while
            # unchanged static inputs still cache normally.
            regular_cache = env['NANOCOMPILE_DIR']
            env['NANOCOMPILE_DIR'] = str(root / 'symlink-cache')
            alias = root / 'metadata-alias'
            alias.write_bytes(original_metadata)
            metadata.unlink()
            metadata.symlink_to(alias)
            assert compile_top() == reference
            cached(False)
            cached(True)
            archive.unlink()
            assert compile_top() == reference
            cached(False)
            cached(True)
            archive.write_bytes(original_archive)
            metadata.unlink()
            metadata.write_bytes(original_metadata)
            env['NANOCOMPILE_DIR'] = regular_cache
        metadata.unlink()
        assert compile_top() == reference
        if args.binary:
            cached(False)
            cached(True)
        metadata.write_bytes(b'not metadata\n')
        assert compile_top() == reference
        if args.binary:
            cached(False)
        # A readable but nonmatching metadata candidate must not mask a valid
        # archive with the original crate hash.
        (root / 'dep.rs').write_text('pub struct Value(pub u32); pub fn value()->Value {Value(13)}\n')
        run(library('dep', 'alternate'))
        metadata.write_bytes((root / 'alternate/libdep.rmeta').read_bytes())
        assert compile_top() == reference
        if args.binary:
            cached(False)
        metadata.write_bytes(original_metadata)
        archive.write_bytes(b'not an archive\n')
        assert compile_top() == reference
        metadata.unlink()
        run(top, success=False)
        evidence = {
            'rustc_verbose_version': run(['rustc', '-vV']).stdout.decode().strip(),
            'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'transitive_corrupt_companion_rlib_outputs_equal': True,
            'preserved_mtime_archive_change_ignored_with_valid_rmeta': True,
            'missing_corrupt_and_mismatched_rmeta_fall_back_to_archive': True,
            'explicit_rlib_and_final_binary_reject_corrupt_archive': True,
            'no_valid_metadata_or_archive_rejected': True,
            'linked_executable_value': 12,
            'output_sha256': reference,
        }
        if args.binary:
            evidence.update(binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                            cache_ignores_unused_companion=True,
                            cache_detects_metadata_removal_corruption_and_mismatch=True,
                            full_metadata_bytes_checked_with_same_root_and_preserved_mtime=True,
                            competing_candidate_content_and_membership_checked=True,
                            explicit_archive_cache_mutation_detected=True,
                            pipelined_companions=companions,
                            late_unused_archive_store_and_restore=companions)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(evidence, indent=2) + '\n')
    print('PASS: transitive rmeta priority, archive fallback, explicit externs and final linking')


if __name__ == '__main__':
    main()
