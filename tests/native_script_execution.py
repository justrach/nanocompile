"""Replay actual Harness media/tree-sitter scripts in private source copies."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import time
from benchmark_storage import save_report
from bindgen_controls import load


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('binary','cargo-log','references','contract','bindgen-tools-file','state','output'):
        p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args();binary=args.binary.resolve();state=args.state.resolve()
    state.mkdir(parents=True,mode=0o700,exist_ok=False)
    controls,controls_hash=load(args.bindgen_tools_file)
    report=dict(completed=False,diagnostic=True,binary_sha256=sha(binary),runner_sha256=sha(Path(__file__)),
                contract_sha256=sha(args.contract),cargo_log_sha256=sha(args.cargo_log),
                bindgen_tools_file_sha256=controls_hash,packages={},
                stderr_normalization='Exclude nanocompile diagnostic lines and nondeterministic Rust main-thread panic IDs; raw streams retained and hashed',
                scope='Actual retained Harness build-script executables, private package copies; isolated diagnostics, no full-project speed claim')
    def save():save_report(args.output,report)
    try:
        for package_name in ('media','tree-sitter'):
            variables=None;command=None
            for line in args.cargo_log.read_text().splitlines():
                match=re.fullmatch(r'\s*Running `(.*)`',line)
                if not match:continue
                fields=shlex.split(match[1]);v={};i=0
                for i,field in enumerate(fields):
                    if '=' not in field or not re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',field.split('=',1)[0]):break
                    key,value=field.split('=',1);v[key]=value
                if v.get('CARGO_PKG_NAME')==package_name and 'OUT_DIR' in v and Path(fields[i]).name=='build-script-build':
                    variables=v;command=Path(fields[i]);break
            assert variables and command,package_name
            root=state/package_name;root.mkdir();source=root/'package'
            shutil.copytree(variables['CARGO_MANIFEST_DIR'],source)
            original={str(f.relative_to(source)):sha(f) for f in source.rglob('*') if f.is_file()}
            # Independent retained outputs are matched against the reference manifest.
            relative=Path('release/build')/command.parent.name/command.name
            real_source=args.references/relative
            manifest=json.loads((args.references/'manifest.json').read_text())
            assert real_source.is_file(),str(real_source)
            assert sha(real_source)==manifest['files'][str(relative)], 'Retained executable differs from manifest'
            real=root/'real';shutil.copy2(real_source,real);real.chmod(0o700)
            shim=root/'build-script-build';shutil.copy2(binary,shim);shim.chmod(0o700)
            (root/'nano-build-script.json').write_text(json.dumps(dict(real=str(real))))
            env={k:v for k,v in os.environ.items() if not k.startswith(('R2_','KACHE_','NANOCOMPILE_')) and k not in ('RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER')}
            env.update(variables);env.pop('CARGO_MAKEFLAGS',None)
            env.update(CARGO_MANIFEST_DIR=str(source),CARGO_MANIFEST_PATH=str(source/'Cargo.toml'),
                       RUSTC_WRAPPER=str(binary),OUT_DIR=str(root/'out'),NANOCOMPILE_DIR=str(root/'cache'),
                       NANOCOMPILE_BUILD_SCRIPTS_FILE=str(args.contract.resolve()),NANOCOMPILE_TRACE='1')
            rows=[];report['packages'][package_name]=dict(real_sha256=sha(real),source_hashes=original,samples=rows)
            def run(label,wrapped=True,decision=None,extra=None,success=True,selected=True):
                out=root/'out';shutil.rmtree(out,ignore_errors=True);out.mkdir()
                current=dict(env)
                if selected:current.update(controls)
                current.update(extra or {})
                events=root/'cache/events';offset=len(events.read_text().splitlines()) if events.exists() else 0
                started=time.perf_counter();q=subprocess.run([str(shim if wrapped else real)],cwd=source,env=current,stdin=subprocess.DEVNULL,capture_output=True,timeout=180)
                elapsed=time.perf_counter()-started
                (root/(label+'.stdout')).write_bytes(q.stdout);(root/(label+'.stderr')).write_bytes(q.stderr)
                outputs={str(f.relative_to(out)):dict(sha256=sha(f),mode=oct(f.stat().st_mode&0o777)) for f in out.rglob('*') if f.is_file()}
                seen=events.read_text().splitlines()[offset:] if events.exists() else []
                row=dict(label=label,seconds=elapsed,exit_code=q.returncode,events=seen,artifacts=outputs,
                         stdout_sha256=hashlib.sha256(q.stdout).hexdigest(),stderr_sha256=hashlib.sha256(q.stderr).hexdigest(),
                         normalized_stderr_sha256=hashlib.sha256(re.sub(rb"thread 'main' \(\d+\) panicked", b"thread 'main' (<runtime-id>) panicked", b'\n'.join(l for l in q.stderr.splitlines() if not l.startswith(b'nanocompile: ')))).hexdigest())
                rows.append(row);save();print(package_name,label,round(elapsed,4),seen,flush=True)
                assert (q.returncode==0)==success,q.stderr.decode(errors='replace')
                if decision:assert decision in seen,(decision,seen,q.stderr.decode(errors='replace'))
                return row
            def same(a,b):
                for key in ('artifacts','stdout_sha256','normalized_stderr_sha256','exit_code'):assert a[key]==b[key],(key,a,b)
            default=run('direct-default',False,selected=False)
            direct=run('direct-explicit',False)
            # Formatting/tool controls may affect diagnostics; require identical outputs.
            assert default['artifacts']==direct['artifacts']
            same(direct,run('cold',decision='build_script_miss'))
            for n in range(3):same(direct,run('hit-'+str(n),decision='build_script_hit'))
            if package_name=='media':
                edited=source/'src/bindings.h';content=edited.read_bytes();replacement=content+b'\n#define kCVPixelFormatType_NanoProbe 41\n'
            else:
                edited=source/'src/parser.c';content=edited.read_bytes();needle=b'self->language = ts_language_copy(language);\n  return true;';assert content.count(needle)==1
                replacement=content.replace(needle,b'self->language = ts_language_copy(language);\n  return language != NULL;')
            stat=edited.stat();edited.write_bytes(replacement);os.utime(edited,ns=(stat.st_atime_ns,stat.st_mtime_ns))
            changed=run('source-edit',decision='build_script_miss');assert changed['artifacts']!=direct['artifacts']
            same(changed,run('direct-edited',False));same(changed,run('edited-hit',decision='build_script_hit'))
            if package_name=='media':
                bindings=(root/'out/bindings.rs').read_text();assert 'kCVPixelFormatType_NanoProbe' in bindings
                probe=root/'probe.rs';probe.write_text('#![allow(warnings)]\ninclude!("out/bindings.rs");\nfn main(){println!("{}",kCVPixelFormatType_NanoProbe);}\n')
                subprocess.run([variables['RUSTC'],str(probe),'-o',str(root/'probe')],check=True,capture_output=True)
                assert subprocess.check_output([str(root/'probe')]).strip()==b'41'
            else:
                probe=root/'probe.c';probe.write_text('#include <tree_sitter/api.h>\n#include <stdio.h>\nint main(){TSParser*p=ts_parser_new();printf("%d\\n",ts_parser_set_language(p,NULL));ts_parser_delete(p);}\n')
                def probe_value():
                    subprocess.run(['/usr/bin/cc','-I'+str(source/'include'),str(probe),str(root/'out/libtree-sitter.a'),'-o',str(root/'probe')],check=True,capture_output=True)
                    return subprocess.check_output([str(root/'probe')]).strip()
                assert probe_value()==b'0'
            edited.write_bytes(content);os.utime(edited,ns=(stat.st_atime_ns,stat.st_mtime_ns))
            same(direct,run('source-revert',decision='build_script_hit'))
            if package_name=='tree-sitter':assert probe_value()==b'1'
            flag={'BINDGEN_EXTRA_CLANG_ARGS':'-DNANO_UNUSED=1'} if package_name=='media' else {'CFLAGS':'-DNANO_UNUSED=1'}
            same(run('direct-override',False,extra=flag),run('guarded-override',decision='build_script_bypass',extra=flag))
            failure={'CLANG_PATH':str(root/'missing-clang'),'LIBCLANG_PATH':str(root/'missing-libclang')} if package_name=='media' else {'CC_FORCE_DISABLE':'1'}
            # Missing libclang can trigger global fallback discovery; use a real failing formatter instead.
            if package_name=='media':
                failing=root/'failing-rustfmt';failing.write_text('#!/bin/sh\nexit 7\n');failing.chmod(0o700)
                failure={'RUSTFMT':str(failing)}
                # bindgen's formatter error behavior is compared, whether fatal or fallback.
                a=run('direct-tool-failure',False,extra=failure)
                same(a,run('guarded-tool-failure',decision='build_script_bypass',extra=failure))
            else:
                a=run('direct-tool-failure',False,extra=failure,success=False)
                same(a,run('guarded-tool-failure',decision='build_script_bypass',extra=failure,success=False))
            same(direct,run('after-failure',decision='build_script_hit'))
            if package_name=='media':
                edited.write_bytes(content+b'\n#error intentional private-header failure\n')
                os.utime(edited,ns=(stat.st_atime_ns,stat.st_mtime_ns))
                a=run('direct-invalid-header',False,success=False)
                same(a,run('invalid-header',decision='build_script_failed',success=False))
                edited.write_bytes(content);os.utime(edited,ns=(stat.st_atime_ns,stat.st_mtime_ns))
                same(direct,run('after-header-failure',decision='build_script_hit'))
                config=Path(controls['RUSTFMT']).parent/'rustfmt.toml'
                cfg=config.read_bytes();cs=config.stat()
                try:
                    config.write_bytes(cfg+b'# preserved-mtime declared formatter config edit\n')
                    os.utime(config,ns=(cs.st_atime_ns,cs.st_mtime_ns))
                    same(direct,run('formatter-config-edit',decision='build_script_miss'))
                finally:
                    config.write_bytes(cfg);os.utime(config,ns=(cs.st_atime_ns,cs.st_mtime_ns))
                same(direct,run('formatter-config-revert',decision='build_script_hit'))
            corrupted=0
            for entry in (root/'cache/entries').iterdir():
                data=json.loads(entry.read_bytes()[65:])
                for output in data['outputs']:
                    digest=output['hash'];blob=root/'cache/blobs'/digest[:2]/digest
                    if blob.is_file():blob.write_bytes(b'corrupt');corrupted+=1
            assert corrupted
            same(direct,run('corruption-repair',decision='build_script_miss'))
            same(direct,run('repaired-hit',decision='build_script_hit'))
            assert original=={str(f.relative_to(source)):sha(f) for f in source.rglob('*') if f.is_file()}
            report['packages'][package_name]['verified']=True;save()
        report['completed']=True;save()
    except BaseException as error:
        report['failure']=dict(type=type(error).__name__,message=str(error));save();raise


if __name__=='__main__':main()
