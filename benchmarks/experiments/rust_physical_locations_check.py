"""Exercise canonical compiler location reuse and live native-proxy fallback."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    binary = args.binary.resolve()
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('NANOCOMPILE_', 'KACHE_', 'R2_', 'DYLD_', 'LD_'))
           and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER')}
    env['RUSTUP_TOOLCHAIN'] = '1.97.1'
    compiler = Path(subprocess.check_output(['rustup', 'which', 'rustc'], env=env, text=True).strip()).resolve()
    sysroot = subprocess.check_output([str(compiler), '--print', 'sysroot'], env=env, text=True).strip()
    libdir = subprocess.check_output([str(compiler), '--print', 'target-libdir'], env=env, text=True).strip()
    with tempfile.TemporaryDirectory(prefix='nano installation locations ') as tmp:
        root = Path(tmp)
        source, out = root / 'lib.rs', root / 'out'
        out.mkdir()
        source.write_text('pub fn answer()->u32 {42}\n')
        command = [str(binary), str(compiler), str(source), '--crate-name', 'locations',
                   '--crate-type', 'rlib', '--emit=dep-info,metadata,link', '--out-dir', str(out),
                   '-L', 'dependency=' + str(out)]
        def compile(cache_name, selected):
            env['NANOCOMPILE_DIR'] = str(root / cache_name)
            command[1] = str(selected)
            shutil.rmtree(out)
            out.mkdir()
            result = subprocess.run(command, cwd=root, env=env, capture_output=True, check=True)
            rows = [json.loads(path.read_bytes()[65:]) for path in (root / cache_name / 'toolchains').iterdir()]
            assert len(rows) == 1 and rows[0]['schema'] == 8
            return rows[0], hashlib.sha256((out / 'liblocations.rlib').read_bytes()).hexdigest()
        memo, reference = compile('direct-cache', compiler)
        assert {k:v for k,v in memo['locations'].items() if k != 'fallback_verified'} == {'compiler': str(compiler), 'sysroot': sysroot, 'target_libdir': libdir}, memo
        memo_again, artifact = compile('direct-cache', compiler)
        assert artifact == reference and memo_again == memo
        assert (root / 'direct-cache/events').read_text().splitlines() == ['miss', 'hit']
        if os.uname().sysname == 'Darwin':
            assert memo['locations']['fallback_verified']
            # A same-name invalid fallback driver must not be loaded before the
            # installed @rpath driver. It would fail startup if selected.
            shadow = root / 'shadow'; shadow.mkdir()
            driver = next((Path(sysroot)/'lib').glob('librustc_driver-*.dylib'))
            (shadow/driver.name).write_bytes(b'invalid shadow library')
            env['DYLD_FALLBACK_LIBRARY_PATH'] = str(shadow)
            fallback, digest = compile('fallback-cache', compiler)
            assert fallback['locations']['fallback_verified'] and digest == reference
            printed = subprocess.run([str(compiler),'--print','sysroot'], env=dict(env,DYLD_PRINT_LIBRARIES='1'),capture_output=True,check=True,text=True)
            assert str(driver) in printed.stderr and str(shadow/driver.name) not in printed.stderr
            env['DYLD_LIBRARY_PATH'] = ''
            override, _ = compile('override-cache', compiler)
            assert override['locations'] is None
            del env['DYLD_LIBRARY_PATH']; del env['DYLD_FALLBACK_LIBRARY_PATH']
        # A native proxy forwards stock Rust but must still query live. Its path
        # is not the canonical compiler within the reported installation.
        log = root / 'queries'
        shim, code = root / 'rustc', root / 'proxy.c'
        code.write_text('''#include <stdio.h>
#include <string.h>
#include <unistd.h>
int main(int argc, char **argv) {
    for (int i=1; i<argc; ++i) if (!strcmp(argv[i], "target-libdir")) {
        FILE *f=fopen(LOG, "a"); if (!f) return 126;
        fputs("query\\n", f); fclose(f); break;
    }
    argv[0]=REAL; execv(REAL, argv); return 127;
}
'''.replace('LOG', json.dumps(str(log))).replace('REAL', json.dumps(str(compiler))))
        subprocess.run(['cc', str(code), '-o', str(shim)], capture_output=True, check=True)
        proxy_memo, artifact = compile('proxy-cache', shim)
        assert proxy_memo['locations'] is None and artifact == reference
        assert log.read_text().splitlines() == ['query', 'query'], log.read_text()
        other = Path(subprocess.check_output(['rustup', 'which', '--toolchain', '1.98.1', 'rustc'], text=True).strip()).resolve()
        newer, _ = compile('other-cache', other)
        assert newer['locations'] is None
    report = {'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'checks': ['canonical Rust 1.97.1 retains compiler-reported sysroot and target-libdir',
                         'validated memo survives a real warm restore with identical output',
                         'native proxy retains live fingerprint and collector queries and identical output',
                         'Rust 1.98.1 declines the location shortcut',
                         'Darwin fallback shadow driver is ignored in live dyld observations',
                         'DYLD_LIBRARY_PATH retains live graph queries'], 'proxy_combined_queries': 2}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
