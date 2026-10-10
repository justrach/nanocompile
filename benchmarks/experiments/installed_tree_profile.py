"""Compare full installed-tree fingerprints with identical content and stamp validation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import time


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline',type=Path);p.add_argument('candidate',type=Path)
    p.add_argument('tree',type=Path);p.add_argument('--runs',type=int,default=7)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();assert args.runs>0
    binaries={name:getattr(args,name).resolve() for name in ('baseline','candidate')}
    env={k:v for k,v in os.environ.items() if not k.startswith(('NANOCOMPILE_','R2_','KACHE_'))}
    rows=[];digests=set()
    with tempfile.TemporaryDirectory(prefix='nano installed tree ') as tmp:
        for pair in range(args.runs):
            order=('baseline','candidate') if pair%2==0 else ('candidate','baseline')
            for name in order:
                root=Path(tmp)/str(pair)/name
                for phase in ('cold','warm'):
                    start=time.monotonic()
                    raw=subprocess.check_output([str(binaries[name]),'internal-installed-tree',str(args.tree.resolve())],env=dict(env,NANOCOMPILE_DIR=str(root)))
                    wall=time.monotonic()-start
                    row=json.loads(raw);digests.add(row['hash'])
                    memos=list((root/'script-tools').glob('*'));assert len(memos)==1
                    memo=json.loads(memos[0].read_bytes()[65:])
                    rows.append(dict(pair=pair,implementation=name,phase=phase,wall_seconds=wall,
                        fingerprint_seconds=row['elapsed_ns']/1e9,hash=row['hash'],stamps=len(memo['stamps']),links=len(memo['links']),
                        independent_file_memos=len(list((root/'toolchain-files').glob('*')))))
        assert len(digests)==1,'Both variants must fingerprint exactly the same complete input graph'
    report=dict(script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        binary_sha256={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in binaries.items()},
        tree=str(args.tree.resolve()),runs=args.runs,observations=rows,
        method='alternate cold order with empty private compiler cache; immediately revalidate whole-tree memo; OS caches unflushed; fingerprints byte-equal')
    report['medians']={phase:{name:statistics.median(r['fingerprint_seconds'] for r in rows if r['phase']==phase and r['implementation']==name) for name in binaries} for phase in ('cold','warm')}
    args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report['medians']))

if __name__=='__main__':main()
