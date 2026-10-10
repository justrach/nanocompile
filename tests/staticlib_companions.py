"""Actual std-linked Rust/C companion artifacts and object-code invalidation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import time
from benchmark_storage import save_report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary', type=Path)
    p.add_argument('--state', type=Path, required=True)
    p.add_argument('--profile', action='store_true', help='verify ordinary compiler/restore diagnostic stages')
    args = p.parse_args()
    root = args.state.resolve(); root.mkdir(parents=True, mode=0o700, exist_ok=False)
    binary = args.binary.resolve()
    rustc = subprocess.check_output(['rustup','which','--toolchain','1.97.1','rustc'],text=True).strip()
    env = {k:v for k,v in os.environ.items() if not k.startswith(('NANOCOMPILE_','R2_','KACHE_')) and k not in ('RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER')}
    env.update(NANOCOMPILE_DIR=str(root/'cache'), NANOCOMPILE_TRACE='1', NANOCOMPILE_RUST_STATICLIB='1', RUSTUP_TOOLCHAIN='1.97.1')
    if args.profile:env['NANOCOMPILE_COMPILER_PROFILE']='1'
    deps=root/'deps';deps.mkdir();out=root/'out';out.mkdir()
    dep=root/'dep.rs';source=root/'source.rs'
    source.write_text('extern crate dep; #[unsafe(no_mangle)] pub extern "C" fn nano_probe()->i32 {format!("{}",dep::value()).parse::<i32>().unwrap()}\n')
    dep.write_text('pub fn value()->i32{41}\n')
    report=dict(completed=False,compiler_profile=args.profile,binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),samples=[])
    def save():save_report(root/'report.json',report)
    def dependency(extra=()):
        subprocess.run([rustc,str(dep),'--crate-name','dep','--crate-type','rlib','--edition=2024','--emit=dep-info,metadata,link','-C','opt-level=3','--out-dir',str(deps),*extra],env=env,check=True,capture_output=True)
    dependency()
    base=[rustc,str(source),'--crate-name','companion','--edition=2024','--emit=dep-info,link','--out-dir',str(out),'-C','opt-level=3','--extern','dep='+str(deps/'libdep.rlib'),'-L','dependency='+str(deps)]
    def run(label,types=('lib','staticlib'),wrapped=True,decision=None,extra=(),compiler=None,success=True):
        shutil.rmtree(out);out.mkdir()
        command=base[:]
        if compiler is not None:command[0]=str(compiler)
        for t in types:command+=['--crate-type',t]
        command+=list(extra)
        start=time.perf_counter();q=subprocess.run(([str(binary)]+command) if wrapped else command,cwd=root,env=env,capture_output=True)
        (root/(label+'.stdout')).write_bytes(q.stdout);(root/(label+'.stderr')).write_bytes(q.stderr)
        files={f.name:dict(sha256=hashlib.sha256(f.read_bytes()).hexdigest(),mode=oct(f.stat().st_mode&0o777)) for f in out.iterdir() if f.is_file()}
        normalized=b'\n'.join(line for line in q.stderr.splitlines() if not line.startswith(b'nanocompile: '))
        row=dict(label=label,exit_code=q.returncode,seconds=time.perf_counter()-start,files=files,stdout_sha256=hashlib.sha256(q.stdout).hexdigest(),stderr_sha256=hashlib.sha256(q.stderr).hexdigest(),normalized_stderr_sha256=hashlib.sha256(normalized).hexdigest());report['samples'].append(row);save()
        assert (q.returncode==0)==success,q.stderr.decode(errors='replace')
        if success:assert {'companion.d','libcompanion.rlib','libcompanion.a'}<=files.keys(),files
        if decision:assert ('nanocompile: '+decision).encode() in q.stderr,q.stderr.decode(errors='replace')
        if args.profile and wrapped and decision=='hit':
            for stage in ('compiler.plan','compiler.prepare_identity','compiler.locks_configuration',
                          'compiler.restore','compiler.total','restore.input_validation','restore.materialization'):
                assert ('nanocompile: compiler-phase '+stage+' ns=').encode() in q.stderr,q.stderr.decode(errors='replace')
        elif not args.profile:assert b'nanocompile: compiler-phase ' not in q.stderr
        print(label,round(row['seconds'],4),flush=True)
        return files
    c=root/'probe.c';c.write_text('#include <stdio.h>\nextern int nano_probe(void);int main(){printf("%d\\n",nano_probe());}\n')
    r=root/'probe.rs';r.write_text('fn main(){println!("{}",companion::nano_probe());}\n')
    def probes(expected, external=()):
        subprocess.run(['/usr/bin/cc',str(c),str(out/'libcompanion.a'),*map(str,external),'-liconv','-o',str(root/'c-probe')],check=True,capture_output=True)
        subprocess.run([rustc,str(r),'--edition=2024','--extern','companion='+str(out/'libcompanion.rlib'),'-L','dependency='+str(deps),*sum((['-L','native='+str(Path(x).parent)] for x in external),[]),'-o',str(root/'rust-probe')],env=env,check=True,capture_output=True)
        for name in ('c-probe','rust-probe'):assert subprocess.check_output([str(root/name)]).strip()==str(expected).encode()
    try:
        direct=run('direct',wrapped=False);probes(41)
        assert run('cold',decision='miss: compiling')==direct;probes(41)
        assert run('hit',decision='hit')==direct;probes(41)
        for n,types in enumerate((('staticlib','lib'),('rlib','staticlib'),('staticlib','rlib'),('lib,staticlib',))):
            reference=run('order-direct-'+str(n),types,False)
            assert run('order-cold-'+str(n),types,decision='miss: compiling')==reference
            assert run('order-hit-'+str(n),types,decision='hit')==reference;probes(41)
        st=dep.stat();dep.write_text('pub fn value()->i32{42}\n');os.utime(dep,ns=(st.st_atime_ns,st.st_mtime_ns));dependency()
        changed=run('dependency-edit',decision='miss: compiling');assert changed!=direct;probes(42)
        assert run('dependency-direct',wrapped=False)==changed
        assert run('dependency-hit',decision='hit')==changed;probes(42)
        dep.write_text('pub fn value()->i32{41}\n');dependency()
        assert run('dependency-revert',decision='hit')==direct;probes(41)
        # A corrupt companion must invalidate the whole restore, never omit .a.
        for entry in (root/'cache/entries').iterdir():
            data=json.loads(entry.read_bytes()[65:])
            for output in data['outputs']:
                if output['path'].endswith('.a'):
                    digest=output['hash'];blob=root/'cache/blobs'/digest[:2]/digest
                    if blob.exists():blob.write_bytes(b'corrupt')
        assert run('archive-repair',decision='miss: compiling')==direct;probes(41)
        assert run('repaired-hit',decision='hit')==direct
        env.pop('NANOCOMPILE_RUST_STATICLIB')
        assert run('default-refusal',decision='bypass: UnsupportedCrateType')==direct
        env['NANOCOMPILE_RUST_STATICLIB']='1'
        for name,extra in [('debug',('-C','debuginfo=1')),('target',('--target','aarch64-apple-darwin')),('dynamic',('-C','prefer-dynamic=no')),('lto',('-C','lto=off'))]:
            expected=run(name+'-direct',wrapped=False,extra=extra)
            assert run(name+'-refusal',extra=extra,decision='bypass: UnsupportedStaticlibConfiguration')==expected
        proxy=root/'rustc-proxy';proxy.write_text('#!/bin/sh\nexec '+shlex.quote(rustc)+' "$@"\n');proxy.chmod(0o700)
        assert run('proxy-refusal',compiler=proxy,decision='bypass: compiler identity unavailable (UnsupportedCompilerScript)')==direct
        original=source.read_bytes();source.write_text('pub fn broken(\n')
        run('failed-direct',wrapped=False,success=False)
        run('failed-wrapper',decision='miss: compiling',success=False)
        for field in ('exit_code','stdout_sha256','normalized_stderr_sha256'):
            assert report['samples'][-2][field]==report['samples'][-1][field]
        source.write_bytes(original);assert run('after-failure',decision='hit')==direct
        native=root/'native';native.mkdir();csource=native/'foreign.c'
        dep.write_text('unsafe extern "C" {fn foreign()->i32;} pub fn value()->i32{unsafe{foreign()}}\n')
        def native_dependency(value):
            csource.write_text('int foreign(void){return '+str(value)+';}\n')
            subprocess.run(['/usr/bin/cc','-c',str(csource),'-o',str(native/'foreign.o')],check=True,capture_output=True)
            subprocess.run(['/usr/bin/ar','rcs',str(native/'libffi.a'),str(native/'foreign.o')],env=dict(env,ZERO_AR_DATE='1'),check=True,capture_output=True)
            dependency(('-L','native='+str(native),'-l','static=ffi'))
        native_dependency(41)
        native_direct=run('native-direct',wrapped=False);probes(41)
        assert run('native-cold',decision='miss: compiling')==native_direct
        assert run('native-hit',decision='hit')==native_direct;probes(41)
        metadata=hashlib.sha256((deps/'libdep.rmeta').read_bytes()).hexdigest()
        native_dependency(42)
        assert hashlib.sha256((deps/'libdep.rmeta').read_bytes()).hexdigest()==metadata,'Native edit unexpectedly changed dependency metadata; object-only gate not established'
        native_changed=run('native-object-edit',decision='miss: compiling');assert native_changed!=native_direct;probes(42)
        assert run('native-edited-direct',wrapped=False)==native_changed
        assert run('native-edited-hit',decision='hit')==native_changed;probes(42)
        native_dependency(41)
        assert run('native-object-revert',decision='hit')==native_direct;probes(41)
        # An unbundled transitive native input remains external to
        # the staticlib. Changing it must affect linked executables while the
        # cached archive itself remains equal to a fresh direct compilation.
        dep.write_text('#[link(name="ffi", kind="static", modifiers="-bundle")] unsafe extern "C" {fn foreign()->i32;} pub fn value()->i32{unsafe{foreign()}}\n')
        dependency()
        unbundled=run('unbundled-direct',wrapped=False);probes(41,(native/'libffi.a',))
        assert run('unbundled-cold',decision='miss: compiling')==unbundled
        assert run('unbundled-hit',decision='hit')==unbundled;probes(41,(native/'libffi.a',))
        archive=native/'libffi.a';stamp=archive.stat();dep_hash=hashlib.sha256((deps/'libdep.rlib').read_bytes()).hexdigest()
        csource.write_text('int foreign(void){return 42;}\n')
        subprocess.run(['/usr/bin/cc','-c',str(csource),'-o',str(native/'foreign.o')],check=True,capture_output=True)
        subprocess.run(['/usr/bin/ar','rcs',str(archive),str(native/'foreign.o')],env=dict(env,ZERO_AR_DATE='1'),check=True,capture_output=True)
        os.utime(archive,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        assert hashlib.sha256((deps/'libdep.rlib').read_bytes()).hexdigest()==dep_hash
        assert run('unbundled-external-edit',decision='hit')==unbundled;probes(42,(archive,))
        assert run('unbundled-edited-direct',wrapped=False)==unbundled;probes(42,(archive,))
        # A hidden native input on the compiling crate is refused;
        # unlike an upstream -bundle library, this could be read during assembly.
        source.write_text('#[link(name="ffi", kind="static")] unsafe extern "C" {fn foreign()->i32;} #[unsafe(no_mangle)] pub extern "C" fn nano_probe()->i32{unsafe{foreign()}}\n')
        own=run('own-hidden-native-direct',wrapped=False,extra=('-L','native='+str(native)))
        for n in range(2):
            assert run('own-hidden-native-refusal-'+str(n),decision='uncached: HiddenNativeLinkInput',extra=('-L','native='+str(native)))==own
        probes(42)
        report['completed']=True;save()
    except BaseException as error:
        if isinstance(error,subprocess.CalledProcessError):
            (root/'tool-failure.stdout').write_bytes(error.stdout or b'')
            (root/'tool-failure.stderr').write_bytes(error.stderr or b'')
        report['failure']=dict(type=type(error).__name__,message=str(error));save();raise


if __name__=='__main__':main()
