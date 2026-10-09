"""Require real lookup overlap and preserve SDK/tool failure behavior."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('binary', type=Path)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
binary = args.binary.resolve()
real_xcrun = shutil.which('xcrun')
clang = subprocess.check_output([real_xcrun, '--find', 'clang'], text=True).strip()
report = {'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
          'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'checks': []}
with tempfile.TemporaryDirectory(prefix='nano live selection ') as tmp:
    root = Path(tmp)
    spy = root/'bin'
    spy.mkdir()
    script = spy/'xcrun'
    source, output = root/'x.c', root/'x.o'
    source.write_text('int nano_live_probe(void) { return 42; }\n')
    flags = ['-c', str(source), '-o', str(output)]
    env = {k:v for k,v in os.environ.items() if not k.startswith(('NANOCOMPILE_', 'R2_', 'KACHE_')) and k != 'SDKROOT'}
    env.update(NANOCOMPILE_DIR=str(root/'cache'), NANOCOMPILE_CLANG_REMARKS='1',
               PATH=str(spy)+os.pathsep+env.get('PATH',''))
    # Each selector waits for the other to start. Sequential queries cannot
    # satisfy this barrier; no duration threshold is used to infer concurrency.
    script.write_text('#!/bin/sh\n'
        'case "$1" in\n'
        ' --find) mine=find; other=sdk;;\n'
        ' --sdk) mine=sdk; other=find;;\n'
        ' *) exit 9;;\n'
        'esac\n'
        'touch '+shlex.quote(str(root))+'/"$mine"\n'
        'n=0\n'
        'while [ ! -f '+shlex.quote(str(root))+'/"$other" ]; do\n'
        ' n=$((n+1)); [ "$n" -lt 200 ] || exit 8\n'
        ' sleep 0.01\n'
        'done\n'
        'exec '+shlex.quote(real_xcrun)+' "$@"\n')
    script.chmod(0o700)
    objects = []
    for _ in range(2):
        for marker in ('find','sdk'):
            (root/marker).unlink(missing_ok=True)
        output.unlink(missing_ok=True)
        q = subprocess.run([str(binary), 'clang', *flags], env=env, capture_output=True, timeout=15)
        assert q.returncode == 0, q.stderr.decode(errors='replace')
        assert all((root/m).exists() for m in ('find','sdk'))
        objects.append(output.read_bytes())
    assert objects[0] == objects[1]
    report['checks'].append('both live selectors cross a two-way start barrier on cold and warm calls')
    subprocess.run([clang, *flags], env=env, check=True, capture_output=True)
    direct = output.read_bytes()
    event_file = root/'cache/events'
    before = event_file.read_bytes() if event_file.exists() else b''
    script.write_text('#!/bin/sh\n[ "$1" != --sdk ] || exit 9\nexec '+shlex.quote(real_xcrun)+' "$@"\n')
    output.unlink()
    q = subprocess.run([str(binary), 'clang', *flags], env=env, capture_output=True, timeout=15)
    assert q.returncode == 0 and output.read_bytes() == direct, q.stderr.decode(errors='replace')
    assert (event_file.read_bytes() if event_file.exists() else b'') == before
    report['checks'].append('failed SDK lookup falls back to unchanged original compiler arguments and bytes')
    script.write_text('#!/bin/sh\n[ "$1" != --find ] || exit 9\nexec '+shlex.quote(real_xcrun)+' "$@"\n')
    output.unlink()
    q = subprocess.run([str(binary), 'clang', *flags], env=env, capture_output=True, timeout=15)
    assert q.returncode != 0 and not output.exists()
    report['checks'].append('failed tool lookup preserves failure without a compiler output')
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report['checks']))
