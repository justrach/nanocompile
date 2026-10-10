"""Real portable C/C++ compile-cache restoration, invalidation and linked behavior."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary', type=Path)
    p.add_argument('--compiler', action='append')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    binary = args.binary.resolve()
    compilers = args.compiler or ([subprocess.check_output(['xcrun','--find','clang'],text=True).strip()] if sys.platform == 'darwin' else [shutil.which('gcc'), shutil.which('clang')])
    assert all(compilers), 'Install GCC and Clang for Linux coverage'
    results = []
    for tool in compilers:
        with tempfile.TemporaryDirectory(prefix='nano portable cc ') as temp:
            root = Path(temp)
            env = {k:v for k,v in os.environ.items() if not k.startswith(('NANOCOMPILE_', 'R2_', 'KACHE_'))}
            if sys.platform == 'darwin': env['SDKROOT'] = subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip()
            env.update(NANOCOMPILE_DIR=str(root/'cache'), NANOCOMPILE_CC=tool, NANOCOMPILE_CXX=tool, NANOCOMPILE_TRACE='1')
            def call(argv, ok=True, current_env=None):
                r = subprocess.run(argv, cwd=root, env=current_env or env, capture_output=True, timeout=180)
                if ok: assert r.returncode == 0, r.stderr.decode(errors='replace')
                return r
            def events():
                f=root/'cache/events'
                return f.read_text().splitlines() if f.exists() else []
            (root/'early').mkdir(); (root/'late').mkdir()
            header=root/'late/value.h'
            header.write_text('#define VALUE 42\n')
            (root/'source.c').write_text('#include "value.h"\nint answer(void) { return VALUE; }\n')
            flags=['-c','source.c','-O2','-g0','-Iearly','-Ilate','-MD','-MF','object deps.d','-o','object.o']
            call([tool,*flags]); reference=sha(root/'object.o'); dep_reference=(root/'object deps.d').read_bytes()
            call([str(binary),'cc',*flags]); assert events()[-1]=='cc_miss'
            (root/'object.o').unlink(); (root/'object deps.d').unlink()
            call([str(binary),'cc',*flags]); assert events()[-1]=='cc_hit'
            assert sha(root/'object.o')==reference and (root/'object deps.d').read_bytes()==dep_reference
            (root/'probe.c').write_text('int answer(void); int main(void) { return answer() == EXPECTED ? 0 : 1; }\n')
            def behavior(value):
                call([tool,'probe.c','object.o','-DEXPECTED='+str(value),'-o','probe'])
                call([str(root/'probe')])
            behavior(42)
            st=header.stat(); header.write_text('#define VALUE 43\n'); os.utime(header,ns=(st.st_atime_ns,st.st_mtime_ns))
            call([str(binary),'cc',*flags]); assert events()[-1]=='cc_miss'; behavior(43)
            new_reference=sha(root/'object.o'); call([tool,*flags]); assert sha(root/'object.o')==new_reference
            (root/'early/value.h').write_text('#define VALUE 44\n')
            call([str(binary),'cc',*flags]); assert events()[-1]=='cc_miss'; behavior(44)
            (root/'early/value.h').unlink()
            call([str(binary),'cc',*flags]); assert events()[-1]=='cc_hit'; behavior(43)
            (root/'optional.c').write_text('#if __has_include("optional.h")\n#include "optional.h"\n#else\n#define OPT 9\n#endif\nint optional(void) { return OPT; }\n')
            optional=['-c','optional.c','-O2','-g0','-o','optional.o']
            call([str(binary),'cc',*optional]); old=sha(root/'optional.o')
            (root/'optional.h').write_text('#define OPT 10\n')
            call([str(binary),'cc',*optional]); assert events()[-1]=='cc_miss' and sha(root/'optional.o')!=old
            (root/'cpp.cpp').write_text('template<class T> T add(T v) { return v+7; } extern "C" int cpp_answer() { return add(35); }\n')
            cpp=['-c','cpp.cpp','-O2','-g0','-o','cpp.o']
            call([tool,*cpp]); cpp_reference=sha(root/'cpp.o')
            call([str(binary),'c++',*cpp]); assert events()[-1]=='cc_miss'
            (root/'cpp.o').unlink(); call([str(binary),'c++',*cpp]); assert events()[-1]=='cc_hit' and sha(root/'cpp.o')==cpp_reference
            (root/'cpp_probe.c').write_text('int cpp_answer(void); int main(void) { return cpp_answer() == 42 ? 0 : 1; }\n')
            call([tool,'cpp_probe.c','cpp.o','-o','cpp_probe']); call([str(root/'cpp_probe')])
            before=len(events()); call([str(binary),'cc',*flags,'-g'])
            assert events()[before:]==['cc_bypass']
            (root/'bad.c').write_text('this does not compile\n')
            assert call([str(binary),'cc','-c','bad.c','-o','bad.o'],ok=False).returncode != 0
            call([str(binary),'cc',*flags]); assert events()[-1]=='cc_hit'
            # Find the current restored object by bytes, then corrupt its CAS copy.
            blobs=[f for f in (root/'cache/blobs').glob('*/*') if f.read_bytes()==(root/'object.o').read_bytes()]
            assert blobs
            for f in blobs: f.write_bytes(b'corrupt')
            call([str(binary),'cc',*flags]); assert events()[-1]=='cc_miss'; behavior(43)
            call([str(binary),'cc',*flags]); assert events()[-1]=='cc_hit'
            call([str(binary),'gc','0']); call([str(binary),'cc',*flags]); assert events()[-1]=='cc_miss'
            results.append({'compiler':tool,'version':call([tool,'--version']).stdout.decode(),'checks':['C/C++ byte-identical objects and depfiles','linked behavior','preserved-mtime header change','new higher-priority include','has_include absence/presence','debug bypass','failed compiler','blob corruption repair','GC']})
    report={'binary_sha256':sha(binary),'platform':sys.platform,'compilers':results}
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(report,indent=2)+'\n')
    print('PASS: portable C/C++ objects, live includes, byte hashes, linked behavior, corruption and GC')


if __name__ == '__main__': main()
