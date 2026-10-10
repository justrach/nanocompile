"""Declared Nano tasks versus real Turborepo local tasks on the same two-package example."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import statistics

ROOT=Path(__file__).resolve().parents[1]
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary',type=Path)
    p.add_argument('--runs',type=int,default=9)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(); assert args.runs>0
    binary=args.binary.resolve(); turbo=ROOT/'examples/turborepo/node_modules/.bin/turbo'
    assert turbo.exists(), 'npm ci --prefix examples/turborepo first'
    rows=[]
    with tempfile.TemporaryDirectory(prefix='nano task comparison ') as tmp:
        root=Path(tmp); repo=root/'project'; cache=root/'cache'; log=root/'executions'
        shutil.copytree(ROOT/'examples/turborepo',repo,ignore=shutil.ignore_patterns('node_modules','.turbo','dist'))
        env={k:v for k,v in os.environ.items() if not k.startswith(('NANOCOMPILE_','TURBO_','R2_','KACHE_'))}
        env.update(NANOCOMPILE_DIR=str(cache),NANO_TURBO_EXECUTION_LOG=str(log),EXAMPLE_LABEL='demo',TURBO_TELEMETRY_DISABLED='1')
        commands={'nanocompile':[str(binary),'task','nanocompile.tasks.json'],
                  'turborepo':[str(turbo),'run','build','--cache=local:rw','--summarize','--no-daemon']}
        def outputs(): return {str(f.relative_to(repo)):sha(f) for f in repo.glob('**/dist/*') if f.is_file()}
        def clean():
            for d in list(repo.glob('**/dist')): shutil.rmtree(d)
        def executed(): return log.read_text().splitlines() if log.exists() else []
        def run(mode,phase,expected,current_env=None):
            clean(); before=len(executed()); start=time.perf_counter()
            result=subprocess.run(commands[mode],cwd=repo,env=current_env or env,capture_output=True,timeout=180)
            elapsed=time.perf_counter()-start
            assert result.returncode==0, result.stderr.decode(errors='replace')
            actual=executed()[before:]; assert sorted(actual)==sorted(expected),(mode,phase,actual)
            artifacts=outputs(); assert len(artifacts)==2
            row={'mode':mode,'phase':phase,'seconds':elapsed,'executed':actual,'artifacts':artifacts}
            if mode=='turborepo':
                summary=json.loads(max((repo/'.turbo/runs').glob('*.json'),key=lambda f:f.stat().st_mtime_ns).read_text())
                row['tasks']=[{k:t.get(k) for k in ('taskId','hash','cache')} for t in summary['tasks']]
                if not expected: assert all(t['cache']['status']=='HIT' and t['cache']['local'] for t in row['tasks'])
            rows.append(row); return artifacts
        reference=None
        for mode in commands:
            actual=run(mode,'cold',['message','site'])
            if reference is None: reference=actual
            assert actual==reference
        for i in range(args.runs):
            for mode in (('nanocompile','turborepo') if i%2==0 else ('turborepo','nanocompile')):
                assert run(mode,'warm',[])==reference
        greeting=repo/'packages/message/greeting.txt'; st=greeting.stat();greeting.write_text('Changed task source\n');os.utime(greeting,ns=(st.st_atime_ns,st.st_mtime_ns))
        changed=[run(mode,'changed-source',['message','site']) for mode in commands]
        assert changed[0]==changed[1] and changed[0]!=reference
        for mode in commands: assert run(mode,'changed-source-warm',[])==changed[0]
        site=repo/'apps/site/build.mjs';site.write_text(site.read_text().replace('Task cache example','Updated task example'))
        changed_site=[run(mode,'changed-site',['site']) for mode in commands];assert changed_site[0]==changed_site[1]
        changed_env=[run(mode,'changed-env',['message','site'],dict(env,EXAMPLE_LABEL='changed')) for mode in commands];assert changed_env[0]==changed_env[1]
        # Compare the current source outputs with real uncached Node executions.
        direct_env=dict(env,EXAMPLE_LABEL='changed')
        clean()
        for directory in ('packages/message','apps/site'):
            subprocess.run(['node','build.mjs'],cwd=repo/directory,env=direct_env,check=True,capture_output=True)
        assert outputs()==changed_env[0]
        blobs=[f for f in (cache/'blobs').glob('*/*') if f.read_bytes()==(repo/'packages/message/dist/message.json').read_bytes()]
        assert blobs
        for f in blobs: f.write_bytes(b'corrupt')
        assert run('nanocompile','corruption-repair',['message'],direct_env)==changed_env[0]
        # Rejected graphs must execute nothing; failed commands preserve status.
        spec=repo/'nanocompile.tasks.json'; parsed=json.loads(spec.read_text()); parsed['tasks'][0]['depends_on']=['site'];spec.write_text(json.dumps(parsed))
        before=len(executed()); bad=subprocess.run(commands['nanocompile'],cwd=repo,env=env,capture_output=True)
        assert bad.returncode!=0 and len(executed())==before
        parsed['tasks'][0]['depends_on']=[]; parsed['tasks'][0]['command']=['node','-e','process.exit(7)'];spec.write_text(json.dumps(parsed))
        failed=subprocess.run(commands['nanocompile'],cwd=repo,env=env,capture_output=True)
        assert failed.returncode==7
        report={'nanocompile_sha256':sha(binary),'script_sha256':sha(Path(__file__)),'turbo_version':subprocess.check_output([str(turbo),'--version'],text=True).strip(),
                'node_version':subprocess.check_output(['node','--version'],text=True).strip(),'runs_per_mode':args.runs,
                'method':'same example, scripts, source paths and fixed environment; cold once per backend; alternating warm pairs; remove every declared output before every build; assert actual execution log and output bytes; Turbo local-only no daemon; Nano explicit ordered file contracts, full environment and installed Node identity; fixture-specific, not a general scheduler comparison',
                'rows':rows,'median_warm_seconds':{mode:statistics.median(r['seconds'] for r in rows if r['mode']==mode and r['phase']=='warm') for mode in commands},
                'checks':['real Turbo local hits','Nano zero-execution restores','byte equality against direct Node','source/preserved-mtime changes','dependent/site-only edits','environment changes','corruption repair','invalid graph executes nothing','failed task status']}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report['median_warm_seconds']));print('PASS: declared tasks and real Turborepo local cache comparison')

if __name__=='__main__': main()
