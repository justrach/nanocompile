"""Replay explicitly audited actual Harness C grammar scripts with runtime ABI edits."""
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
    p.add_argument("--audit",type=Path,default=Path(__file__).resolve().parents[1]/"benchmarks/harness-grammar-script-audit.json")
    args=p.parse_args();binary=args.binary.resolve();state=args.state.resolve()
    state.mkdir(parents=True,mode=0o700,exist_ok=False)
    controls,controls_hash=load(args.bindgen_tools_file)
    report=dict(completed=False,diagnostic=True,binary_sha256=sha(binary),runner_sha256=sha(Path(__file__)),
                contract_sha256=sha(args.contract),cargo_log_sha256=sha(args.cargo_log),
                bindgen_tools_file_sha256=controls_hash,packages={},
                stderr_normalization='Exclude nanocompile diagnostic lines and nondeterministic Rust main-thread panic IDs; raw streams retained and hashed',
                audit_sha256=sha(args.audit), scope='Explicitly audited actual retained Harness grammar build-script executables, private package copies; runtime grammar ABI edits; isolated diagnostics, no full-project speed claim')
    def save():save_report(args.output,report)
    try:
        for audit_entry in json.loads(args.audit.read_bytes())['entries']:
            package_name=audit_entry['package']
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
            assert sha(source/audit_entry['script_relative_path'])==audit_entry['build_script_sha256']
            assert variables['CARGO_PKG_VERSION']==audit_entry['version']
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
            edited=sorted(source.rglob('parser.c'))[0];content=edited.read_bytes()
            match=re.search(rb'#define LANGUAGE_VERSION (\d+)',content);assert match
            initial=int(match[1]);changed_version=initial-1
            replacement=content[:match.start(1)]+str(changed_version).encode()+content[match.end(1):]
            header=edited.parent/'tree_sitter/parser.h'
            field=re.search(r'struct TSLanguage \{\s*uint32_t (\w+);',header.read_text()).group(1)
            symbol=re.search(rb'const TSLanguage \*(tree_sitter_\w+)\(void\)',content).group(1).decode()
            probe=root/'probe.c'
            probe.write_text('#include <tree_sitter/parser.h>\n#include <stdio.h>\nextern const TSLanguage *'+symbol+'(void);\nint main(){printf("%u\\n",'+symbol+'()->'+field+');}\n')
            def probe_value():
                archive=list((root/'out').glob('*.a'));assert len(archive)==1,archive
                subprocess.run(['/usr/bin/cc','-I'+str(edited.parent),str(probe),str(archive[0]),'-o',str(root/'probe')],check=True,capture_output=True)
                return subprocess.check_output([str(root/'probe')]).strip()
            assert probe_value()==str(initial).encode()
            stat=edited.stat();edited.write_bytes(replacement);os.utime(edited,ns=(stat.st_atime_ns,stat.st_mtime_ns))
            changed=run('source-edit',decision='build_script_miss');assert changed['artifacts']!=direct['artifacts']
            same(changed,run('direct-edited',False));same(changed,run('edited-hit',decision='build_script_hit'))
            assert probe_value()==str(changed_version).encode()
            edited.write_bytes(content);os.utime(edited,ns=(stat.st_atime_ns,stat.st_mtime_ns))
            same(direct,run('source-revert',decision='build_script_hit'))
            assert probe_value()==str(initial).encode()
            hs=header.stat();original_header=header.read_bytes()
            try:
                header.write_bytes(original_header+b'\n/* private preserved-mtime header edit */\n')
                os.utime(header,ns=(hs.st_atime_ns,hs.st_mtime_ns))
                same(direct,run('header-edit',decision='build_script_miss'))
            finally:
                header.write_bytes(original_header);os.utime(header,ns=(hs.st_atime_ns,hs.st_mtime_ns))
            same(direct,run('header-revert',decision='build_script_hit'))
            member=source/'nano-unused-input.h';member.write_text('/* new package member */\n')
            same(direct,run('new-member',decision='build_script_miss'))
            member.unlink();same(direct,run('member-revert',decision='build_script_hit'))
            flag={'CFLAGS':'-DNANO_UNUSED=1'}
            same(run('direct-override',False,extra=flag),run('guarded-override',decision='build_script_bypass',extra=flag))
            failure={'CC_FORCE_DISABLE':'1'}
            a=run('direct-tool-failure',False,extra=failure,success=False)
            same(a,run('guarded-tool-failure',decision='build_script_bypass',extra=failure,success=False))
            same(direct,run('after-failure',decision='build_script_hit'))
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
