"""Real installed-command checks for Apple's compiler-owned CAS and passthrough."""
import argparse
import hashlib
import json
import mmap
import os
from pathlib import Path
import platform
import subprocess
import shlex
import shutil
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('binary', type=Path)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
binary = args.binary.resolve()
report = {'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
          'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'checks': []}
if platform.system() != 'Darwin':
    q = subprocess.run([str(binary), 'clang', '--version'], capture_output=True)
    assert q.returncode == 0
    report['checks'].append('non-Apple host compiler probe passthrough')
else:
    clang = subprocess.check_output(['xcrun', '--find', 'clang'], text=True).strip()
    sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
    report['compiler_version'] = subprocess.check_output([clang, '--version'], text=True)
    help_text = subprocess.check_output([clang, '-cc1', '--help'], text=True)
    driver_help = subprocess.check_output([clang, '--help-hidden'], text=True)
    capable = '-fcache-compile-job' in help_text and '-fcas-path' in help_text and '-fdepscan=' in driver_help and 'Apple clang version' in report['compiler_version']
    report['local_cas_capable'] = capable
    with tempfile.TemporaryDirectory(prefix='nano Clang command ') as tmp:
        root = Path(tmp)
        env = {k:v for k,v in os.environ.items() if not k.startswith(('NANOCOMPILE_', 'R2_', 'KACHE_')) and k != 'SDKROOT'}
        env.update(NANOCOMPILE_DIR=str(root/'cache'), NANOCOMPILE_CLANG_REMARKS='1')
        source, header, out = root/'x.c', root/'x.h', root/'x.o'
        source.write_text('#include <stdint.h>\n#include <TargetConditionals.h>\n#include "x.h"\nint32_t nano_probe(void) {return VALUE;}\n')
        header.write_text('#define VALUE 42\n')
        flags = ['-isysroot', sdk, '--target=arm64-apple-macosx', '-gfull', '-c', str(source), '-o', str(out)]
        def events():
            path = root/'cache/events'
            return path.read_text().splitlines() if path.exists() else []
        def run(extra=None):
            out.unlink(missing_ok=True)
            q = subprocess.run([str(binary), 'clang', *flags], cwd=root, env=env if extra is None else env|extra,
                               capture_output=True, check=True)
            return q, out.read_bytes()
        cold, first = run()
        before = events()
        warm, second = run()
        assert first == second
        if capable:
            assert 'clang_native_hit' in events()[len(before):]
            assert b'compile job cache miss' in cold.stderr and b'compile job cache hit' in warm.stderr
            direct = [clang, '-isysroot', sdk, '-fdepscan=inline', '-Xclang', '-fcas-path', '-Xclang', str(root/'direct-cas'),
                      '-Xclang', '-fcache-compile-job', '-Xclang', '-fcache-disable-replay', *flags]
            subprocess.run(direct, cwd=root, env=env, check=True, capture_output=True)
            assert out.read_bytes() == second
            report['checks'].append('C debug objects match replay-disabled compiler and exact warm replay')
            for source_name, contents in [('x.S','.text\n.globl _nano_asm_probe\n_nano_asm_probe:\n ret\n')]:
                asm = root/source_name
                asm.write_text(contents)
                command = [str(binary),'clang','-c',str(asm),'-o',str(out)]
                subprocess.run(command,cwd=root,env=env,check=True,capture_output=True)
                a = out.read_bytes()
                q = subprocess.run(command,cwd=root,env=env,check=True,capture_output=True)
                assert out.read_bytes()==a and b'compile job cache hit' in q.stderr
            report['checks'].append('preprocessed assembly exact replay')
            st = header.stat()
            header.write_text('#define VALUE 43\n')
            os.utime(header,ns=(st.st_atime_ns,st.st_mtime_ns))
            changed, obj = run()
            assert obj != first and b'compile job cache miss' in changed.stderr
            report['checks'].append('same-size preserved-mtime header invalidation')
            with header.open('r+b') as f:
                with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_WRITE) as mm:
                    mm[14:16]=b'44'
                    _, old=run()
                    state=header.stat()
                    mm[15:16]=b'5'
                    after=header.stat()
                    q,new=run()
                    assert new!=old and b'compile job cache miss' in q.stderr
                    report['dirty_mmap_metadata_unchanged']=(state.st_ino,state.st_size,state.st_mtime_ns,state.st_ctime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
            report['checks'].append('already-dirty unflushed mmap header invalidation')
            spy = root/'selection-spy'
            spy.mkdir()
            query_log = root/'selection.log'
            real_xcrun = shutil.which('xcrun',path=env.get('PATH'))
            script = spy/'xcrun'
            script.write_text('#!/bin/sh\nprintf \'%s\\n\' "$*" >> '+shlex.quote(str(query_log))+'\nexec '+shlex.quote(real_xcrun)+' "$@"\n')
            script.chmod(0o700)
            spy_env=env|{'PATH':str(spy)+os.pathsep+env.get('PATH','')}
            live_flags=flags[2:]
            for _ in range(2):
                subprocess.run([str(binary),'clang',*live_flags],cwd=root,env=spy_env,check=True,capture_output=True)
            queries=query_log.read_text().splitlines()
            assert queries.count('--find clang')==2 and queries.count('--sdk macosx --show-sdk-path')==2,queries
            report['checks'].append('compiler and SDK selection queried on both eligible lookups')
            before = events()
            _, _ = run({'NANOCOMPILE_CLANG_REMARKS':'0'})
            assert 'clang_native_run' in events()[len(before):] and 'clang_native_hit' not in events()[len(before):]
            report['checks'].append('normal streaming mode caches without reporting unobserved hits')
            cas = root/'cache/native-clang'
            assert cas.exists() and all((x.stat().st_mode & 0o777)==0o700 for x in cas.iterdir() if x.is_dir())
            subprocess.run([str(binary),'clear'],env=env,check=True,capture_output=True)
            assert not list(cas.iterdir())
            q,_=run()
            assert b'compile job cache miss' in q.stderr
            report['checks'].append('private CAS permissions and clear forces native miss')
        before=events()
        version=subprocess.run([str(binary),'clang','--version'],env=env,capture_output=True,check=True)
        assert version.stdout==subprocess.check_output([clang,'--version'],env=env)
        stdin=[str(binary),'clang','-x','c','-','-c','-o',str(out)]
        subprocess.run(stdin,input=b'int nano_stdin(void){return 42;}\n',env=env,check=True,capture_output=True)
        disabled_flags=['-isysroot',sdk,*flags]
        subprocess.run([str(binary),'clang',*disabled_flags],env=env|{'NANOCOMPILE_DISABLE':'1'},check=True,capture_output=True)
        assert events()==before
        report['checks'].append('version, stdin and disabled commands bypass cache')
        helper=root/'opaque-clang-helper'
        helper.write_text('#!/bin/sh\nexec '+shlex.quote(clang)+' "$@"\n')
        helper.chmod(0o700)
        before=events()
        q=subprocess.run([str(binary),'clang',*flags],cwd=root,env=env|{'NANOCOMPILE_CLANG':str(helper)},check=True,capture_output=True)
        helper_obj=out.read_bytes()
        subprocess.run([clang,*flags],cwd=root,env=env,check=True,capture_output=True)
        assert helper_obj==out.read_bytes() and events()==before
        report['checks'].append('opaque compiler override passes through with original arguments')
        source.write_text('#error deliberate error\n')
        out.unlink(missing_ok=True)
        q=subprocess.run([str(binary),'clang',*flags],env=env,capture_output=True)
        assert q.returncode != 0 and not out.exists()
        report['checks'].append('compiler failure preserved without an output')
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report['checks']))
