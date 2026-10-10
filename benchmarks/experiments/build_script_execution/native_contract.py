"""Prepare local explicit media/tree-sitter contracts; not an automatic auditor."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('project', type=Path)
    parser.add_argument('--tools-state', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--env-output', required=True, type=Path)
    parser.add_argument('--rustc', default='rustc')
    args = parser.parse_args()
    assert not args.output.exists() and not args.env_output.exists()
    binary, project = args.binary.resolve(), args.project.resolve()
    tools = args.tools_state.resolve()
    tools.mkdir(mode=0o700, parents=True, exist_ok=False)
    sdk = Path(subprocess.check_output(['/usr/bin/xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip()).resolve()
    sysroot = Path(subprocess.check_output([args.rustc,'--print','sysroot'],cwd=project,text=True).strip()).resolve()
    rustfmt = sysroot/'bin/rustfmt'
    libclang = Path('/Library/Developer/CommandLineTools/usr/lib/libclang.dylib')
    clang = Path('/usr/bin/clang')
    assert binary.is_file() and rustfmt.is_file() and libclang.is_file() and clang.is_file()
    config = tools/'rustfmt.toml'
    config.write_text('# Explicit default formatting; no parent/home config discovery.\n')
    formatter = tools/'media-rustfmt'
    formatter.write_text('#!/bin/sh\nexec '+shlex.quote(str(rustfmt))+' --config-path '+shlex.quote(str(config))+' "$@"\n')
    formatter.chmod(0o700); config.chmod(0o600)
    selections = dict(LIBCLANG_PATH=str(libclang), CLANG_PATH=str(clang), RUSTFMT=str(formatter))
    base = Path(__file__).with_name('sqlite-harness-contract.json')
    spec = json.loads(base.read_text())
    sqlite = next(p for p in spec['packages'] if p['package']=='libsqlite3-sys')
    for rule in sqlite['environment']:
        if rule['name']=='RUSTC_WRAPPER':rule['value']=str(binary)
    # Known source-audited native selectors; new directories from overrides
    # must not silently become undeclared compilation/bindgen inputs.
    absent = ['C_INCLUDE_PATH','OBJCPLUS_INCLUDE_PATH','CCC_OVERRIDE_OPTIONS','CCC_ADD_ARGS',
              'CLANG_CONFIG_FILE_SYSTEM_DIR','CLANG_CONFIG_FILE_USER_DIR',
              'LLVM_CONFIG_PATH','BINDGEN_EXTRA_CLANG_ARGS',
              'BINDGEN_EXTRA_CLANG_ARGS_aarch64-apple-darwin',
              'BINDGEN_EXTRA_CLANG_ARGS_aarch64_apple_darwin']
    native_rules = [copy.deepcopy(r) for r in sqlite['environment'] if
                    not r['name'].startswith(('CARGO_FEATURE_','SQLITE_','LIBSQLITE3_')) and r['name']!='CARGO_PKG_VERSION']
    existing = {r['name'] for r in native_rules}
    native_rules += [dict(name=name,value=None) for name in absent if name not in existing]
    for package,version in [('media','0.1.0'),('tree-sitter','0.26.11')]:
        item = copy.deepcopy(sqlite)
        item['package'] = package
        item['environment'] = copy.deepcopy(native_rules)+[dict(name='CARGO_PKG_VERSION',value=version)]
        if package=='media':
            item['environment'] += [dict(name=name,value=value) for name,value in selections.items()]
            item['inputs'] += [str(formatter),str(config)]
            item['tools'] += ['/usr/bin/clang','/usr/bin/xcrun','/bin/sh',str(rustfmt)]
            item['installed_inputs'] += [str(libclang),str(sdk/'System/Library/Frameworks'),
                                        '/Library/Developer/CommandLineTools/usr/include']
            item['tool_selection'] += [dict(tool='clang',path='/usr/bin/clang'),
                                       dict(tool='xcrun',path='/usr/bin/xcrun')]
        else:
            item['environment'] += [dict(name='CARGO_FEATURE_WASM',value=None),
                                    dict(name='CARGO_FEATURE_BINDGEN',value=None),
                                    dict(name='CARGO_FEATURE_STD',value='1')]
        spec['packages'].append(item)
    for output,value in [(args.output,spec),(args.env_output,selections)]:
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(value,indent=2)+'\n');output.chmod(0o600)
    record = dict(binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                  generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  sdk=str(sdk),sysroot=str(sysroot),source_contract_sha256=hashlib.sha256(base.read_bytes()).hexdigest(),
                  contract_sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(),
                  tools_file_sha256=hashlib.sha256(args.env_output.read_bytes()).hexdigest(),
                  formatter_sha256=hashlib.sha256(formatter.read_bytes()).hexdigest(),
                  rustfmt_config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
                  status='prepared; requires real direct/cold/hit/edit and whole-project validation')
    (tools/'preparation.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))


if __name__=='__main__':
    main()
