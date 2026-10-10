"""Guard the byte-pinned physical installation memo experiment (macOS arm64)."""
import argparse
import hashlib
import json
import os
import platform
import sys
from pathlib import Path
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('binary', type=Path)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
binary = args.binary.resolve()
env = {k:v for k,v in os.environ.items() if not k.startswith(('NANOCOMPILE_', 'KACHE_', 'R2_', 'LD_', 'DYLD_'))
       and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER')}
env.update(RUSTUP_TOOLCHAIN='1.97.1', NANOCOMPILE_TRACE='1')
compiler = subprocess.check_output(['rustup', 'which', 'rustc'], env=env, text=True).strip()
if platform.system() != 'Darwin' or platform.machine() != 'arm64' or hashlib.sha256(Path(compiler).read_bytes()).hexdigest() != '210df6794001b73ec3d453878707fa1e0bdcb63c427024a6e6574bbe5615a4da':
    args.output.write_text(json.dumps(dict(skipped=True, reason='Byte-pinned macOS arm64 Rust 1.97.1 fixture unavailable'))+'\n')
    print('SKIP: byte-pinned macOS arm64 Rust 1.97.1 fixture unavailable')
    sys.exit(0)
with tempfile.TemporaryDirectory(prefix='nano physical identity ') as temp:
    root = Path(temp)
    source = root/'lib.rs'
    source.write_text('pub fn answer()->u32 {42}\n')
    out = root/'out'; out.mkdir()
    env['NANOCOMPILE_DIR'] = str(root/'cache')
    a,b = root/'a',root/'b'; a.mkdir(); b.mkdir()
    command = [str(binary), compiler, str(source), '--crate-name', 'physical', '--crate-type', 'rlib',
               '--emit=dep-info,metadata,link', '--out-dir', str(out), '-L', 'dependency='+str(out)]
    records = []
    def run(cwd, extra):
        completed = subprocess.run(command, cwd=cwd, env=dict(env, **extra), check=True, capture_output=True)
        records.append(completed.stderr.decode())
        memos = [json.loads(p.read_bytes()[65:]) for p in (root/'cache/toolchains').iterdir()]
        return memos, hashlib.sha256((out/'libphysical.rlib').read_bytes()).hexdigest()
    first, digest = run(a, {'DYLD_FALLBACK_LIBRARY_PATH':str(a)})
    # Direct physical rustc does not select through rustup's cwd override.
    (b/'rust-toolchain.toml').write_text('[toolchain]\nchannel="1.98.1"\n')
    second, again = run(b, {'DYLD_FALLBACK_LIBRARY_PATH':str(b)})
    assert len(first)==len(second)==1, (len(first),len(second),records)
    assert first==second, 'Physical memo unexpectedly changed across cwd/fallback'
    def direct_digest(cwd, extra):
        subprocess.run(command[1:], cwd=cwd, env=dict(env, **extra), check=True, capture_output=True)
        return hashlib.sha256((out/'libphysical.rlib').read_bytes()).hexdigest()
    assert again == direct_digest(b, {'DYLD_FALLBACK_LIBRARY_PATH':str(b)})
    assert digest == direct_digest(a, {'DYLD_FALLBACK_LIBRARY_PATH':str(a)})
    original_state = source.stat()
    source.write_text('pub fn answer()->u32 {43}\n')
    os.utime(source, ns=(original_state.st_atime_ns, original_state.st_mtime_ns))
    edited_memos, edited = run(b, {'DYLD_FALLBACK_LIBRARY_PATH':str(b)})
    assert edited_memos == second and edited != again
    assert edited == direct_digest(b, {'DYLD_FALLBACK_LIBRARY_PATH':str(b)})
    source.write_text('pub fn answer()->u32 {42}\n')
    os.utime(source, ns=(original_state.st_atime_ns, original_state.st_mtime_ns))
    reverted_memos, reverted = run(b, {'DYLD_FALLBACK_LIBRARY_PATH':str(b)})
    assert reverted_memos == second and reverted == again
    assert first[0]['schema']==8 and first[0]['locations']['fallback_verified']
    assert all('toolchain: pinned physical installation memo' in record for record in records)
    # Other loader policies must not share that memo or locations shortcut.
    third, again = run(b, {'DYLD_LIBRARY_PATH':''})
    assert len(third)==2 and again==direct_digest(b, {'DYLD_LIBRARY_PATH':''})
    assert 'toolchain: pinned physical installation memo' not in records[-1]
    assert any(m['locations'] is None for m in third)
    # Exact tool bytes are required: a forwarding native binary is a proxy,
    # even if it is named rustc beneath an installation-shaped bin directory.
    proxy_root = root/'proxy'; (proxy_root/'bin').mkdir(parents=True)
    code = proxy_root/'proxy.c'
    code.write_text('#include <unistd.h>\nint main(int n,char **v){v[0]=REAL;execv(REAL,v);return 127;}'.replace('REAL',json.dumps(compiler)))
    proxy = proxy_root/'bin/rustc'
    subprocess.run(['cc',str(code),'-o',str(proxy)],check=True)
    command[1]=str(proxy)
    fourth, again = run(b,{})
    assert len(fourth)==3 and again==direct_digest(b, {})
    assert 'toolchain: pinned physical installation memo' not in records[-1]
report = dict(binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              checks=['two cwd and fallback values share one fully validated physical memo',
                      'new rustup cwd override does not change direct stock compiler selection',
                      'each compiled artifact matches direct rustc in its own working directory',
                      'same-size preserved-mtime source edits and reverts retain correct outputs without changing installation memo',
                      'DYLD_LIBRARY_PATH retains contextual identity and live queries',
                      'native proxy with installation-shaped path refuses shared memo'])
args.output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
