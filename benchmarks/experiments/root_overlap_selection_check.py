"""Reject a live sysroot disagreement without storing or restoring an entry."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('NANOCOMPILE_', 'R2_', 'KACHE_'))
           and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER')}
    env['RUSTUP_TOOLCHAIN'] = '1.97.1'
    sysroot = subprocess.check_output(['rustc', '--print', 'sysroot'], env=env, text=True).strip()
    target = subprocess.check_output(['rustc', '--print', 'target-libdir'], env=env, text=True).strip()
    binary = args.binary.resolve()
    with tempfile.TemporaryDirectory(prefix='nano root disagreement ') as temp:
        root = Path(temp)
        shim = root / 'rustc'
        code = root / 'shim.c'
        # Native proxy: normal compilation and fingerprint probes use real Rust.
        # The collector's combined live query deliberately reports another root.
        code.write_text('''#include <stdio.h>
#include <string.h>
#include <unistd.h>
int main(int argc, char **argv) {
    int combined = 0;
    for (int i = 1; i < argc; ++i)
        if (!strcmp(argv[i], "target-libdir")) combined = 1;
    if (combined) {
        puts("/deliberately/different/selected/toolchain");
        puts(TARGET);
        return 0;
    }
    argv[0] = REAL;
    execv(REAL, argv);
    return 127;
}
'''.replace('TARGET', json.dumps(target)).replace('REAL', json.dumps(str(Path(sysroot) / 'bin/rustc'))))
        subprocess.run(['cc', str(code), '-o', str(shim)], check=True, capture_output=True)
        source = root / 'lib.rs'
        source.write_text('pub fn answer() -> u32 { 42 }\n')
        out = root / 'out'
        out.mkdir()
        cache = root / 'cache'
        env.update(NANOCOMPILE_DIR=str(cache), NANOCOMPILE_TRACE='1')
        command = [str(binary), str(shim), str(source), '--crate-name', 'root_disagreement',
                   '--crate-type', 'rlib', '--emit=dep-info,metadata,link',
                   '--out-dir', str(out), '-L', 'dependency=' + str(out)]
        events = []
        artifact_hashes = []
        for _ in range(2):
            for path in out.iterdir():
                path.unlink()
            result = subprocess.run(command, cwd=root, env=env, capture_output=True)
            assert result.returncode == 0, result.stderr.decode(errors='replace')
            assert b'uncached: ToolchainChanged' in result.stderr, result.stderr
            artifact = out / 'libroot_disagreement.rlib'
            assert artifact.is_file()
            artifact_hashes.append(hashlib.sha256(artifact.read_bytes()).hexdigest())
            entries = cache / 'entries'
            assert not entries.exists() or not any(entries.iterdir())
        events = (cache / 'events').read_text().splitlines()
        assert events == ['miss', 'miss'], events
        assert artifact_hashes[0] == artifact_hashes[1]
    report = {'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'method': 'Native compiler proxy forwards real compilation and identity probes, but reports a disagreeing root on the live combined sysroot/target-libdir query.',
              'checks': ['live root disagreement rejects metadata before cache storage',
                         'successful compiler output remains available',
                         'second clean build recompiles instead of restoring',
                         'both uncached outputs match'], 'events': events}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
