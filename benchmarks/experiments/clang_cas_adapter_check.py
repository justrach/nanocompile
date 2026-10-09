"""Verify the Zig Clang adapter with C/assembly restores and content invalidation."""
import argparse
import hashlib
import json
import os
import mmap
import shutil
from pathlib import Path
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('baseline', type=Path)
p.add_argument('candidate', type=Path)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
clang = subprocess.check_output(['xcrun', '--find', 'clang'], text=True).strip()
rows = []
with tempfile.TemporaryDirectory(prefix='nano-clang-cas-probe-') as tmp:
    root = Path(tmp)
    c, header, asm = root/'x.c', root/'x.h', root/'x.S'
    c.write_text('#include <stdint.h>\n#include <TargetConditionals.h>\n#include "x.h"\nint32_t nano_probe(void) {return VALUE;}\n')
    header.write_text('#define VALUE 42\n')
    asm.write_text('.text\n.globl _nano_asm_probe\n_nano_asm_probe:\n ret\n')
    flags = ['-fdepscan=inline', '-Xclang', '-fcas-path', '-Xclang', str(root/'cas'),
             '-Xclang', '-fcache-compile-job', '-Rcompile-job-cache']
    def compile(source, cache):
        dest = root/(source.name+'.o')
        dest.unlink(missing_ok=True)
        env = dict(os.environ, NANOCOMPILE_CLANG_CAS=str(root/'cas'))
        q = subprocess.run([str((args.candidate if cache else args.baseline).resolve()), '--target=arm64-apple-macosx', '-gfull', '-c', str(source), '-o', str(dest)],
                           env=env, capture_output=True, text=True)
        return q, dest.read_bytes() if dest.exists() else None
    for source in (c, asm):
        direct, reference = compile(source, False)
        assert direct.returncode == 0
        shutil.rmtree(root/'cas', ignore_errors=True)
        cold, first = compile(source, True)
        warm, second = compile(source, True)
        assert cold.returncode == warm.returncode == 0 and reference == first == second
        assert 'compile job cache miss' in cold.stderr and 'compile job cache hit' in warm.stderr
        rows.append({'source_kind': source.suffix, 'cold_miss': True, 'warm_hit': True,
                     'replay_disabled_cold_warm_object_bytes_equal': True})
    stamp = header.stat()
    header.write_text('#define VALUE 43\n')
    os.utime(header, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert header.stat().st_size == stamp.st_size and header.stat().st_mtime_ns == stamp.st_mtime_ns
    changed, obj = compile(c, True)
    direct, expected = compile(c, False)
    assert changed.returncode == direct.returncode == 0 and obj == expected
    assert 'compile job cache miss' in changed.stderr
    rows.append({'preserved_mtime_same_size_header_change_causes_miss': True,
                 'changed_object_matches_replay_disabled_compile': True})
    with header.open('r+b') as mapped_file:
        with mmap.mmap(mapped_file.fileno(), 0, access=mmap.ACCESS_WRITE) as mapped:
            mapped[14:16] = b'44'
            initial, old_object = compile(c, True)
            assert initial.returncode == 0
            before = header.stat()
            mapped[15:16] = b'5'
            after = header.stat()
            actual, new_object = compile(c, True)
            direct, expected = compile(c, False)
            assert actual.returncode == direct.returncode == 0 and new_object == expected and new_object != old_object
            assert 'compile job cache miss' in actual.stderr
            same_metadata = (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) == (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            rows.append({'already_dirty_unflushed_mmap_header_change_detected': True,
                         'checked_metadata_unchanged_on_second_write': same_metadata,
                         'changed_object_matches_replay_disabled_compile': True})
    probe = subprocess.run([str(args.candidate.resolve()), '--version'], capture_output=True, text=True)
    assert probe.returncode == 0 and probe.stdout == subprocess.check_output([clang, '--version'], text=True)
    pre = subprocess.run([str(args.candidate.resolve()), '-E', str(c)], capture_output=True, text=True)
    assert pre.returncode == 0 and 'compile job cache' not in pre.stderr
    rows.append({'version_probe_and_preprocessing_passthrough': True})
    stdin_objects = []
    for adapter in (args.baseline, args.candidate):
        output = root/'stdin.o'
        output.unlink(missing_ok=True)
        q = subprocess.run([str(adapter.resolve()), '-x', 'c', '-', '-c', '-o', str(output)],
                           input='int nano_stdin(void) {return 42;}\n', capture_output=True, text=True,
                           env=dict(os.environ, NANOCOMPILE_CLANG_CAS=str(root/'cas')))
        assert q.returncode == 0 and 'compile job cache' not in q.stderr
        stdin_objects.append(output.read_bytes())
    assert stdin_objects[0] == stdin_objects[1]
    rows.append({'stdin_compile_passthrough_preserves_input_and_object_bytes': True})
    c.write_text('#error deliberate failure\n')
    fail, obj = compile(c, True)
    assert fail.returncode != 0 and obj is None
    rows.append({'failed_compilation_returns_failure_without_object': True})
report = {'scope': 'Experimental Zig adapter fixtures; no production support or Cargo speedup claim.',
          'adapter_sha256': {label: hashlib.sha256(path.resolve().read_bytes()).hexdigest() for label,path in [('baseline',args.baseline),('candidate',args.candidate)]},
          'compiler': clang, 'compiler_sha256': hashlib.sha256(Path(clang).read_bytes()).hexdigest(),
          'compiler_version': subprocess.check_output([clang, '--version'], text=True),
          'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'cache_flags': ['-fdepscan=inline', '-Xclang', '-fcas-path', '-Xclang', '<private CAS>',
                          '-Xclang', '-fcache-compile-job', '-Rcompile-job-cache'], 'checks': rows}
args.output.write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(rows))
