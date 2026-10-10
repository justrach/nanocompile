"""Extend a local native contract with six individually audited C grammar scripts."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shlex


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',type=Path,required=True)
    p.add_argument('--cargo-log',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();assert not args.output.exists()
    audit_path=Path(__file__).resolve().parents[2]/'harness-grammar-script-audit.json'
    audit=json.loads(audit_path.read_bytes());spec=json.loads(args.base.read_bytes())
    template=next(item for item in spec['packages'] if item['package']=='tree-sitter')
    checked=[]
    for entry in audit['entries']:
        variables=None
        for line in args.cargo_log.read_text().splitlines():
            match=re.fullmatch(r'\s*Running `(.*)`',line)
            if not match:continue
            variables={}
            for field in shlex.split(match[1]):
                if '=' not in field or not re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',field.split('=',1)[0]):break
                key,value=field.split('=',1);variables[key]=value
            if variables.get('CARGO_PKG_NAME')==entry['package'] and 'OUT_DIR' in variables:break
        assert variables and variables.get('CARGO_PKG_NAME')==entry['package'] and variables.get('CARGO_PKG_VERSION')==entry['version']
        script=Path(variables['CARGO_MANIFEST_DIR'])/entry['script_relative_path']
        assert hashlib.sha256(script.read_bytes()).hexdigest()==entry['build_script_sha256'],'Source audit no longer matches'
        item=copy.deepcopy(template);item['package']=entry['package']
        item['environment']=[rule for rule in item['environment'] if not rule['name'].startswith('CARGO_FEATURE_') and rule['name']!='CARGO_PKG_VERSION']
        item['environment'].append(dict(name='CARGO_PKG_VERSION',value=entry['version']))
        # These native C scripts read no Cargo features; whole environment still
        # participates in the key, while native-target guards exclude wasm inputs.
        assert not any(existing['package']==item['package'] for existing in spec['packages'])
        spec['packages'].append(item);checked.append(entry['package'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(spec,indent=2)+'\n');args.output.chmod(0o600)
    record=dict(status='prepared; actual-script and full-project validation pending',packages=checked,
                base_sha256=hashlib.sha256(args.base.read_bytes()).hexdigest(),audit_sha256=hashlib.sha256(audit_path.read_bytes()).hexdigest(),
                generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),contract_sha256=hashlib.sha256(args.output.read_bytes()).hexdigest())
    args.output.with_suffix('.preparation.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))


if __name__=='__main__':main()
