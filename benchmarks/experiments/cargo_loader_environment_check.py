"""Capture Cargo's loader variable names using a native compiler wrapper."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    with tempfile.TemporaryDirectory(prefix='nano-cargo-loader-') as tmp:
        root = Path(tmp)
        (root / 'src').mkdir()
        (root / 'Cargo.toml').write_text('[package]\nname="loader_probe"\nversion="0.0.0"\nedition="2021"\n')
        (root / 'src/lib.rs').write_text('pub fn answer()->u32 {42}\n')
        wrapper, log, code = root / 'wrapper', root / 'calls.jsonl', root / 'wrapper.c'
        code.write_text('''#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
int main(int argc,char **argv) {
 FILE *f=fopen(LOG,"a"); if(!f || argc<2) return 126;
 fprintf(f,"{\\"compiler\\":\\"%s\\",\\"loader_environment_names\\":[",argv[1]);
 char *names[]={"DYLD_FALLBACK_LIBRARY_PATH","DYLD_LIBRARY_PATH","DYLD_INSERT_LIBRARIES","LD_LIBRARY_PATH","LD_PRELOAD"}; int comma=0;
 for(int i=0;i<5;i++) if(getenv(names[i])) {fprintf(f,"%s\\"%s\\"",comma?",":"",names[i]);comma=1;}
 fputs("]}\\n",f);fclose(f); execv(argv[1],argv+1); return 127;
}
'''.replace('LOG', json.dumps(str(log))))
        subprocess.run(['cc', str(code), '-o', str(wrapper)], capture_output=True, check=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith(('NANOCOMPILE_', 'KACHE_', 'R2_'))
               and k not in ('RUSTC_WRAPPER', 'RUSTC_WORKSPACE_WRAPPER')}
        env.update(RUSTUP_TOOLCHAIN='1.97.1', RUSTC_WRAPPER=str(wrapper), CARGO_INCREMENTAL='0')
        subprocess.run(['cargo', 'build', '--release', '--offline', '-j', '1'], cwd=root, env=env, capture_output=True, check=True)
        rows = [json.loads(x) for x in log.read_text().splitlines()]
        expected = 'DYLD_FALLBACK_LIBRARY_PATH' if os.uname().sysname == 'Darwin' else 'LD_LIBRARY_PATH'
        assert any(expected in x['loader_environment_names'] for x in rows)
        report = {'method': 'Minimal real Cargo release build; native wrapper records only compiler argument and loader variable names, then directly execs the compiler. No environment values recorded. Capture uses a native executable to preserve the loader environment.',
                  'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  'rust_toolchain': '1.97.1', 'calls': rows}
        args.output.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report))


if __name__ == '__main__':
    main()
