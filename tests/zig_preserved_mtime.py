"""Verify same-size preserved-mtime Zig dependency edits against fresh compilation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('binary',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--expect-stale',action='store_true',help='Diagnostic reproduction on an old binary only')
    args=p.parse_args()
    binary=args.binary.resolve()
    with tempfile.TemporaryDirectory(prefix='nano zig preserved ') as tmp:
        root=Path(tmp)
        (root/'main.zig').write_text('const std=@import("std"); const child=@import("child.zig"); pub fn main() void {std.debug.print("{d}\\n", .{child.value});}\n')
        child=root/'child.zig';child.write_text('pub const value:u32=42;\n');mtime=child.stat().st_mtime_ns
        env=dict(os.environ,NANOCOMPILE_DIR=str(root/'nano'),ZIG_LOCAL_CACHE_DIR=str(root/'local'),ZIG_GLOBAL_CACHE_DIR=str(root/'global'))
        command=['zig','build-exe','main.zig','-O','ReleaseFast','-femit-bin='+str(root/'value')]
        def run(wrapped):
            (root/'value').unlink(missing_ok=True)
            subprocess.run(([str(binary)] if wrapped else [])+command,cwd=root,env=env,capture_output=True,check=True)
            result=subprocess.run([str(root/'value')],capture_output=True,check=True)
            return int(result.stderr), hashlib.sha256((root/'value').read_bytes()).hexdigest()
        first,original_hash=run(True);assert first==42
        child.write_text('pub const value:u32=43;\n');os.utime(child,ns=(mtime,mtime))
        changed,changed_hash=run(True)
        # Fresh reference uses separate local parsing state; installed compiler
        # resources and source paths stay the same.
        env['ZIG_LOCAL_CACHE_DIR']=str(root/'reference-local')
        env['ZIG_GLOBAL_CACHE_DIR']=str(root/'reference-global')
        reference,_=run(False);assert reference==43
        env['ZIG_LOCAL_CACHE_DIR']=str(root/'local');env['ZIG_GLOBAL_CACHE_DIR']=str(root/'global')
        if args.expect_stale:
            assert changed==42, changed
        else:
            assert changed==reference, (changed,reference)
            restored,digest=run(True);assert restored==43 and digest==changed_hash
            child.write_text('pub const value:u32=42;\n');os.utime(child,ns=(mtime,mtime))
            reverted,digest=run(True);assert reverted==42 and digest==original_hash
            assert not list((root/'nano/producer-jobs').glob('*'))
        events=(root/'nano/events').read_text().splitlines()
        if not args.expect_stale: assert events==['miss','miss','hit','variant_hit','hit'],events
        report={'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'expected':reference,'observed_after_preserved_mtime_edit':changed,'stale_reproduced':args.expect_stale,'events':events,
                'checks':['same-size dependency edit preserves mtime','fresh compiler executes 43','wrapped result checked against fresh compiler']}
        args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__': main()
