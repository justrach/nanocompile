"""Real Wootin Zig executable: clean cold/native hits/Nano hits and source edits."""
import argparse
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import time


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary', type=Path)
    p.add_argument('project', type=Path, help='Disposable Wootin snapshot; original files restored finally')
    p.add_argument('--state', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--cold-runs', type=int, default=3)
    p.add_argument('--hit-runs', type=int, default=9)
    p.add_argument('--edit-runs', type=int, default=3)
    args = p.parse_args()
    assert min(args.cold_runs, args.hit_runs, args.edit_runs) > 0
    project, state, binary = args.project.resolve(), args.state.resolve(), args.binary.resolve()
    state.mkdir(parents=True, exist_ok=False)
    sources = {str(x.relative_to(project)): sha(x) for x in sorted(project.rglob('*.zig'))}
    root = project / 'Tests/Base64Benchmark/Base64BenchmarkMain.zig'
    shared = project / 'Sources/WootinCore/base64_strict.zig'
    originals = {x: (x.read_bytes(), x.stat().st_mtime_ns) for x in (root, shared)}
    assert b'const iterations = 24;' in originals[root][0]
    assert b'encoded_length / 4 * 3 + switch (encoded_length % 4)' in originals[shared][0]
    report = {'method': 'alternating direct Zig and Nano on actual Wootin executable; cold removes compiler and wrapper caches; native hits retain Zig caches; Nano hits delete Zig caches; edit cycles use normal updated mtimes, verify semantic outputs and Nano restore hashes; executable runtime excluded from build clock; OS filesystem caches unflushed; no R2',
              'project': str(project), 'source_commit': '04ac6717a0b2c69cd138fb6f6dc17ba6a66c2f90',
              'source_sha256': sources, 'binary_sha256': sha(binary), 'script_sha256': sha(Path(__file__)),
              'zig_version': subprocess.check_output(['zig', 'version'], text=True).strip(),
              'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'builds': []}
    assert report['zig_version'] == '0.17.0'
    env = {k: v for k,v in os.environ.items() if not k.startswith(('NANOCOMPILE_', 'ZIG_', 'R2_', 'KACHE_'))}
    def write_sources(leaf=False, dependency=False, restore_times=False):
        for file, (data, timestamp) in originals.items():
            if leaf and file == root:
                data = data.replace(b'const iterations = 24;', b'const iterations = 25;')
            if dependency and file == shared:
                data = data.replace(b'encoded_length / 4 * 3 + switch (encoded_length % 4)', b'(encoded_length >> 2) * 3 + switch (encoded_length & 3)')
            if file.read_bytes() != data:
                file.write_bytes(data)
            if restore_times:
                os.utime(file, ns=(timestamp,timestamp))
    def reset(mode):
        shutil.rmtree(state / mode, ignore_errors=True)
    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2)+'\n')
    def build(mode, phase, iteration, empty_zig=False, expected=None):
        folder = state / mode
        folder.mkdir(parents=True, exist_ok=True)
        if empty_zig:
            for name in ('global','local'):
                shutil.rmtree(folder / name, ignore_errors=True)
        artifact = folder / 'base64'
        artifact.unlink(missing_ok=True)
        current = dict(env, ZIG_GLOBAL_CACHE_DIR=str(folder / 'global'), ZIG_LOCAL_CACHE_DIR=str(folder / 'local'), NANOCOMPILE_DIR=str(folder / 'nano'))
        events = folder / 'nano/events'
        before = events.read_text().splitlines() if events.exists() else []
        command = ['zig','build-exe','-O','ReleaseFast','--dep','strict_base64',
                   '-Mroot=Tests/Base64Benchmark/Base64BenchmarkMain.zig',
                   '-Mstrict_base64=Sources/WootinCore/base64_strict.zig', '-femit-bin='+str(artifact)]
        if mode == 'nanocompile':
            command.insert(0,str(binary))
        started = time.perf_counter_ns()
        result = subprocess.run(command,cwd=project,env=current,capture_output=True,timeout=300)
        elapsed = (time.perf_counter_ns()-started)/1e9
        assert result.returncode == 0, result.stderr.decode(errors='replace')
        counts = dict(collections.Counter((events.read_text().splitlines()[len(before):] if events.exists() else [])))
        output = subprocess.check_output([str(artifact)],text=True,timeout=30)
        value = json.loads(output.split('WOOTIN_PROFILE_JSON ',1)[1])
        assert value['exact_output'] and value['invalid_rejected'] and value['split_boundaries_passed'], value
        assert value['standard_token'] == value['strict_token'] == value['streaming_token']
        semantic = {k:v for k,v in value.items() if not k.endswith('_mib_s')}
        digest = sha(artifact)
        if expected:
            assert semantic == expected['semantic'], (phase,semantic,expected['semantic'])
            if mode == 'nanocompile' and phase in ('hit','revert'):
                assert digest == expected['artifact_sha256']
        if mode == 'nanocompile':
            hit = phase in ('hit','revert')
            assert counts.get('hit',0) == int(hit) and counts.get('miss',0) == int(not hit), (phase,counts)
        row = {'mode':mode,'phase':phase,'iteration':iteration,'seconds':elapsed,'events':counts,
               'artifact_sha256':digest,'artifact_bytes':artifact.stat().st_size,'semantic':semantic,
               'zig_cache_deleted_before_build':empty_zig,'command':command}
        report['builds'].append(row);save()
        print(json.dumps({k:v for k,v in row.items() if k not in ('semantic','command')}),flush=True)
        return row
    try:
        for i in range(args.cold_runs):
            for mode in (('direct','nanocompile') if i%2==0 else ('nanocompile','direct')):
                reset(mode);build(mode,'cold',i,True)
        prime = {mode:next(x for x in reversed(report['builds']) if x['mode']==mode) for mode in ('direct','nanocompile')}
        assert prime['direct']['semantic'] == prime['nanocompile']['semantic']
        for i in range(args.hit_runs):
            for mode in (('direct','nanocompile') if i%2==0 else ('nanocompile','direct')):
                build(mode,'hit',i,mode=='nanocompile',prime[mode])
        for i in range(args.edit_runs):
            write_sources()
            initial={}
            for mode in ('direct','nanocompile'):
                reset(mode);initial[mode]=build(mode,'edit_prime',i,True)
            for phase,leaf,dependency in [('leaf_edit',True,False),('shared_edit',True,True),('revert',False,False)]:
                write_sources(leaf,dependency)
                rows={}
                for mode in (('direct','nanocompile') if i%2==0 else ('nanocompile','direct')):
                    rows[mode]=build(mode,phase,i,expected=initial[mode] if phase=='revert' else None)
                assert rows['direct']['semantic'] == rows['nanocompile']['semantic']
                assert rows['direct']['semantic']['iterations'] == (25 if leaf else 24)
        report['summary_seconds'] = {phase:{mode:statistics.median(x['seconds'] for x in report['builds'] if x['phase']==phase and x['mode']==mode)
            for mode in ('direct','nanocompile')} for phase in ('cold','hit','leaf_edit','shared_edit','revert')}
    finally:
        write_sources(restore_times=True)
        report['sources_restored'] = all(sha(project/name)==digest for name,digest in sources.items())
        save()
        assert report['sources_restored']
    print(json.dumps(report['summary_seconds'],indent=2))


if __name__ == '__main__':
    main()
