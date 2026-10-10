"""Profile an actual captured final Harness request after the full run completes.

Existing compiled dependencies are read only. This is an isolated diagnostic,
not a full-build benchmark. Source edits are checked by the separate full runner.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from benchmark_storage import save_report
from macho_staging import validate_staging_difference
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from compiler_phase_profiles import collect


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary',type=Path)
    p.add_argument('--request',type=Path,required=True)
    p.add_argument('--compiled-target',type=Path,required=True)
    p.add_argument('--reference-report',type=Path,required=True)
    p.add_argument('--state',type=Path,required=True)
    args=p.parse_args()
    request=json.loads(args.request.read_text());reference=json.loads(args.reference_report.read_text())
    assert reference.get('completed') and reference['tracked_sources_unchanged']
    command=request['args'][:];assert command[command.index('--crate-name')+1]=='harness'
    project=Path(request['cwd']);target=args.compiled_target.resolve()
    old=Path(command[command.index('--out-dir')+1]).parents[1]
    command=[x.replace(str(old),str(target)) for x in command]
    source_hashes=reference['tracked_rust_and_manifest_hashes']
    for name,digest in source_hashes.items():assert sha(project/name)==digest,name
    root=args.state.resolve();root.mkdir(mode=0o700,parents=True,exist_ok=False)
    out=root/'out';out.mkdir();command[command.index('--out-dir')+1]=str(out)
    suffix=next(x.split('=',1)[1] for x in command if x.startswith('extra-filename='))
    executable=out/('harness'+suffix);depname=executable.name+'.d'
    # Rust's dep-info records compile-time env inputs. Retain original values
    # privately; never publish the environment map or argument paths.
    dep=target/'release/deps'/depname;env_records={};env_absent=[]
    for line in dep.read_text().splitlines():
        if line.startswith('# env-dep:'):
            key,separator,value=line[len('# env-dep:'):].partition('=')
            if separator:env_records[key]=value
            else:env_absent.append(key)
    env={k:v for k,v in os.environ.items() if not k.startswith(('R2_','KACHE_','NANOCOMPILE_')) and k not in ('RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER','RUSTC_BOOTSTRAP')}
    for key in env_absent:env.pop(key,None)
    env.update(env_records)
    env.update(RUSTUP_TOOLCHAIN='1.97.1',SOURCE_DATE_EPOCH=str(reference['source_date_epoch']),NANOCOMPILE_DIR=str(root/'cache'),NANOCOMPILE_TRACE='1',NANOCOMPILE_COMPILER_PROFILE='1',NANOCOMPILE_PROC_MACROS='reported',NANOCOMPILE_EXECUTABLE_PRODUCERS='1',NANOCOMPILE_THIN_LTO_PRODUCERS='1')
    report=dict(completed=False,diagnostic=True,scope='isolated actual final Harness request; existing read-only dependencies; reported macro inputs; no build speed or GUI claim',binary_sha256=sha(args.binary),runner_sha256=sha(Path(__file__)),request_sha256=sha(args.request),reference_report_sha256=sha(args.reference_report),dep_info_sha256=sha(dep),compile_environment_keys=sorted(env_records),compile_environment_absent_keys=sorted(env_absent),samples=[])
    capture=root/'capture';capture.mkdir()
    save=lambda:save_report(root/'report.json',report)
    def run(label,wrapped=True,decision=None):
        shutil.rmtree(out);out.mkdir();start=time.perf_counter()
        q=subprocess.run(([str(args.binary.resolve())]+command) if wrapped else command,cwd=project,env=env,capture_output=True)
        seconds=time.perf_counter()-start
        (capture/(label+'.stdout')).write_bytes(q.stdout);(capture/(label+'.stderr')).write_bytes(q.stderr)
        (capture/(label+'.json')).write_text(json.dumps(dict(args=command,exit_code=q.returncode)))
        files={f.name:dict(sha256=sha(f),mode=oct(f.stat().st_mode&0o777)) for f in out.iterdir() if f.is_file()}
        row=dict(label=label,seconds=seconds,exit_code=q.returncode,files=files,stdout_sha256=hashlib.sha256(q.stdout).hexdigest(),stderr_sha256=hashlib.sha256(q.stderr).hexdigest());report['samples'].append(row);save()
        assert q.returncode==0,q.stderr.decode(errors='replace')
        assert set(files)=={executable.name,depname},files
        if decision:assert ('nanocompile: '+decision).encode() in q.stderr,q.stderr.decode(errors='replace')
        installed=root/'harness';shutil.copy2(executable,installed)
        probe=subprocess.run([str(installed),'--help'],capture_output=True,env=env)
        (root/(label+'.help.stdout')).write_bytes(probe.stdout)
        (root/(label+'.help.stderr')).write_bytes(probe.stderr)
        row.update(cli_help_exit_code=probe.returncode,cli_help_stdout_sha256=hashlib.sha256(probe.stdout).hexdigest(),cli_help_stderr_sha256=hashlib.sha256(probe.stderr).hexdigest());save()
        assert probe.returncode==0
        expected=next(b['cli_help_sha256'] for b in reference['builds'] if b['implementation']=='nanocompile')
        assert hashlib.sha256(probe.stdout).hexdigest()==expected
        subprocess.run(['codesign','--verify','--strict',str(executable)],check=True,capture_output=True)
        row.update(cli_help_valid=True,cli_help_sha256=expected);save();print(label,round(seconds,6),flush=True)
        return files
    try:
        direct=run('direct',False);direct_bytes=executable.read_bytes()
        cold=run('cold',decision='miss: compiling executable producer')
        assert cold[depname]==direct[depname]
        report['direct_staging_difference']=validate_staging_difference(direct_bytes,executable.read_bytes());save()
        for n in range(3):assert run('hit-'+str(n),decision='hit: executable producer')==cold
        subprocess.run([str(args.binary.resolve()),'clear'],env=env,cwd=project,check=True,capture_output=True)
        assert run('cold-confirmation',decision='miss: compiling executable producer')==cold
        report['compiler_phase_profiles']=collect(capture)
        for name,digest in source_hashes.items():assert sha(project/name)==digest,name
        report.update(completed=True,tracked_sources_unchanged=True);save()
    except BaseException as error:
        if isinstance(error,subprocess.CalledProcessError):
            (root/'tool-failure.stdout').write_bytes(error.stdout or b'');(root/'tool-failure.stderr').write_bytes(error.stderr or b'')
        report['failure']=dict(type=type(error).__name__,message=str(error));save();raise


if __name__=='__main__':main()
