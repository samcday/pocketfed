#!/usr/bin/python3
"""Independent final-image inventory against the current daily image.

The old trial validator requires two DRM modules in its historic initramfs.
The newer Plymouth baseline has a different initramfs inventory. Preserve and
compare that exact current inventory, while retaining independent boot parsing.
"""
import argparse,ast,contextlib,hashlib,io,json,os,re,runpy,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--base-parser',type=Path,required=True);p.add_argument('--fingerprint-parser',type=Path,required=True);a=p.parse_args()
output=io.StringIO()
with contextlib.redirect_stdout(output):runpy.run_path(str(a.base_parser),run_name='__main__')
r=json.loads(output.getvalue())
# Reuse only independently written format parsers, without the old top-level
# baseline assertions; no modifications to their parsing functions.
tree=ast.parse(a.fingerprint_parser.read_text());tree.body=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom,ast.FunctionDef))]
ns={};exec(compile(tree,str(a.fingerprint_parser),'exec'),ns)
module=Path('/usr/lib/modules')/r['kernel_release'];assert module.name=='7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
r['fingerprint_dt']=ns['fingerprint_facts'](module);assert r['fingerprint_dt']['present']
r['fingerprint_modules']={name:subprocess.check_output(['modinfo','-k',module.name,'-F','vermagic',name],text=True).strip() for name in ('fpc1020','qseecomtee')}
assert all(v.split()[0]==module.name for v in r['fingerprint_modules'].values())
listing=subprocess.check_output(['lsinitrd',str(module/'initramfs.img')],text=True)
r['initramfs_modules']=sorted(set(re.findall(r'usr/lib/modules/[^/]+/(kernel/\S+\.ko(?:\.(?:xz|zst|gz))?)',listing)))
r['packages_evra']=sorted(subprocess.check_output(['rpm','-qa','--qf','%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n'],text=True).splitlines())
facts=ns['file_facts']
for key,roots in {'authentication':['/etc/pam.d','/usr/lib/pam.d','/etc/authselect','/etc/phrog','/etc/greetd','/etc/dracut.conf.d'],'systemd':['/etc/systemd/system','/etc/systemd/user','/usr/lib/systemd/system','/usr/lib/systemd/user'],'selinux':['/etc/selinux/targeted/policy','/etc/selinux/targeted/contexts/files']}.items():
 r[key]={str(p):v for root in roots for p in sorted(Path(root).rglob('*')) if (v:=facts(p)) is not None}
r['activation_masks']={n:os.readlink('/etc/systemd/system/'+n) for n in ('fprintd.service','qsee-supplicant.service','pocketfed-fpc-auth.socket','pocketfed-fpc-provision@.service','phosh-fingerprint-auth.socket')}
assert set(r['activation_masks'].values())=={'/dev/null'}
r['broker_runtime_state_present']=Path('/var/lib/pocketfed-fpc-auth').exists() or Path('/run/pocketfed-fpc-auth').exists()
r['initialization_marker_present']=Path('/var/lib/fprint/fpc-qsee/initialize-empty').exists()
assert not r['broker_runtime_state_present'] and not r['initialization_marker_present']
p=Path('/usr/share/pocketfed/fingerprint-trial/daily-upgrade.json')
r['upgrade_report']=json.loads(p.read_text()) if p.exists() else None
print(json.dumps(r,indent=2,sort_keys=True))
