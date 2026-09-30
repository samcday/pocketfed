#!/usr/bin/python3
"""Offline boot, fingerprint DT, package and authentication-policy inspection."""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import runpy
import re
import struct
import subprocess


def dt_nodes(blob):
    """Parse the FDT structure independently of the image's fdtget/finalizer."""
    header = struct.unpack_from('>10I', blob)
    magic, total, off_struct, off_strings = header[:4]
    assert magic == 0xD00DFEED and total == len(blob)
    strings_size, struct_size = header[8:10]
    assert off_struct + struct_size <= total and off_strings + strings_size <= total
    strings = blob[off_strings:off_strings + strings_size]
    pos, limit, stack, nodes = off_struct, off_struct + struct_size, [], {}
    while pos < limit:
        token = struct.unpack_from('>I', blob, pos)[0]
        pos += 4
        if token == 1:
            end = blob.index(b'\0', pos, limit)
            stack.append(blob[pos:end].decode('ascii'))
            pos = (end + 4) & ~3
            path = '/' + '/'.join(stack[1:])
            assert path not in nodes
            nodes[path] = {}
        elif token == 2:
            assert stack
            stack.pop()
        elif token == 3:
            assert stack and pos + 8 <= limit
            size, name_offset = struct.unpack_from('>II', blob, pos)
            pos += 8
            assert pos + size <= limit and name_offset < len(strings)
            name = strings[name_offset:strings.index(b'\0', name_offset)].decode('ascii')
            node = nodes['/' + '/'.join(stack[1:])]
            assert name not in node
            node[name] = blob[pos:pos + size]
            pos = (pos + size + 3) & ~3
        elif token == 4:
            pass
        else:
            assert token == 9 and not stack
            return nodes
    raise AssertionError('Missing FDT end token')


def text_list(value):
    assert value.endswith(b'\0')
    return value[:-1].decode('ascii').split('\0')


def fingerprint_facts(module):
    nodes = dt_nodes((module / 'dtb/qcom/sdm670-google-sargo.dtb').read_bytes())
    assert 'google,sargo' in text_list(nodes['/']['compatible'])
    if '/fingerprint' not in nodes:
        return {'present': False}
    fp = nodes['/fingerprint']
    assert text_list(fp['compatible']) == ['google,sargo-fingerprint', 'fpc,fpc1020']
    assert text_list(fp['firmware-name']) == ['fpctzappfingerprint']
    reset = list(struct.unpack('>3I', fp['reset-gpios']))
    irq = list(struct.unpack('>3I', fp['irq-gpios']))
    assert reset[1:] == [134, 1] and irq[1:] == [121, 0] and reset[0] == irq[0]
    providers = [(path, values) for path, values in nodes.items()
                 if values.get('phandle') == struct.pack('>I', reset[0])]
    assert len(providers) == 1
    assert 'qcom,sdm670-tlmm' in text_list(providers[0][1]['compatible'])
    assert fp.get('status', b'okay\0') in (b'okay\0', b'ok\0')
    assert fp['wakeup-source'] == b''
    return {'present': True, 'compatible': text_list(fp['compatible']),
            'firmware_name': text_list(fp['firmware-name'])[0],
            'reset_gpio': 134, 'reset_active_low': True, 'irq_gpio': 121,
            'irq_active_high': True, 'gpio_provider': providers[0][0],
            'wakeup_source': True}


def file_facts(path):
    if path.is_symlink():
        return {'symlink': str(path.readlink())}
    if path.is_file():
        data = path.read_bytes()
        return {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
    return None


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--base-parser', required=True, type=Path)
parser.add_argument('--require-fingerprint', action='store_true')
args = parser.parse_args()
buffer = io.StringIO()
with contextlib.redirect_stdout(buffer):
    runpy.run_path(str(args.base_parser), run_name='__main__')
facts = json.loads(buffer.getvalue())
facts['packages_evra'] = sorted(subprocess.check_output(['rpm', '-qa', '--qf',
    '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n'], text=True).splitlines())
module = Path('/usr/lib/modules') / facts['kernel_release']
facts['fingerprint_dt'] = fingerprint_facts(module)
listing = subprocess.check_output(['lsinitrd', str(module / 'initramfs.img')], text=True)
initrd_modules = sorted(set(re.findall(r'usr/lib/modules/[^/]+/(kernel/\S+\.ko(?:\.(?:xz|zst|gz))?)', listing)))
module_names = {Path(p).name.split('.ko', 1)[0].replace('-', '_') for p in initrd_modules}
critical = {'mmc_core', 'mmc_block', 'sdhci', 'sdhci_pltfm', 'sdhci_msm', 'cqhci',
            'msm', 'panel_samsung_s6e3fa7', 'rmi_core', 'rmi_i2c', 'gpio_keys',
            'pinctrl_sdm670', 'qnoc_sdm670', 'gcc_sdm845'}
assert critical <= module_names, sorted(critical - module_names)
config = dict(line.split('=', 1) for line in (module / 'config').read_text().splitlines()
              if line.startswith('CONFIG_') and '=' in line)
for symbol in ['CONFIG_EXT4_FS', 'CONFIG_DEVTMPFS', 'CONFIG_DRM', 'CONFIG_QCOM_SCM']:
    assert config[symbol] == 'y', (symbol, config[symbol])
assert 'usr/lib/ostree/ostree-prepare-root' in listing
assert 'usr/lib/systemd/system/ostree-prepare-root.service' in listing
facts['initramfs_inventory'] = {
    'dracut_modules': listing.split('dracut modules:\n', 1)[1].split('========', 1)[0].splitlines(),
    'kernel_modules': initrd_modules, 'critical_drivers_present': sorted(critical),
    'critical_kernel_config': {k: config[k] for k in
        ['CONFIG_EXT4_FS', 'CONFIG_DEVTMPFS', 'CONFIG_DRM', 'CONFIG_QCOM_SCM', 'CONFIG_MMC',
         'CONFIG_MMC_BLOCK', 'CONFIG_MMC_SDHCI', 'CONFIG_MMC_SDHCI_MSM',
         'CONFIG_DRM_MSM', 'CONFIG_DRM_PANEL_SAMSUNG_S6E3FA7',
         'CONFIG_RMI4_CORE', 'CONFIG_RMI4_I2C', 'CONFIG_KEYBOARD_GPIO']},
    'ostree_prepare_root_present': True}
facts['initial_activation'] = {
    'masks': {name: file_facts(Path('/etc/systemd/system') / name)
              for name in ['fprintd.service', 'phosh-fingerprint-auth.socket', 'qsee-supplicant.service',
                           'pocketfed-fpc-auth.socket', 'pocketfed-fpc-provision@.service']},
    'broker_present': any(Path(p).exists() or Path(p).is_symlink() for p in
        ['/usr/lib/systemd/system/pocketfed-fpc-auth.service',
         '/usr/lib/systemd/system/pocketfed-fpc-auth.socket', '/run/pocketfed-fpc-auth/token.sock']),
    'broker_runtime_state_present': any(Path(p).exists() or Path(p).is_symlink()
        for p in ['/var/lib/pocketfed-fpc-auth', '/run/pocketfed-fpc-auth']),
    'database_init_marker_present': Path('/var/lib/fprint/fpc-qsee/initialize-empty').exists() or
        Path('/var/lib/fprint/fpc-qsee/initialize-empty').is_symlink(),
    'build_only_helpers_present': any(Path(p).exists() or Path(p).is_symlink() for p in
        ['/tmp/install-fingerprint-userspace', '/tmp/validate-fingerprint-inputs.py',
         '/tmp/install-fingerprint-kernel', '/tmp/replace-template-dtb.py',
         '/tmp/install-fingerprint-policy.py'])}
if args.require_fingerprint:
    assert facts['fingerprint_dt']['present']
    assert facts['kernel_release'] == '7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
    facts['fingerprint_modules'] = {}
    for name in ['fpc1020', 'qseecomtee']:
        vermagic = subprocess.check_output(['modinfo', '-k', module.name, '-F', 'vermagic', name], text=True).strip()
        assert vermagic.split()[0] == module.name
        facts['fingerprint_modules'][name] = {
            'vermagic': vermagic,
            'depends': subprocess.check_output(['modinfo', '-k', module.name, '-F', 'depends', name], text=True).strip()}
paths = set()
for root in ['/etc/pam.d', '/usr/lib/pam.d', '/etc/authselect',
             '/etc/phrog', '/etc/greetd', '/etc/dracut.conf.d']:
    paths.update(Path(root).rglob('*'))
for pattern in ['/usr/lib/systemd/system/phrog.service', '/usr/lib/systemd/system/greetd.service',
                '/usr/lib/systemd/system/81voltd.service*',
                '/usr/lib/systemd/system/ModemManager.service*']:
    paths.update(Path('/').glob(pattern.lstrip('/')))
facts['authentication_and_device_policy'] = {
    str(p): data for p in sorted(paths) if (data := file_facts(p)) is not None}
facts['system_enablement'] = {str(p): str(p.readlink())
    for p in sorted(Path('/etc/systemd/system').rglob('*')) if p.is_symlink()}
facts['systemd_policy_files'] = {
    str(p): data for root in ['/etc/systemd/system', '/etc/systemd/user',
                             '/usr/lib/systemd/system', '/usr/lib/systemd/user']
    for p in sorted(Path(root).rglob('*')) if (data := file_facts(p)) is not None}
facts['selinux_policy'] = {
    str(p): data for root in ['/etc/selinux/targeted/policy',
                             '/etc/selinux/targeted/contexts/files']
    for p in sorted(Path(root).rglob('*')) if (data := file_facts(p)) is not None}
facts['mutable_state_paths'] = {str(p): {'mode': oct(p.lstat().st_mode & 0o7777),
    'type': 'symlink' if p.is_symlink() else 'directory' if p.is_dir() else 'file'}
    for p in sorted(Path('/var').rglob('*'))}
print(json.dumps(facts, indent=2, sort_keys=True))
