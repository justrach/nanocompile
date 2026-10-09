"""Verify the local Apple Clang CAS for narrow C and preprocessed-assembly fixtures."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
clang = subprocess.check_output(['xcrun', '--find', 'clang'], text=True).strip()
rows = []
with tempfile.TemporaryDirectory(prefix='nano-clang-cas-probe-') as tmp:
    root = Path(tmp)
    c, header, asm = root/'x.c', root/'x.h', root/'x.S'
    c.write_text('#include <stdint.h>\n#include "x.h"\nint32_t nano_probe(void) {return VALUE;}\n')
    header.write_text('#define VALUE 42\n')
    asm.write_text('.text\n.globl _nano_asm_probe\n_nano_asm_probe:\n ret\n')
    flags = ['-fdepscan=inline', '-Xclang', '-fcas-path', '-Xclang', str(root/'cas'),
             '-Xclang', '-fcache-compile-job', '-Rcompile-job-cache']
    def compile(source, cache):
        dest = root/(source.name+'.o')
        dest.unlink(missing_ok=True)
        q = subprocess.run([clang, *(flags if cache else []), '-c', str(source), '-o', str(dest)],
                           capture_output=True, text=True)
        return q, dest.read_bytes() if dest.exists() else None
    for source in (c, asm):
        direct, reference = compile(source, False)
        assert direct.returncode == 0
        cold, first = compile(source, True)
        warm, second = compile(source, True)
        assert cold.returncode == warm.returncode == 0 and reference == first == second
        assert 'compile job cache miss' in cold.stderr and 'compile job cache hit' in warm.stderr
        rows.append({'source_kind': source.suffix, 'cold_miss': True, 'warm_hit': True,
                     'direct_cold_warm_object_bytes_equal': True})
    stamp = header.stat()
    header.write_text('#define VALUE 43\n')
    os.utime(header, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert header.stat().st_size == stamp.st_size and header.stat().st_mtime_ns == stamp.st_mtime_ns
    changed, obj = compile(c, True)
    direct, expected = compile(c, False)
    assert changed.returncode == direct.returncode == 0 and obj == expected
    assert 'compile job cache miss' in changed.stderr
    rows.append({'preserved_mtime_same_size_header_change_causes_miss': True,
                 'changed_object_matches_direct': True})
    c.write_text('#error deliberate failure\n')
    fail, obj = compile(c, True)
    assert fail.returncode != 0 and obj is None
    rows.append({'failed_compilation_returns_failure_without_object': True})
report = {'scope': 'Local Apple Clang fixture verification only; no Cargo speedup or production adapter claim.',
          'compiler': clang, 'compiler_sha256': hashlib.sha256(Path(clang).read_bytes()).hexdigest(),
          'compiler_version': subprocess.check_output([clang, '--version'], text=True),
          'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'cache_flags': ['-fdepscan=inline', '-Xclang', '-fcas-path', '-Xclang', '<private CAS>',
                          '-Xclang', '-fcache-compile-job', '-Rcompile-job-cache'], 'checks': rows}
args.output.write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(rows))
