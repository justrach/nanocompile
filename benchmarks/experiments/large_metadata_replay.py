"""Replay a recorded real large-metadata compiler request in a new output/cache directory."""
import argparse,hashlib,json,os,subprocess,time
from pathlib import Path
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--invocation',type=Path,required=True);parser.add_argument('--cargo-env',type=Path,required=True)
parser.add_argument('--accepted',type=Path,required=True);parser.add_argument('--candidate',type=Path,required=True)
parser.add_argument('--state',type=Path,required=True)
options=parser.parse_args();root=options.state.resolve();root.mkdir(parents=True,mode=0o700,exist_ok=False)
record=json.loads(options.invocation.read_text());args=list(record['args']);cwd=Path(record['cwd'])
(root/'out').mkdir();args[args.index('--out-dir')+1]=str(root/'out')
env={k:v for k,v in os.environ.items() if not k.startswith(('NANOCOMPILE_','KACHE_','R2_')) and k not in ('RUSTC_WRAPPER','RUSTC_WORKSPACE_WRAPPER')};env.update(json.loads(options.cargo_env.read_text()));env.update(NANOCOMPILE_DIR=str(root/'cache'),NANOCOMPILE_PROC_MACROS='reported',NANOCOMPILE_TRACE='1',SOURCE_DATE_EPOCH='1791423832',RUSTUP_TOOLCHAIN='1.97.1')
out=Path(args[args.index('--out-dir')+1]);crate=args[args.index('--crate-name')+1]
suffix=next((value.split('=',1)[1] for value in args if value.startswith('extra-filename=')), '')
outputs=[out/(f'lib{crate}{suffix}.rmeta'),out/(f'lib{crate}{suffix}.rlib'),out/(f'{crate}{suffix}.d')]
def digest(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
sources={str(p.relative_to(cwd)):digest(p) for p in cwd.rglob('*.rs')};rows=[];reference=None
for name,binary in [('accepted-cold',str(options.accepted.resolve())),('candidate-cold',str(options.candidate.resolve())),('candidate-warm',str(options.candidate.resolve()))]:
 for p in outputs:p.unlink(missing_ok=True)
 started=time.monotonic();r=subprocess.run([binary,*args],cwd=cwd,env=env,capture_output=True,timeout=180);elapsed=time.monotonic()-started
 (root/(name+'.stdout')).write_bytes(r.stdout);(root/(name+'.stderr')).write_bytes(r.stderr)
 artifacts={p.name:digest(p) for p in outputs if p.exists()};reference=reference or artifacts
 row=dict(name=name,seconds=elapsed,exit_code=r.returncode,artifacts=artifacts,matches_reference=artifacts==reference,decisions=[x for x in r.stderr.decode(errors='replace').splitlines() if x.startswith('nanocompile:')],binary_sha256=digest(Path(binary)))
 rows.append(row);print(json.dumps(row),flush=True)
 (root/'result.json').write_text(json.dumps(dict(rows=rows,diagnostic=True,source_hashes=sources,invocation_sha256=digest(options.invocation)),indent=2)+'\n')
 assert r.returncode==0 and artifacts==reference
assert any('uncached: StreamTooLong' in x for x in rows[0]['decisions'])
assert not any('uncached:' in x for x in rows[1]['decisions'])
assert 'nanocompile: hit' in rows[2]['decisions']
assert all(digest(cwd/p)==h for p,h in sources.items())
print('PASS real compiler cold/store/warm bytes and unchanged sources',flush=True)
