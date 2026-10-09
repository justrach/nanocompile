"""Verify pinned upstream vectors, then rotate streaming digests of real files."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('upstream', type=Path)
    parser.add_argument('--file', type=Path, action='append', required=True)
    parser.add_argument('--runs', type=int, default=25)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert args.runs > 0
    binary, upstream = args.binary.resolve(), args.upstream.resolve()
    vectors_path = upstream / 'test_vectors/test_vectors.json'
    vectors = json.loads(vectors_path.read_text())['cases']
    modes = ('zig', 'upstream')
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('R2_', 'KACHE_', 'NANOCOMPILE_'))}

    with tempfile.TemporaryDirectory(prefix='nano-blake3-stream-') as tmp:
        root = Path(tmp)
        env['NANOCOMPILE_DIR'] = str(root / 'cache')

        def run(mode, path):
            started = time.perf_counter()
            result = subprocess.run([str(binary), mode, str(path)], cwd=root,
                                    env=env, capture_output=True, check=True, timeout=120)
            elapsed = time.perf_counter() - started
            row = json.loads(result.stdout)
            assert row['upstream_version'] == '1.8.7'
            assert row['upstream_simd_degree'] == 4, 'This probe targets ARM NEON'
            row['process_seconds'] = elapsed
            return row

        vector_input = root / 'vector.bin'
        for case in vectors:
            length = case['input_len']
            vector_input.write_bytes((bytes(range(251)) * (length // 251 + 1))[:length])
            for mode in modes:
                assert run(mode, vector_input)['hash'] == case['hash'][:64], (mode, length)

        files = []
        for input_path in args.file:
            path = input_path.resolve()
            before = path.stat()
            input_sha = sha(path)
            reference = None
            samples = []
            for mode in modes:
                digest = run(mode, path)['hash']
                if reference is None:
                    reference = digest
                assert digest == reference
            for i in range(args.runs):
                for mode in (modes if i % 2 == 0 else modes[::-1]):
                    row = run(mode, path)
                    assert row['hash'] == reference
                    samples.append({'implementation': mode, **row})
            after = path.stat()
            assert (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (
                after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            assert sha(path) == input_sha
            files.append({
                'path': str(path), 'bytes': before.st_size, 'input_sha256': input_sha,
                'blake3': reference, 'input_content_and_state_unchanged': True,
                'samples': samples,
                'median_hash_ms': {mode: statistics.median(
                    r['nanoseconds'] for r in samples if r['implementation'] == mode) / 1e6
                    for mode in modes},
                'median_process_seconds': {mode: statistics.median(
                    r['process_seconds'] for r in samples if r['implementation'] == mode)
                    for mode in modes},
            })

    sources = ['blake3.c', 'blake3_dispatch.c', 'blake3_portable.c', 'blake3_neon.c',
               'blake3.h', 'blake3_impl.h']
    evidence = {
        'method': 'Same Zig executable and 64 KiB streaming reader; choose Zig Context.digest or pinned upstream C implementation. Prime both and rotate complete process runs. Internal timer includes open/stat/read/hash/close/result allocation. No mapping, memo shortcut or extra hashing threads. This is a file digest microbenchmark, not a project build comparison.',
        'zig_version': subprocess.check_output(['zig', 'version'], text=True).strip(),
        'upstream_tag': '1.8.7',
        'upstream_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=upstream,
                                                    text=True).strip(),
        'upstream_source_sha256': {name: sha(upstream / 'c' / name) for name in sources},
        'binary_sha256': sha(binary), 'script_sha256': sha(Path(__file__)),
        'zig_probe_sha256': sha(Path(__file__).with_suffix('.zig')),
        'cache_source_sha256': sha(Path(__file__).parents[2] / 'src/cache.zig'),
        'vectors_sha256': sha(vectors_path), 'official_unkeyed_vectors_verified': len(vectors),
        'runs_per_implementation_per_file': args.runs, 'files': files,
    }
    args.output.write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps([{'bytes': f['bytes'], 'median_hash_ms': f['median_hash_ms']}
                      for f in files], indent=2))


if __name__ == '__main__':
    main()
