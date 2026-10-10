"""Verify selected-resource decoder reuse and actual compiler-switch invalidation."""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile


def memos(root, schema):
    rows = []
    for path in root.iterdir():
        if not path.is_file():
            continue
        raw = path.read_bytes()
        value = json.loads(raw[65:])
        if value.get('schema') == schema:
            rows.append((path, value))
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary', type=Path)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--other-toolchain', default='1.98.1')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    binary = args.binary.resolve()
    env = {k:v for k,v in os.environ.items() if not k.startswith(('NANOCOMPILE_', 'R2_', 'KACHE_'))
           and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER')}
    env['RUSTUP_TOOLCHAIN'] = '1.97.1'
    with tempfile.TemporaryDirectory(prefix='nano decoder scope ') as temp:
        root = Path(temp)
        a, b, source, out, cache = [root/name for name in ('a', 'b', 'source', 'out', 'cache')]
        for directory in (a,b,source,out): directory.mkdir()
        (source/'lib.rs').write_text('pub fn answer() -> u32 { 42 }\n')
        env['NANOCOMPILE_DIR'] = str(cache)
        argv = [str(binary), 'rustc', str(source/'lib.rs'), '--crate-name', 'scope_fixture',
                '--crate-type', 'rlib', '--emit=dep-info,metadata,link', '--out-dir', str(out),
                '-L', 'dependency='+str(out), '-C', 'opt-level=1']
        def build(cwd, expected='miss'):
            for path in out.iterdir(): path.unlink()
            before = (cache/'events').read_text().splitlines() if (cache/'events').exists() else []
            q = subprocess.run(argv, cwd=cwd, env=env, capture_output=True)
            assert q.returncode == 0, q.stderr.decode(errors='replace')
            events = (cache/'events').read_text().splitlines()[len(before):]
            assert events == [expected] if expected else events in (['miss'], ['hit'])
        baseline_hash = None
        if args.baseline:
            candidate_argv = argv[0]
            argv[0] = str(args.baseline.resolve())
            build(a)
            baseline_memos = memos(cache/'toolchains', 4)
            assert len(baseline_memos) == 1
            baseline_hash = baseline_memos[0][1]['hash']
            shutil.rmtree(cache)
            argv[0] = candidate_argv
        build(a)
        first = memos(cache/'toolchains',5)
        assert len(first) == 1
        original = first[0][1]
        if baseline_hash is not None:
            assert original['hash'] == baseline_hash
        builtins = {path.name: (path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
                    for path,row in memos(cache/'metadata',2) if row.get('identity','').startswith('toolchain:')}
        assert builtins
        build(b)
        second = memos(cache/'toolchains',5)
        assert len(second) == 2
        assert len({row['hash'] for _,row in second}) == 2
        second_hashes = {row['hash'] for _,row in second}
        assert {row['decoder_hash'] for _,row in second} == {original['decoder_hash']}
        for name,(mtime,digest) in builtins.items():
            path = cache/'metadata'/name
            assert path.stat().st_mtime_ns == mtime and hashlib.sha256(path.read_bytes()).hexdigest() == digest
        (b/'rust-toolchain.toml').write_text('[toolchain]\nchannel = "1.97.1"\n')
        build(b)
        third = memos(cache/'toolchains',5)
        assert len({row['hash'] for _,row in third}) == 2
        assert {row['hash'] for _,row in third} != second_hashes
        assert {row['decoder_hash'] for _,row in third} == {original['decoder_hash']}
        for name,(mtime,digest) in builtins.items():
            path = cache/'metadata'/name
            assert path.stat().st_mtime_ns == mtime and hashlib.sha256(path.read_bytes()).hexdigest() == digest
        (b/'rust-toolchain.toml').unlink()
        build(b, expected=None)
        fourth = memos(cache/'toolchains',5)
        assert {row['hash'] for _,row in fourth} == second_hashes
        assert {row['decoder_hash'] for _,row in fourth} == {original['decoder_hash']}
        env['RUSTUP_TOOLCHAIN'] = args.other_toolchain
        switched_version = subprocess.check_output(['rustc','-vV'],env=env,text=True)
        build(b)
        switched = memos(cache/'toolchains',5)
        assert len(switched) == 3
        assert len({row['decoder_hash'] for _,row in switched}) == 2
        env['RUSTUP_TOOLCHAIN'] = '1.97.1'
        build(b, expected=None)
        returned = memos(cache/'toolchains',5)
        assert len(returned) == 3
        assert len({row['decoder_hash'] for _,row in returned}) == 2
        # Exercise selection by the caller file itself, without an environment override.
        del env['RUSTUP_TOOLCHAIN']
        (b/'rust-toolchain.toml').write_text('[toolchain]\nchannel = "1.97.1"\n')
        prior_paths = {path for path,_ in returned}
        build(b)
        selected = [(path,row) for path,row in memos(cache/'toolchains',5) if path not in prior_paths]
        assert len(selected) == 1
        selected_path, selected_row = selected[0]
        assert selected_row['decoder_hash'] == original['decoder_hash']
        (b/'rust-toolchain.toml').write_text('[toolchain]\nchannel = "'+args.other_toolchain+'"\n')
        actual_version = subprocess.check_output(['rustc','-vV'],cwd=b,env=env,text=True)
        assert actual_version == switched_version
        build(b)
        active = json.loads(selected_path.read_bytes()[65:])
        assert active['hash'] != selected_row['hash']
        assert active['decoder_hash'] != selected_row['decoder_hash']
        report = {'switched_rustc_version': switched_version, 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                  'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  'checks': ['different caller directories retain different complete compilation fingerprints',
                             'identical present compiler/resource state shares decoder identity',
                             'toolchain root-classification memos reused without rewriting across callers',
                             'adding a selector changes the full fingerprint while preserving decoder and classifications for unchanged actual compiler resources'],
                  'shared_toolchain_classifications': len(builtins)}
        report['checks'] += ['removing a caller selector restores the original full identity',
                             'switching the actual installed compiler changes decoder identity',
                             'returning to the original compiler reuses its unchanged identities',
                             'active caller selector changes both identities when it selects a different compiler']
        if baseline_hash is not None:
            report['baseline_sha256'] = hashlib.sha256(args.baseline.read_bytes()).hexdigest()
            report['checks'].append('complete compilation fingerprint matches baseline for identical caller state')
        args.output.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report))


if __name__ == '__main__': main()
