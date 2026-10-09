"""Reproduce the Apple Clang scanner's debug-metadata difference from normal compilation."""
import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
clang = subprocess.check_output(['xcrun', '--find', 'clang'], text=True).strip()
sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
with tempfile.TemporaryDirectory(prefix='nano-clang-debug-difference-') as tmp:
    root = Path(tmp)
    source = root/'x.c'
    source.write_text('int nano_probe(void) {return 42;}\n')
    objects, stripped, dwarf = {}, {}, {}
    for mode in ('normal', 'scanner'):
        flags = [] if mode == 'normal' else ['-fdepscan=inline', '-Xclang', '-fcas-path',
            '-Xclang', str(root/'cas'), '-Xclang', '-fcache-compile-job']
        output = root/'x.o'
        subprocess.run([clang, '-isysroot', sdk, '-gfull', *flags, '-c', str(source), '-o', str(output)], check=True)
        objects[mode] = hashlib.sha256(output.read_bytes()).hexdigest()
        dwarf[mode] = subprocess.check_output(['xcrun', 'dwarfdump', str(output)], text=True)
        clean = root/(mode+'-stripped.o')
        shutil.copy2(output, clean)
        subprocess.run(['xcrun', 'strip', '-S', str(clean)], check=True)
        stripped[mode] = hashlib.sha256(clean.read_bytes()).hexdigest()
    assert objects['normal'] != objects['scanner']
    assert stripped['normal'] == stripped['scanner']
    assert 'DW_AT_comp_dir' in dwarf['normal'] and 'DW_AT_comp_dir' not in dwarf['scanner']
report = {'scope': 'Small debug fixture only; motivates replay-disabled baseline, not permission to ignore arbitrary artifact differences.',
          'compiler_version': subprocess.check_output([clang, '--version'], text=True),
          'compiler_sha256': hashlib.sha256(Path(clang).read_bytes()).hexdigest(),
          'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'object_sha256': objects, 'debug_stripped_object_sha256': stripped,
          'normal_has_compile_dir_scanner_omits_it': True,
          'unmodified_objects_differ': True, 'debug_stripped_objects_equal': True}
args.output.write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report))
