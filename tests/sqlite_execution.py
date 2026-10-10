"""Actual bundled SQLite script execution: guarded reuse, source edits and native bytes."""
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


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('binary', 'cargo_log', 'real', 'contract', 'state', 'output'):
        parser.add_argument('--'+name.replace('_', '-'), type=Path, required=True)
    args = parser.parse_args()
    binary=args.binary.resolve(); state=args.state.resolve()
    state.mkdir(parents=True,mode=0o700,exist_ok=False)
    variables=None
    for line in args.cargo_log.read_text().splitlines():
        match=re.fullmatch(r'\s*Running `(.*)`',line)
        if not match:continue
        env={}
        for field in shlex.split(match[1]):
            if '=' not in field or not re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',field.split('=',1)[0]):break
            name,value=field.split('=',1);env[name]=value
        if env.get('CARGO_PKG_NAME')=='libsqlite3-sys' and 'OUT_DIR' in env:
            variables=env;break
    assert variables and variables['CARGO_PKG_VERSION']=='0.30.1'
    package=state/'package';shutil.copytree(variables['CARGO_MANIFEST_DIR'],package)
    env={k:v for k,v in os.environ.items() if not k.startswith(('R2_','KACHE_','NANOCOMPILE_')) and k not in ('RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER')}
    env.update(variables)
    # Standalone execution has no Cargo jobserver descriptors. Drop its stale
    # advertisement; compiler semantics and deterministic native flags remain.
    env.pop('CARGO_MAKEFLAGS',None)
    env.update(CARGO_MANIFEST_DIR=str(package),RUSTC_WRAPPER=str(binary),OUT_DIR=str(state/'out'),
               NANOCOMPILE_DIR=str(state/'cache'),NANOCOMPILE_TRACE='1',
               NANOCOMPILE_BUILD_SCRIPTS_FILE=str(args.contract.resolve()))
    real=state/'real';shutil.copy2(args.real,real);real.chmod(0o700)
    shim=state/'build-script-build';shutil.copy2(binary,shim);shim.chmod(0o700)
    (state/'nano-build-script.json').write_text(json.dumps(dict(real=str(real))))
    rows=[]
    def run(label, wrapped=True, decision=None, extra=None, success=True):
        out=state/'out';shutil.rmtree(out,ignore_errors=True);out.mkdir()
        current=dict(env);current.update(extra or {})
        events=state/'cache/events';offset=len(events.read_text().splitlines()) if events.exists() else 0
        started=time.perf_counter()
        result=subprocess.run([str(shim if wrapped else real)],cwd=package,env=current,stdin=subprocess.DEVNULL,capture_output=True,timeout=180)
        elapsed=time.perf_counter()-started
        seen=events.read_text().splitlines()[offset:] if events.exists() else []
        stdout=state/(label+'.stdout');stderr=state/(label+'.stderr');stdout.write_bytes(result.stdout);stderr.write_bytes(result.stderr)
        artifacts={p.name:dict(sha256=digest(p),mode=oct(p.stat().st_mode & 0o777)) for p in out.iterdir() if p.is_file()}
        normalized=b'\n'.join(line for line in result.stderr.splitlines() if not line.startswith(b'nanocompile: '))
        row=dict(label=label,seconds=elapsed,exit_code=result.returncode,events=seen,artifacts=artifacts,
                 stdout_sha256=digest(stdout),stderr_sha256=digest(stderr),normalized_stderr_sha256=hashlib.sha256(normalized).hexdigest())
        rows.append(row)
        args.output.write_text(json.dumps(dict(completed=False, samples=rows),indent=2)+'\n')
        assert (result.returncode==0)==success,result.stderr.decode(errors='replace')
        if decision:assert decision in seen,(decision,seen,result.stderr.decode(errors='replace'))
        return row
    def same(first,next):
        assert all(first[k]==next[k] for k in ('artifacts','stdout_sha256','normalized_stderr_sha256')),(first,next)
    reference=run('direct',False)
    same(reference,run('cold',decision='build_script_miss'))
    for i in range(3):same(reference,run('warm-'+str(i),decision='build_script_hit'))
    source=package/'sqlite3/sqlite3.c';original=source.read_bytes();stamp=source.stat()
    version=re.search(rb'#define SQLITE_VERSION\s+"([^"]+)"',original).group(1)
    replacement=version[:-1]+bytes([ord('9') if version[-1]!=ord('9') else ord('8')])
    edited_source=original.replace(b'"'+version+b'"',b'"'+replacement+b'"');assert edited_source!=original
    source.write_bytes(edited_source);os.utime(source,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
    changed=run('source-edit',decision='build_script_miss');assert changed['artifacts']['libsqlite3.a']!=reference['artifacts']['libsqlite3.a']
    probe=state/'probe.c';probe.write_text('extern const char* sqlite3_libversion(void); int puts(const char*); int main(void){puts(sqlite3_libversion());}\n')
    subprocess.run(['cc',str(probe),str(state/'out/libsqlite3.a'),'-o',str(state/'probe')],check=True,capture_output=True)
    assert subprocess.check_output([str(state/'probe')]).strip()==replacement
    source.write_bytes(original);os.utime(source,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
    same(reference,run('source-revert',decision='build_script_hit'))
    header=package/'sqlite3/sqlite3.h';original_header=header.read_bytes();hs=header.stat()
    edited_header=original_header.replace(b'copyright',b'copyrighT',1);assert edited_header!=original_header
    header.write_bytes(edited_header);os.utime(header,ns=(hs.st_atime_ns,hs.st_mtime_ns))
    same(reference,run('header-edit',decision='build_script_miss'))
    header.write_bytes(original_header);os.utime(header,ns=(hs.st_atime_ns,hs.st_mtime_ns))
    same(reference,run('header-revert',decision='build_script_hit'))
    direct_flags=run('direct-flags',False,extra={'LIBSQLITE3_FLAGS':'SQLITE_OMIT_DEPRECATED'})
    same(direct_flags,run('guarded-flags',decision='build_script_bypass',extra={'LIBSQLITE3_FLAGS':'SQLITE_OMIT_DEPRECATED'}))
    direct_failure=run('direct-failed-compiler',False,extra={'CC_FORCE_DISABLE':'1'},success=False)
    guarded_failure=run('failed-compiler',decision='build_script_bypass',extra={'CC_FORCE_DISABLE':'1'},success=False)
    same(direct_failure,guarded_failure)
    assert direct_failure['exit_code']==guarded_failure['exit_code']
    same(reference,run('after-failure',decision='build_script_hit'))
    (state/'out/libsqlite3.a').write_bytes(b'caller output tampering')
    same(reference,run('after-output-tampering',decision='build_script_hit'))
    corrupted=set()
    for entry_path in (state/'cache/entries').iterdir():
        entry=json.loads(entry_path.read_bytes()[65:])
        for output in entry['outputs']:
            if output['path'].endswith('/libsqlite3.a'):
                blob=output['hash'];(state/'cache/blobs'/blob[:2]/blob).write_bytes(b'corrupt')
                corrupted.add(blob)
    assert corrupted
    same(reference,run('corrupt-blob-repair',decision='build_script_miss'))
    same(reference,run('after-blob-repair',decision='build_script_hit'))
    report=dict(completed=True,diagnostic=True,scope='actual libsqlite3-sys 0.30.1 bundled script, private source copy, declared default Apple tools; no project speed claim',
                binary_sha256=digest(binary),runner_sha256=digest(Path(__file__)),real_sha256=digest(real),contract_sha256=digest(args.contract),cargo_log_sha256=digest(args.cargo_log),
                samples=rows,preserved_mtime_source_edit_runtime_verified=True,header_edit_and_reverts_verified=True,guarded_flags_and_failures_passthrough=True,output_tampering_isolated_and_corrupt_blobs_repaired=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({r['label']:round(r['seconds'],4) for r in rows}))


if __name__=='__main__':main()
