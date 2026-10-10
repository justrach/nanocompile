"""Exercise real Cargo script reuse, declared edits, installed links and fallback streams."""
import argparse
import hashlib
import json
import os
import sys
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
    checks = []
    with tempfile.TemporaryDirectory(prefix='nano script cache ') as tmp:
        root = Path(tmp)
        project, target, cache, installed = [root / x for x in ('project', 'target', 'cache', 'installed')]
        (project / 'src').mkdir(parents=True)
        (installed / 'a').mkdir(parents=True)
        (installed / 'b').mkdir()
        (installed / 'a/value').write_text('10')
        (installed / 'b/value').write_text('20')
        (installed / 'include').symlink_to('a', target_is_directory=True)
        (project / 'input').write_text('42')
        # Exercise the large dependency-graph parallel restore path.
        (project/'declared-data.bin').write_bytes(b'x'*(9*1024*1024))
        for i in range(32): (project/('declared-'+str(i))).write_text(str(i))
        (project / 'Cargo.toml').write_text('[package]\nname="script-fixture"\nversion="0.1.0"\nedition="2021"\n')
        (project / 'src/main.rs').write_text('include!(concat!(env!("OUT_DIR"), "/value.rs")); fn main(){println!("{}", VALUE);}')
        (project / 'build.rs').write_text(r'''
use std::{env,fs,io::{self,Read},path::PathBuf};
fn main(){
 let mut stdin=String::new(); io::stdin().read_to_string(&mut stdin).unwrap();
 eprintln!("script ran; stdin={}", stdin);
 if env::var("MODE").unwrap_or_default()=="fail" {std::process::exit(7)}
 if env::var("MODE").unwrap_or_default()=="jobserver" {
  extern "C" {fn fcntl(fd:i32,cmd:i32,...)->i32;}
  let flags=env::var("CARGO_MAKEFLAGS").unwrap();
  for fd in flags.strip_prefix("--jobserver-auth=").unwrap().split(',') {
   assert!(unsafe{fcntl(fd.parse().unwrap(),1)}>=0,"jobserver descriptor lost");
  }
 }
 let out=PathBuf::from(env::var("OUT_DIR").unwrap());
 let input:u32=fs::read_to_string("input").unwrap().trim().parse().unwrap();
 let header:u32=fs::read_to_string(PathBuf::from(env::var("INSTALLED").unwrap()).join("include/value")).unwrap().trim().parse().unwrap();
 let extra:u32=env::var("EXTRA").unwrap().parse().unwrap();
 fs::write(out.join("value.rs"),format!("const VALUE:u32={};",input+header+extra+stdin.len() as u32)).unwrap();
 fs::write(out.join("second.txt"),"complete output set").unwrap();
 if env::var("MODE").unwrap_or_default()=="nested" {fs::create_dir_all(out.join("empty")).unwrap();}
 println!("cargo:rerun-if-changed=input");
}
''')
        tool=root/'declared-tool';tool.write_text('#!/bin/sh\nexit 0\n');tool.chmod(0o700)
        config = root / 'contract.json'
        config.write_text(json.dumps(dict(schema=1, packages=[dict(package='script-fixture', inputs=[str(project)], installed_inputs=[str(installed)],tools=[str(tool)],apple_tools=['ar'] if sys.platform=='darwin' else [])])))
        env = {k:v for k,v in os.environ.items() if not k.startswith(('NANOCOMPILE_', 'R2_', 'KACHE_')) and k not in ('RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER')}
        env.update(RUSTUP_TOOLCHAIN='1.97.1', RUSTC_WRAPPER=str(binary), CARGO_TARGET_DIR=str(target),
                   NANOCOMPILE_DIR=str(cache), NANOCOMPILE_BUILD_SCRIPTS_FILE=str(config),
                   INSTALLED=str(installed), EXTRA='1', NANOCOMPILE_TRACE='1')
        def events():
            return (cache/'events').read_text().splitlines() if (cache/'events').exists() else []
        def cargo(expected, decision):
            shutil.rmtree(target, ignore_errors=True)
            before=len(events())
            q=subprocess.run(['cargo','build','--release','--offline'],cwd=project,env=env,capture_output=True)
            assert q.returncode==0,q.stderr.decode(errors='replace')
            assert decision in events()[before:],(decision,events()[before:],q.stderr.decode(errors='replace'))
            actual=subprocess.check_output([str(target/'release/script-fixture')]).decode().strip()
            assert actual==str(expected),(actual,expected)
            return hashlib.sha256((target/'release/script-fixture').read_bytes()).hexdigest()
        first=cargo(53,'build_script_miss')
        assert cargo(53,'build_script_hit')==first
        checks.append('real Cargo cold execution and warm restored executable agree')
        mtime=tool.stat().st_mtime_ns
        tool.write_text('#!/bin/sh\nexit 1\n');os.utime(tool,ns=(mtime,mtime))
        cargo(53,'build_script_miss')
        tool.write_text('#!/bin/sh\nexit 0\n');os.utime(tool,ns=(mtime,mtime))
        assert cargo(53,'build_script_hit')==first
        checks.append('declared tool bytes with preserved mtime invalidate and revert safely')
        if sys.platform=='darwin':checks.append('live xcrun-selected system-only archiver participates in cold and warm identities')

        mtime=(project/'input').stat().st_mtime_ns
        (project/'input').write_text('43');os.utime(project/'input',ns=(mtime,mtime))
        cargo(54,'build_script_miss')
        (project/'input').write_text('42');os.utime(project/'input',ns=(mtime,mtime))
        assert cargo(53,'build_script_hit')==first
        checks.append('same-size preserved-mtime mutable source edit and revert')
        header=installed/'a/value';mtime=header.stat().st_mtime_ns
        header.write_text('11');os.utime(header,ns=(mtime,mtime))
        cargo(54,'build_script_miss')
        header.write_text('10');os.utime(header,ns=(mtime,mtime))
        cargo(53,'build_script_hit')
        (installed/'include').unlink();(installed/'include').symlink_to('b',target_is_directory=True)
        cargo(63,'build_script_miss')
        (installed/'b/new-header').write_text('membership')
        cargo(63,'build_script_miss')
        checks.append('linked installed target content, link retarget and directory membership invalidate')
        env['EXTRA']='2';cargo(64,'build_script_miss');cargo(64,'build_script_hit')
        checks.append('environment changes invalidate execution')
        # Save an installed Cargo shim and its real executable for transparent
        # execution tests independent of Cargo target reconstruction.
        script=next((target/'release/build').glob('*/build-script-build'))
        launch=json.loads((script.parent/'nano-build-script.json').read_text())
        saved=root/'saved';saved.mkdir()
        shim=saved/'build-script-build';shutil.copyfile(script,shim);shim.chmod(0o700)
        real=saved/'real';shutil.copyfile(launch['real'],real);real.chmod(0o700)
        (saved/'nano-build-script.json').write_text(json.dumps(dict(real=str(real))))
        manual=root/'manual'
        menv=dict(env,OUT_DIR=str(manual),CARGO_PKG_NAME='script-fixture')
        def launch_script(decision, payload=None, code=0, inherited=()):
            shutil.rmtree(manual,ignore_errors=True);manual.mkdir()
            before=len(events())
            if payload is None:
                with open('/dev/null','rb') as stream:q=subprocess.run([str(shim)],cwd=project,env=menv,stdin=stream,capture_output=True,pass_fds=inherited)
            else:q=subprocess.run([str(shim)],cwd=project,env=menv,input=payload,capture_output=True)
            assert q.returncode==code,(q.returncode,q.stderr)
            assert decision is None or decision in events()[before:],(decision,events()[before:],q.stderr)
            return q
        a=launch_script('build_script_miss');b=launch_script('build_script_hit')
        assert (a.stdout,a.stderr)==(b.stdout,b.stderr)
        assert 'VALUE:u32=64' in (manual/'value.rs').read_text()
        checks.append('restored stdout and stderr match executed streams')
        assert (manual/'second.txt').read_text()=='complete output set'
        assert not list(root.glob('.nano-script-*'))
        if os.geteuid()!=0:
            shutil.rmtree(manual);manual.mkdir(mode=0o750)
            root_mode=root.stat().st_mode & 0o777
            root.chmod(0o500)
            try:
                with open('/dev/null','rb') as stream:
                    failed=subprocess.run([str(shim)],cwd=project,env=menv,stdin=stream,capture_output=True)
                assert failed.returncode!=0,(failed.returncode,failed.stderr)
                assert not list(manual.iterdir()),list(manual.iterdir())
                assert not failed.stdout and b'script ran' not in failed.stderr
            finally:
                root.chmod(root_mode)
            assert not list(root.glob('.nano-script-*'))
            with open('/dev/null','rb') as stream:
                restored=subprocess.run([str(shim)],cwd=project,env=menv,stdin=stream,capture_output=True)
            assert restored.returncode==0,restored.stderr
            assert (restored.stdout,restored.stderr)==(a.stdout,a.stderr)
            assert manual.stat().st_mode & 0o777 == 0o750
            assert sorted(x.name for x in manual.iterdir())==['second.txt','value.rs']
            checks.append('staging permission failure leaves OUT_DIR empty without replay; subsequent atomic hit restores all outputs and permissions')
        launch_script('build_script_bypass',b'abc')
        assert 'VALUE:u32=67' in (manual/'value.rs').read_text()
        checks.append('non-null stdin bypass preserves incoming bytes')
        menv['MODE']='fail';launch_script('build_script_failed',code=7);launch_script('build_script_failed',code=7)
        checks.append('failed executions never cached and preserve exit code')
        menv['MODE']='nested';launch_script('build_script_miss');launch_script('build_script_miss')
        assert (manual/'empty').is_dir()
        checks.append('nested outputs execute each time rather than partially restoring')
        del menv['MODE']
        receipts=list((cache/'build-script-receipts').iterdir())
        for receipt in receipts:receipt.write_bytes(b'corrupt')
        launch_script('build_script_miss')
        checks.append('corrupt receipt reruns rather than accepting incomplete evidence')
        for blob in (cache/'blobs').rglob('*'):
            if blob.is_file():blob.write_bytes(b'bad')
        launch_script('build_script_miss')
        checks.append('corrupt output blobs rerun and produce correct output')
        fds=os.pipe()
        try:
            menv['MODE']='jobserver';menv['CARGO_MAKEFLAGS']='--jobserver-auth='+','.join(map(str,fds))
            launch_script('build_script_miss',inherited=fds)
            launch_script('build_script_hit',inherited=fds)
            menv['NANOCOMPILE_DISABLE']='1'
            launch_script(None,inherited=fds)
            del menv['NANOCOMPILE_DISABLE'];del menv['NANOCOMPILE_BUILD_SCRIPTS_FILE']
            launch_script(None,inherited=fds)
            checks.append('jobserver descriptors preserved on cache miss, disabled and missing-contract fallback')
        finally:
            for fd in fds:os.close(fd)
        del menv['MODE'];del menv['CARGO_MAKEFLAGS']
        menv['NANOCOMPILE_DISABLE']='1'
        with open('/dev/null','rb') as stream:q=subprocess.run([str(shim)],cwd=project,env=menv,stdin=stream,capture_output=True)
        assert q.returncode==0 and b'script ran' in q.stderr
        checks.append('disabled installed shim executes the real script')
        del menv['NANOCOMPILE_DISABLE']
        menv['NANOCOMPILE_BUILD_SCRIPTS_FILE']=str(config)
        menv['EXTRA']='3'
        directory=cache/'entries'
        mode=directory.stat().st_mode & 0o777
        prior_entries=set(directory.iterdir())
        directory.chmod(0o500)
        try:
            launch_script('build_script_miss')
            assert 'VALUE:u32=65' in (manual/'value.rs').read_text()
            if os.geteuid()!=0:assert set(directory.iterdir())==prior_entries
        finally:
            directory.chmod(mode)
        checks.append('cache-store permission failure preserves successful execution and correct output')

    report=dict(binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),checks=checks)
    args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()
