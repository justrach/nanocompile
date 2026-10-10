"""Replay a captured Harness tree-sitter-highlight request with a real API edit.

Dependency/native directories are read only. Sources, outputs and cache are private.
This isolates one compilation; these measurements are not whole-build results.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import time
from benchmark_storage import save_report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary', type=Path)
    p.add_argument('--request', type=Path, required=True)
    p.add_argument('--state', type=Path, required=True)
    args = p.parse_args()
    root = args.state.resolve(); root.mkdir(mode=0o700, parents=True, exist_ok=False)
    request = json.loads(args.request.read_text()); command = request['args'][:]
    assert command[command.index('--crate-name')+1] == 'tree_sitter_highlight'
    assert request['exit_code'] == 0
    project = root/'project'; shutil.copytree(request['cwd'], project)
    for i, value in enumerate(command):
        if value.startswith(request['cwd']+'/'): command[i] = str(project)+value[len(request['cwd']):]
    out = root/'out'; out.mkdir(); command[command.index('--out-dir')+1] = str(out)
    binary = args.binary.resolve()
    env = {k:v for k,v in os.environ.items() if not k.startswith(('NANOCOMPILE_', 'R2_', 'KACHE_')) and k not in ('RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER')}
    env.update(NANOCOMPILE_DIR=str(root/'cache'), NANOCOMPILE_TRACE='1', NANOCOMPILE_PROC_MACROS='reported', NANOCOMPILE_RUST_STATICLIB='1', RUSTUP_TOOLCHAIN='1.97.1')
    report = dict(completed=False, scope='isolated actual Harness dependency request; private source copy; existing read-only compiled dependencies; reported macro inputs opt-in matches full Harness trials; R2 off; OS caches unflushed', binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), request_sha256=hashlib.sha256(args.request.read_bytes()).hexdigest(), samples=[])
    save = lambda: save_report(root/'report.json', report)
    def run(label, wrapped=True, enabled=True, decision=None):
        shutil.rmtree(out); out.mkdir()
        e = dict(env, NANOCOMPILE_RUST_STATICLIB='1' if enabled else '0')
        start = time.perf_counter()
        q = subprocess.run(([str(binary)]+command) if wrapped else command, cwd=project, env=e, capture_output=True)
        seconds = time.perf_counter()-start
        (root/(label+'.stdout')).write_bytes(q.stdout); (root/(label+'.stderr')).write_bytes(q.stderr)
        files = {f.name:dict(sha256=hashlib.sha256(f.read_bytes()).hexdigest(), mode=oct(f.stat().st_mode&0o777)) for f in out.iterdir() if f.is_file()}
        report['samples'].append(dict(label=label, seconds=seconds, exit_code=q.returncode, files=files, stdout_sha256=hashlib.sha256(q.stdout).hexdigest(), stderr_sha256=hashlib.sha256(q.stderr).hexdigest())); save()
        assert q.returncode == 0, q.stderr.decode(errors='replace')
        assert len(files)==3 and {Path(x).suffix for x in files}=={'.d','.rlib','.a'}, files
        if decision: assert ('nanocompile: '+decision).encode() in q.stderr, q.stderr.decode(errors='replace')
        print(label, round(seconds,6), flush=True)
        return files
    c = root/'probe.c'
    c.write_text('#include <stdio.h>\nextern void *ts_highlight_buffer_new(void); extern unsigned ts_highlight_buffer_len(const void *); extern void ts_highlight_buffer_delete(void *); int main(){void *b=ts_highlight_buffer_new(); printf("%u\\n",ts_highlight_buffer_len(b));ts_highlight_buffer_delete(b);}\n')
    r = root/'probe.rs'
    r.write_text('unsafe extern "C" {fn ts_highlight_buffer_new()->*mut std::ffi::c_void;fn ts_highlight_buffer_len(p:*const std::ffi::c_void)->u32;fn ts_highlight_buffer_delete(p:*mut std::ffi::c_void);} fn main(){let _h=tree_sitter_highlight::Highlighter::new();unsafe{let p=ts_highlight_buffer_new();println!("{}",ts_highlight_buffer_len(p));ts_highlight_buffer_delete(p);}}\n')
    dependency = next(x for x in command if x.startswith('dependency='))
    def probes(expected):
        subprocess.run(['/usr/bin/cc',str(c),str(next(out.glob('*.a'))),'-liconv','-o',str(root/'c-probe')],check=True,capture_output=True)
        subprocess.run([command[0],str(r),'--edition=2024','--extern','tree_sitter_highlight='+str(next(out.glob('*.rlib'))),'-L',dependency,'-o',str(root/'rust-probe')],env=env,check=True,capture_output=True)
        for name in ('c-probe','rust-probe'): assert subprocess.check_output([str(root/name)]).strip()==str(expected).encode()
    edit = project/'src/c_lib.rs'; original = edit.read_bytes(); marker = b'this.renderer.html.len() as u32'
    assert original.count(marker)==1
    try:
        direct = run('direct',False); probes(0)
        assert run('cold',decision='miss: compiling')==direct; probes(0)
        for n in range(3):
            for enabled in ((False,True) if n%2==0 else (True,False)):
                assert run(('hit-' if enabled else 'default-off-')+str(n), enabled=enabled, decision='hit' if enabled else 'bypass: UnsupportedCrateType')==direct
                probes(0)
        edit.write_bytes(original.replace(marker, marker+b' + 1'))
        changed = run('edited-direct',False); assert changed!=direct; probes(1)
        assert run('edited-miss',decision='miss: compiling')==changed; probes(1)
        assert run('edited-hit',decision='hit')==changed; probes(1)
        edit.write_bytes(original)
        assert run('reverted-hit',decision='hit')==direct; probes(0)
        report['hit_median_seconds']=statistics.median(x['seconds'] for x in report['samples'] if x['label'].startswith('hit-'))
        report['default_off_median_seconds']=statistics.median(x['seconds'] for x in report['samples'] if x['label'].startswith('default-off-'))
        report['completed']=True; save()
    except BaseException as e:
        if isinstance(e,subprocess.CalledProcessError):
            (root/'tool-failure.stdout').write_bytes(e.stdout or b''); (root/'tool-failure.stderr').write_bytes(e.stderr or b'')
        report['failure']=dict(type=type(e).__name__,message=str(e));save();raise
    finally: edit.write_bytes(original)


if __name__=='__main__': main()
