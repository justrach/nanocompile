"""Run serial correctness gates for the adopted decoder-scope binary."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('binary', type=Path)
p.add_argument('--baseline', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
binary = a.binary.resolve()
env = dict(os.environ, RUSTUP_TOOLCHAIN='1.97.1')
report = {'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
          'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'source_sha256': {str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in
                            map(Path, ('src/cache.zig','src/identity.zig','src/rust_metadata.zig'))},
          'checks': []}
with tempfile.TemporaryDirectory(prefix='decoder gates ') as temp:
    cases = [('unit', ['zig','build','test']),
             ('integration', ['zig','build','integration','-Doptimize=ReleaseFast'])]
    for name, script, extra in (
        ('native_identity','tests/native_identity.py',[]),
        ('native_metadata','tests/native_metadata_cache.py',[]),
        ('static_native','tests/static_native_cache.py',[]),
        ('producer','tests/producer_cache.py',['--cargo-flags']),
        ('executable','tests/executable_cache.py',[]),
        ('scope','benchmarks/experiments/decoder_scope_check.py',['--baseline',str(a.baseline.resolve())])):
        cases.append((name, ['python3',script,str(binary),*extra,'--output',str(Path(temp)/(name+'.json'))]))
    for name, command in cases:
        print('Checking '+name, flush=True)
        result = subprocess.run(command, env=env, capture_output=True, timeout=600)
        if result.returncode:
            print(result.stdout.decode(errors='replace')[-3000:])
            print(result.stderr.decode(errors='replace')[-3000:])
        assert result.returncode == 0, name
        row = {'name':name,'command':command,'passed':True}
        output = Path(temp)/(name+'.json')
        if output.exists(): row['results'] = json.loads(output.read_text())
        report['checks'].append(row)
        a.output.write_text(json.dumps(report,indent=2)+'\n')
        print(name+' passed', flush=True)
assert hashlib.sha256(binary.read_bytes()).hexdigest() == report['binary_sha256']
print('All decoder adoption gates passed',flush=True)
