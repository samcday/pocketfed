#!/usr/bin/python3
"""Finalize to a regular temporary file and inspect it; never flash a partition."""
import ast,hashlib,json,os,subprocess
from pathlib import Path
from gi.repository import GLib
ROOT=Path('/var/tmp/sargo-fingerprint-services-20260912')
i=json.loads((ROOT/'staged-inspection.json').read_text());e=json.loads((ROOT/'candidate-facts-current.json').read_text())
assert i['status']=='locked staged inspection passed' and not i['errors']
state=GLib.Variant.new_from_bytes(GLib.VariantType.new('a{sv}'),GLib.Bytes.new(Path('/run/ostree/staged-deployment').read_bytes()),False).unpack()
assert state['locked'] and state['target']['name']==i['staged_checksum']+'.'+str(i['staged_serial'])
root=Path(i['root']);module=root/'usr/lib/modules'/e['kernel_release']
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(module/'aboot.img')==e['boot']['sha256']
# This current baseline disables regeneration; both embedded and standalone
# initramfs/kernel/DT remain byte-identical to the independently inspected image.
assert i['regenerate_initramfs'] is False
for n in ('vmlinuz','initramfs.img','dtb/qcom/sdm670-google-sargo.dtb'):
 assert sha(module/n)==sha(Path('/usr/lib/modules')/e['kernel_release']/n),n
version=1-int(os.readlink('/boot/loader').split('.')[1])
new_target=f"/ostree/boot.{version}/pocketfed/{state['target']['bootcsum']}/0"
assert sum(x.startswith('ostree=') for x in state['kargs'])==1
options=' '.join('ostree='+new_target if x.startswith('ostree=') else x for x in state['kargs'])
view=ROOT/'boot-preview'/module.name;view.mkdir(parents=True)
for n in ('vmlinuz','initramfs.img','dtb'):(view/n).symlink_to(module/n)
subprocess.run([str(root/'usr/libexec/pocketfed-aboot-finalize'),'--options',options,'--append-options-file',str(root/'usr/lib/ostree-boot/aboot-kargs'),str(module/'aboot.img'),str(view/'aboot.img')],check=True)
tree=ast.parse((ROOT/'boot-parser.py').read_text());tree.body=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom,ast.FunctionDef))]
ns={};exec(compile(tree,'boot-parser.py','exec'),ns);boot=ns['boot_facts'](view)
for k in ('outer_shim_sha256','dtb_sha256','canonical_kernel_sha256'):assert boot[k]==e['boot'][k]
assert options in boot['cmdline']
r={'status':'regular-file boot preview passed','staged_checksum':i['staged_checksum'],'manifest':i['manifest'],'locked':True,'expected_options':options,'boot_preview':boot,'preview_path':str(view/'aboot.img'),'partition_written':False}
(ROOT/'boot-preview-validation.json').write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps({'status':r['status'],'staged_checksum':r['staged_checksum'],'bytes':boot['bytes'],'sha256':boot['sha256'],'partition_written':False},indent=2))
