"""Alternate identical real-project Zig restores with serial/parallel stamp checks."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import time


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('baseline',type=Path);p.add_argument('candidate',type=Path)
    p.add_argument('project',type=Path);p.add_argument('--state',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--runs',type=int,default=27)
    args=p.parse_args();assert args.runs>0
    state=args.state.resolve();state.mkdir(parents=True,exist_ok=False)
    project=args.project.resolve();binaries={k:getattr(args,k).resolve() for k in ('baseline','candidate')}
    wrapper=state/'nanocompile';artifact=state/'base64'
    env={k:v for k,v in os.environ.items() if not k.startswith(('NANOCOMPILE_','ZIG_','R2_','KACHE_'))}
    env.update(NANOCOMPILE_DIR=str(state/'nano'),NANOCOMPILE_TRACE='1',ZIG_LOCAL_CACHE_DIR=str(state/'local'),ZIG_GLOBAL_CACHE_DIR=str(state/'global'))
    command=[str(wrapper),'zig','build-exe','-O','ReleaseFast','--dep','strict_base64','-Mroot=Tests/Base64Benchmark/Base64BenchmarkMain.zig','-Mstrict_base64=Sources/WootinCore/base64_strict.zig','-femit-bin='+str(artifact)]
    sources={str(x.relative_to(project)):sha(x) for x in project.rglob('*.zig')}
    report={'method':'27 alternating real Wootin executable restores; same wrapper path, cache, compiler args, environment and output; both binaries have the parsing correctness fix; only candidate parallelizes >=512 Zig toolchain stamps; compiler caches deleted before every timed restore; byte-identical artifact and trace coverage required; compiler prime excluded; OS caches warm',
            'binary_sha256':{k:sha(v) for k,v in binaries.items()},'script_sha256':sha(Path(__file__)),
            'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_sha256':sources,'command':command,'builds':[]}
    def run(mode,phase):
        shutil.copy2(binaries[mode],wrapper);artifact.unlink(missing_ok=True)
        if phase=='hit':
            for folder in ('local','global'): shutil.rmtree(state/folder,ignore_errors=True)
        events=state/'nano/events';before=events.read_text().splitlines() if events.exists() else []
        start=time.perf_counter_ns();r=subprocess.run(command,cwd=project,env=env,capture_output=True,timeout=300);elapsed=(time.perf_counter_ns()-start)/1e6
        assert r.returncode==0,r.stderr.decode()
        delta=(events.read_text().splitlines()[len(before):]);assert delta==(['miss'] if phase=='prime' else ['hit']),delta
        if phase=='hit':
            assert sha(artifact)==reference
            assert (b'parallel Zig stamp validation' in r.stderr)==(mode=='candidate'),r.stderr
        return {'mode':mode,'phase':phase,'ms':elapsed,'events':delta,'parallel_coverage':b'parallel Zig stamp validation' in r.stderr}
    report['builds'].append(run('baseline','prime'));reference=sha(artifact)
    for i in range(args.runs):
        for mode in (('baseline','candidate') if i%2==0 else ('candidate','baseline')):
            report['builds'].append(run(mode,'hit'))
    samples={k:[x['ms'] for x in report['builds'] if x['phase']=='hit' and x['mode']==k] for k in binaries}
    deltas=[a-b for a,b in zip(samples['baseline'],samples['candidate'])]
    report.update(median_ms={k:statistics.median(v) for k,v in samples.items()},paired_ms_saved=deltas,
                  paired_summary={'wins':sum(x>0 for x in deltas),'mean_ms_saved':statistics.mean(deltas),'median_ms_saved':statistics.median(deltas),'standard_error_ms':statistics.stdev(deltas)/len(deltas)**.5 if len(deltas)>1 else None},
                  artifact_sha256=reference,sources_unchanged=all(sha(project/k)==v for k,v in sources.items()))
    assert report['sources_unchanged'];args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:report[k] for k in ('median_ms','paired_summary')}))


if __name__=='__main__':main()
