"""Alternate actual C++ compilation and portable Nano warm restoration."""
import argparse,hashlib,json,os,statistics,subprocess,sys,tempfile,time
from pathlib import Path

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('binary',type=Path);p.add_argument('--compiler',default='/Library/Developer/CommandLineTools/usr/bin/clang' if sys.platform=='darwin' else 'g++');p.add_argument('--runs',type=int,default=9);p.add_argument('--output',type=Path,required=True);a=p.parse_args();binary=a.binary.resolve();rows=[]
 with tempfile.TemporaryDirectory(prefix='nano cpp benchmark ') as tmp:
  root=Path(tmp);env={k:v for k,v in os.environ.items() if not k.startswith(('NANOCOMPILE_','R2_','KACHE_'))};env.update(NANOCOMPILE_DIR=str(root/'cache'),NANOCOMPILE_CXX=a.compiler)
  if sys.platform=='darwin':env['SDKROOT']=subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip()
  (root/'source.cpp').write_text('template<unsigned N> unsigned long work(unsigned long x) { for (unsigned i=0;i<32;i++) x=(x^(x>>7))*6364136223846793005UL+i+N; return x; }\n'+''.join(f'extern "C" unsigned long f{i}(unsigned long x) {{ return work<{i}>(x); }}\n' for i in range(512)))
  flags=['-c','source.cpp','-O2','-g0','-o','object.o'];commands={'direct':[a.compiler,*flags],'nanocompile':[str(binary),'c++',*flags]}
  def build(mode,phase):
   out=root/'object.o';out.unlink(missing_ok=True);start=time.perf_counter();r=subprocess.run(commands[mode],cwd=root,env=env,capture_output=True,timeout=180);seconds=time.perf_counter()-start;assert r.returncode==0,r.stderr.decode();digest=sha(out);rows.append({'mode':mode,'phase':phase,'seconds':seconds,'object_sha256':digest});return digest
  reference=build('direct','cold');assert build('nanocompile','cold')==reference
  for i in range(a.runs):
   for mode in (('direct','nanocompile') if i%2==0 else ('nanocompile','direct')):assert build(mode,'warm')==reference
  events=(root/'cache/events').read_text().splitlines();assert events.count('cc_hit')==a.runs and events.count('cc_miss')==1
  (root/'probe.c').write_text('unsigned long f0(unsigned long); int main(void) { return (int)(f0(42)&255); }\n');subprocess.run([a.compiler,'probe.c','object.o','-o','probe'],cwd=root,env=env,check=True,capture_output=True);observed=subprocess.run([str(root/'probe')],env=env).returncode
  subprocess.run(commands['direct'],cwd=root,env=env,check=True,capture_output=True);subprocess.run([a.compiler,'probe.c','object.o','-o','probe'],cwd=root,env=env,check=True,capture_output=True);assert subprocess.run([str(root/'probe')],env=env).returncode==observed
  result={'binary_sha256':sha(binary),'compiler':a.compiler,'compiler_version':subprocess.check_output([a.compiler,'--version'],env=env,text=True),'script_sha256':sha(Path(__file__)),'method':'512 real C++ template instances, O2, g0; alternate direct recompilation and warm portable cache; remove object every time; exact object hashes, cc_hit counters and linked behavior; synthetic compiler workload, not Harness or a general cold-build improvement','rows':rows,'median_warm_seconds':{mode:statistics.median(r['seconds'] for r in rows if r['mode']==mode and r['phase']=='warm') for mode in commands}}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result['median_warm_seconds']))
if __name__=='__main__':main()
