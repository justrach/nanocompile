"""Investigation only: decode native kinds in one exact rustc metadata format.

This does not change nanocompile eligibility. Unknown records fail closed.
Layout source: rust-lang/rust commit 8bab26f4f68e0e26f0bb7960be334d5b520ea452,
compiler/rustc_metadata/src/rmeta and rustc_hir/src/attrs/data_structures.rs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

VERSION = b'rustc 1.97.1 (8bab26f4f 2026-07-14)'


class Reader:
    def __init__(self, data, pos=0):
        self.data, self.pos = data, pos

    def take(self, n):
        if n < 0 or self.pos + n > len(self.data):
            raise ValueError('truncated metadata')
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def byte(self):
        return self.take(1)[0]

    def integer(self):
        out = 0
        for shift in range(0, 64, 7):
            b = self.byte()
            if shift == 63 and b > 1:
                raise ValueError('integer overflow')
            out |= (b & 127) << shift
            if b < 128:
                return out
        raise ValueError('invalid integer')

    def string(self):
        out = self.take(self.integer())
        if self.byte() != 0xc1:
            raise ValueError('invalid string sentinel')
        return out.decode('utf-8')

    def boolean(self):
        b = self.byte()
        if b > 1:
            raise ValueError('invalid bool')
        return bool(b)

    def option_bool(self):
        return self.boolean() if self.boolean() else None

    def symbol(self):
        tag = self.byte()
        if tag == 0:
            return self.string()
        if tag == 1:
            return Reader(self.data, self.integer()).string()
        if tag == 2:
            return {'predefined': self.integer()}
        raise ValueError('unknown symbol encoding')


def classify(data):
    if not data.startswith(b'rust\0\0\0\x0a') or not data.endswith(b'rust-end-file'):
        raise ValueError('unknown metadata format')
    data = data[:-len(b'rust-end-file')]
    if Reader(data, 16).string().encode() != VERSION:
        raise ValueError('unknown compiler version')
    root = int.from_bytes(data[8:16], 'little')
    r = Reader(data, root)
    if r.byte() != 0:
        raise ValueError('custom target unsupported')
    triple = r.string()
    crate_hash = f'{int.from_bytes(r.take(16), "little"):032x}'
    name = r.symbol()
    if r.boolean() or r.boolean():
        raise ValueError('proc-macro or stub unsupported')
    extra = r.string()
    r.take(8)  # StableCrateId
    if r.boolean() and r.byte() > 1:
        raise ValueError('unknown panic strategy')
    if r.byte() > 1 or r.byte() > 4:
        raise ValueError('unknown root enums')
    for _ in range(4):
        r.boolean()
    previous = None
    count, position = 0, None
    for _ in range(10):
        count = r.integer()
        if count:
            distance = r.integer()
            position = root - distance if previous is None else previous + distance
            if not 16 <= position < root:
                raise ValueError('invalid lazy position')
            previous = position
    if count > 128:
        raise ValueError('too many native records')
    kinds = []
    if count:
        n = Reader(data, position)
        for _ in range(count):
            kind = n.byte()
            if kind == 0:
                modifiers = [n.option_bool() for _ in range(3)]
                label = 'static'
            elif kind in (1, 2, 3):
                modifiers = [n.option_bool()]
                label = {1: 'dylib', 2: 'raw-dylib', 3: 'framework'}[kind]
            elif kind in (4, 5, 6):
                modifiers = []
                label = {4: 'link-arg', 5: 'wasm-import', 6: 'unspecified'}[kind]
            else:
                raise ValueError('unknown native kind')
            library = n.symbol()
            filename = n.symbol() if n.boolean() else None
            if n.boolean():
                raise ValueError('conditional native record unsupported')
            if n.boolean():
                n.integer()  # crate number
                n.integer()  # definition index
            verbatim = n.option_bool()
            if n.integer() != 0:
                raise ValueError('DLL imports unsupported')
            kinds.append({'kind': label, 'name': library, 'filename': filename,
                          'modifiers': modifiers, 'verbatim': verbatim})
    return {'triple': triple, 'hash': crate_hash, 'name': name,
            'extra_filename': extra, 'native_libraries': kinds,
            'dynamic_only_candidate': all(x['kind'] in ('dylib', 'framework', 'unspecified')
                                          and x['filename'] is None for x in kinds)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--libc', type=Path)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    env = dict(os.environ, RUSTUP_TOOLCHAIN='1.97.1')
    env.pop('RUSTC_WRAPPER', None)
    env.pop('RUSTC_BOOTSTRAP', None)
    cases = {}
    with tempfile.TemporaryDirectory(prefix='nano-native-metadata-') as tmp:
        root = Path(tmp)
        def run(command):
            result = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=120)
            assert result.returncode == 0, result.stderr.decode(errors='replace')
            return result
        run(['rustc', '-Vv'])
        (root / 'native.c').write_text('int value(void) { return 12; }\n')
        run(['cc', '-c', 'native.c', '-o', 'native.o'])
        run(['ar', 'crs', 'libprobe.a', 'native.o'])
        attrs = {'none': '', 'default': '#[link(name="probe")]',
                 'dylib': '#[link(name="probe",kind="dylib")]',
                 'static': '#[link(name="probe",kind="static")]',
                 'two_dylibs': '#[link(name="probe",kind="dylib")] #[link(name="second",kind="dylib")]',
                 'inactive_static': '#[cfg(any())] #[link(name="probe",kind="static")]',
                 'macro_static': 'macro_rules! native { () => { #[link(name="probe",kind="static")] extern "C" {fn value()->i32;} }; } native!();'}
        for case, attr in attrs.items():
            source = attr if case == 'macro_static' else attr + '\nextern "C" {fn value()->i32;} '
            (root / 'lib.rs').write_text(source + '\npub fn answer()->i32 {12}\n')
            command = ['rustc', 'lib.rs', '--crate-name', case, '--crate-type', 'rlib',
                       '--emit=metadata,link', '-L', 'native=.', '--out-dir', '.']
            run(command)
            path = root / f'lib{case}.rmeta'
            data = path.read_bytes()
            result = classify(data)
            assert result['dynamic_only_candidate'] == (case not in ('static', 'macro_static')), result
            for malformed in (data[:15], data[:-1], data.replace(VERSION, b'x' * len(VERSION), 1)):
                try:
                    classify(malformed)
                except ValueError:
                    pass
                else:
                    raise AssertionError('malformed metadata accepted')
            artifact = root / f'lib{case}.rlib'
            reference = hashlib.sha256(artifact.read_bytes()).hexdigest()
            # Compilation of a dylib-linked rlib need not open that native file.
            if case in ('default', 'dylib', 'two_dylibs'):
                (root / 'libprobe.a').rename(root / 'saved.a')
                run(command)
                assert hashlib.sha256(artifact.read_bytes()).hexdigest() == reference
                (root / 'saved.a').rename(root / 'libprobe.a')
            if case in ('static', 'macro_static'):
                (root / 'native.c').write_text('int value(void) { return 13; }\n')
                run(['cc', '-c', 'native.c', '-o', 'native.o'])
                (root / 'libprobe.a').unlink()
                run(['ar', 'crs', 'libprobe.a', 'native.o'])
                run(command)
                assert hashlib.sha256(artifact.read_bytes()).hexdigest() != reference
                (root / 'native.c').write_text('int value(void) { return 12; }\n')
                run(['cc', '-c', 'native.c', '-o', 'native.o'])
                (root / 'libprobe.a').unlink()
                run(['ar', 'crs', 'libprobe.a', 'native.o'])
            cases[case] = result
        if args.libc:
            cases['real_libc'] = classify(args.libc.read_bytes())
        evidence = {'investigation_only': True, 'production_cache_behavior_changed': False,
                    'compiler_version': VERSION.decode(),
                    'probe_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    'cases': cases, 'malformed_header_version_and_truncation_rejected': True,
                    'dynamic_rlib_bytes_equal_with_native_archive_removed': True,
                    'static_and_macro_static_rlib_bytes_change_with_native_archive': True}
        if args.output:
            args.output.write_text(json.dumps(evidence, indent=2) + '\n')
        print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
