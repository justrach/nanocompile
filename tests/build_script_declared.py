"""Real Cargo checks for NANOCOMPILE_BUILD_SCRIPT_CACHE=declared (Cargo's rerun rule)."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


SCRIPT = r'''
use std::{env, fs, path::PathBuf};
fn main() {
    let out = PathBuf::from(env::var("OUT_DIR").unwrap());
    let mode = env::var("SCRIPT_MODE").unwrap_or_default();
    eprintln!("script ran");
    let data = fs::read_to_string("data.txt").unwrap();
    let value: u32 = data.trim().parse().unwrap();
    let extra: u32 = env::var("EXTRA").ok().and_then(|v| v.parse().ok()).unwrap_or(0);
    fs::write(out.join("value.rs"), format!("pub const VALUE: u32 = {};", value + extra)).unwrap();
    match mode.as_str() {
        "undeclared" => {}
        "always" => println!("cargo:rerun-if-changed="),
        "outdir" => { fs::write(out.join("gen.txt"), "x").unwrap(); println!("cargo:rerun-if-changed={}", out.join("gen.txt").display()); }
        "nested" => { fs::create_dir_all(out.join("sub")).unwrap(); println!("cargo::rerun-if-changed=data.txt"); }
        "env-only" => println!("cargo:rerun-if-env-changed=EXTRA"),
        "dir" => println!("cargo:rerun-if-changed=assets"),
        _ => { println!("cargo:rerun-if-changed=data.txt"); println!("cargo:rerun-if-env-changed=EXTRA"); }
    }
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary', type=Path)
    binary = p.parse_args().binary.resolve()
    with tempfile.TemporaryDirectory(prefix='nano declared script ') as tmp:
        root = Path(tmp)
        project, target, cache = root / 'project', root / 'target', root / 'cache'
        (project / 'src').mkdir(parents=True)
        (project / 'Cargo.toml').write_text('[package]\nname="declared-fixture"\nversion="0.1.0"\nedition="2021"\n')
        (project / 'src/main.rs').write_text('include!(concat!(env!("OUT_DIR"), "/value.rs"));\nfn main() { println!("{}", VALUE); }\n')
        (project / 'build.rs').write_text(SCRIPT)
        (project / 'data.txt').write_text('40\n')
        (project / 'notes.md').write_text('a\n')
        base = {k: v for k, v in os.environ.items() if not k.startswith(('NANOCOMPILE_', 'R2_', 'KACHE_'))
                and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER')}
        base.update(RUSTC_WRAPPER=str(binary), CARGO_TARGET_DIR=str(target), NANOCOMPILE_DIR=str(cache),
                    NANOCOMPILE_BUILD_SCRIPT_CACHE='declared', NANOCOMPILE_TRACE='1', EXTRA='2')
        base.setdefault('RUSTUP_TOOLCHAIN', '1.97.1')

        def events():
            path = cache / 'events'
            return path.read_text().splitlines() if path.exists() else []

        def cargo(expected, decision, **changes):
            shutil.rmtree(target, ignore_errors=True)
            before = len(events())
            env = dict(base, **changes)
            q = subprocess.run(['cargo', 'build', '--release', '--offline'], cwd=project, env=env,
                               stdin=subprocess.DEVNULL, capture_output=True)
            assert q.returncode == 0, q.stderr.decode(errors='replace')
            seen = [e for e in events()[before:] if e.startswith('build_script')]
            assert seen == [decision], (decision, seen, q.stderr.decode(errors='replace')[-2000:])
            actual = subprocess.check_output([str(target / 'release/declared-fixture')]).decode().strip()
            assert actual == str(expected), (actual, expected)

        def preserved_edit(path, text):
            stamp = path.stat()
            path.write_text(text)
            os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))

        cargo(42, 'build_script_miss')
        cargo(42, 'build_script_hit')
        # A declared input edited in place with size and mtime preserved.
        preserved_edit(project / 'data.txt', '41\n')
        cargo(43, 'build_script_miss')
        cargo(43, 'build_script_hit')
        # Undeclared package files are not inputs once the script declares any.
        (project / 'notes.md').write_text('changed\n')
        cargo(43, 'build_script_hit')
        # A declared environment variable is part of the key.
        cargo(44, 'build_script_miss', EXTRA='3')
        cargo(44, 'build_script_hit', EXTRA='3')
        cargo(43, 'build_script_hit')
        # Reverting restores the historical result.
        preserved_edit(project / 'data.txt', '40\n')
        cargo(42, 'build_script_hit')

        # A script that declares nothing depends on its whole package.
        cargo(42, 'build_script_miss', SCRIPT_MODE='undeclared')
        cargo(42, 'build_script_hit', SCRIPT_MODE='undeclared')
        (project / 'notes.md').write_text('changed again\n')
        cargo(42, 'build_script_miss', SCRIPT_MODE='undeclared')
        cargo(42, 'build_script_hit', SCRIPT_MODE='undeclared')
        (project / 'extra-file').write_text('new member\n')
        cargo(42, 'build_script_miss', SCRIPT_MODE='undeclared')
        cargo(42, 'build_script_hit', SCRIPT_MODE='undeclared')

        # Only env declarations: no file inputs, as in Cargo.
        cargo(42, 'build_script_miss', SCRIPT_MODE='env-only')
        cargo(42, 'build_script_hit', SCRIPT_MODE='env-only')

        # An explicitly declared directory is tracked in full, including
        # VCS-named and CACHEDIR.TAG subdirectories that the package scan skips.
        for sub in ('.git', 'cached'):
            (project / 'assets' / sub).mkdir(parents=True, exist_ok=True)
            (project / 'assets' / sub / 'file').write_text('one\n')
        (project / 'assets/cached/CACHEDIR.TAG').write_text('Signature: 8a477f597d28d172789f06886806bc55\n')
        cargo(42, 'build_script_miss', SCRIPT_MODE='dir')
        cargo(42, 'build_script_hit', SCRIPT_MODE='dir')
        for sub in ('.git', 'cached'):
            preserved_edit(project / 'assets' / sub / 'file', 'two\n')
            cargo(42, 'build_script_miss', SCRIPT_MODE='dir')
            cargo(42, 'build_script_hit', SCRIPT_MODE='dir')
        # The package-default scan skips them, as Cargo's package listing does.
        cargo(42, 'build_script_miss', SCRIPT_MODE='undeclared')
        cargo(42, 'build_script_hit', SCRIPT_MODE='undeclared')
        preserved_edit(project / 'assets/.git/file', 'three\n')
        cargo(42, 'build_script_hit', SCRIPT_MODE='undeclared')

        # Never cached: always-rerun, inputs under OUT_DIR, nested outputs.
        for mode in ('always', 'outdir', 'nested'):
            cargo(42, 'build_script_miss', SCRIPT_MODE=mode)
            cargo(42, 'build_script_miss', SCRIPT_MODE=mode)

        # A changed script binary (new source) never reuses the old run.
        (project / 'build.rs').write_text(SCRIPT.replace('value + extra', 'value + extra + 100'))
        cargo(142, 'build_script_miss')
        cargo(142, 'build_script_hit')

        # An explicit contract that lists only other packages leaves this one
        # in declared mode (the contract pre-check skips the full parse).
        other = root / 'contract.json'
        other.write_text('{"schema": 1, "packages": [{"package": "some-other-package", "inputs": ["/nonexistent"]}]}')
        cargo(142, 'build_script_miss', NANOCOMPILE_BUILD_SCRIPTS_FILE=str(other))
        cargo(142, 'build_script_hit', NANOCOMPILE_BUILD_SCRIPTS_FILE=str(other))
        # A listed package whose environment is outside its contract (here a
        # release build against a contract recorded with DEBUG=true) falls back
        # to declared mode instead of running live.
        listed = root / 'listed.json'
        listed.write_text(json.dumps({"schema": 1, "packages": [{"package": "declared-fixture", "inputs": ["."],
                                                                  "environment": [{"name": "DEBUG", "value": "true"}]}]}))
        cargo(142, 'build_script_miss', NANOCOMPILE_BUILD_SCRIPTS_FILE=str(listed))
        cargo(142, 'build_script_hit', NANOCOMPILE_BUILD_SCRIPTS_FILE=str(listed))

        # Installed shims are text files naming Nano as their interpreter, so
        # no new executable image is created per build. A shim whose record
        # is missing must fail immediately rather than run itself again.
        shims = list((target / 'release/build').glob('declared-fixture-*/build-script-build'))
        assert shims and all(s.read_bytes().startswith(b'#!' + str(binary).encode()) for s in shims), shims
        orphan = root / 'orphan' / 'build-script-build'
        orphan.parent.mkdir()
        orphan.write_bytes(b'#!' + str(binary).encode() + b'\n')
        orphan.chmod(0o700)
        q = subprocess.run([str(orphan)], env=base, capture_output=True, timeout=20)
        assert q.returncode != 0 and b'MissingBuildScriptRecord' in q.stderr, q.stderr
        # Disabled mode runs every script live and records nothing new.
        shutil.rmtree(target, ignore_errors=True)
        env = {k: v for k, v in base.items() if k != 'NANOCOMPILE_BUILD_SCRIPT_CACHE'}
        before = len(events())
        q = subprocess.run(['cargo', 'build', '--release', '--offline'], cwd=project, env=env,
                           stdin=subprocess.DEVNULL, capture_output=True)
        assert q.returncode == 0 and not [e for e in events()[before:] if e.startswith('build_script')]
        assert subprocess.check_output([str(target / 'release/declared-fixture')]).decode().strip() == '142'
    print('PASS: declared build-script runs: hits, preserved-mtime edits, env keys, package default, '
          'uncacheable scripts, binary changes and disabled mode')


if __name__ == '__main__':
    main()
