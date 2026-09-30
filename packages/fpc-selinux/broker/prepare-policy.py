#!/usr/bin/python3
"""Build/query a supplementary broker policy offline; never load host policy."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import setools

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DOMAIN = 'pocketfed_fpc_auth_t'
EXEC = 'pocketfed_fpc_auth_exec_t'
NEW = {DOMAIN, EXEC}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command(*args):
    return subprocess.check_output([str(a) for a in args], text=True)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atoms(form):
    if isinstance(form, str):
        return {form}
    return set().union(*(atoms(x) for x in form)) if form else set()


def strip_types(form):
    if not isinstance(form, tuple):
        return form
    return tuple(strip_types(x) for x in form if x not in NEW)


def permissions(policy, source, target, cls):
    # Include disabled conditional branches in every negative boundary check.
    return set().union(*(set(r.perms) for r in setools.TERuleQuery(
        policy, ruletype=['allow'], source=source, target=target,
        tclass=[cls]).results()))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--policy', type=Path, required=True)
    p.add_argument('--contexts', type=Path, required=True, help='complete contexts/files directory')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir()
    helper = load('smoo_policy', REPO / 'tools/liveboot/prepare-smoo-policy.py')
    parser = load('fpc_policy', HERE.parent / 'test-policy.py')
    before = setools.SELinuxPolicy(str(a.policy))
    assert not NEW.intersection(str(t) for t in before.types())
    mod, pp = a.output / 'pocketfed_fpc_broker.mod', a.output / 'pocketfed_fpc_broker.pp'
    command('checkmodule', '-M', '-m', '-o', mod, HERE / 'pocketfed_fpc_broker.te')
    command('semodule_package', '-o', pp, '-m', mod, '-f', HERE / 'pocketfed_fpc_broker.fc')
    module = command('/usr/libexec/selinux/hll/pp', pp)
    original = helper.to_cil(a.policy, a.output / 'before.cil', before.mls)
    attributes = re.findall(r'^\(typeattribute ([^()\s]+)\)$', original, re.M)
    keep = '\n(expandtypeattribute (' + ' '.join(attributes) + ') false)\n'
    if 'cil_gen_require' not in attributes:
        keep += '(typeattribute cil_gen_require)\n'
    if '(roleattribute cil_gen_require)' not in original:
        keep += '(roleattribute cil_gen_require)\n'
    candidate = a.output / 'policy.35'
    candidate.write_bytes(helper.compile_cil(original + keep + module, before.version))
    after = setools.SELinuxPolicy(str(candidate))
    assert (before.version, before.mls) == (after.version, after.mls)
    resulting = helper.to_cil(candidate, a.output / 'after.cil', after.mls)
    old_forms = Counter(parser.cil_forms(original))
    normalized = []
    for form in parser.cil_forms(resulting):
        if form[0] == 'typeattributeset':
            form = strip_types(form)
            if form[-1] == ():
                continue
        elif atoms(form) & NEW:
            continue
        # libsemanage bookkeeping, absent from a decompiled kernel policy.
        if form[0] in ('typeattribute', 'typeattributeset', 'roleattribute', 'roleattributeset') and form[1] == 'cil_gen_require':
            continue
        normalized.append(form)
    assert Counter(normalized) == old_forms, 'existing policy changed outside new broker types'
    assert not after.lookup_type(DOMAIN).ispermissive
    assert {str(x) for x in after.lookup_type(DOMAIN).attributes()} == {'domain'}
    assert not after.lookup_type('fprintd_t').ispermissive
    perm = lambda s, t, c: permissions(after, s, t, c)
    assert 'connectto' in perm('fprintd_t', DOMAIN, 'unix_stream_socket')
    assert perm('fprintd_t', 'unconfined_service_t', 'unix_stream_socket') == permissions(
        before, 'fprintd_t', 'unconfined_service_t', 'unix_stream_socket')
    assert 'connectto' not in perm('fprintd_t', 'unconfined_service_t', 'unix_stream_socket')
    assert not perm('fprintd_t', 'pocketfed_fpc_auth_state_t', 'file') & {'open', 'read', 'write', 'append', 'create'}
    for target in ('device_t', 'fixed_disk_device_t', 'pocketfed_fpc_device_t'):
        assert not perm(DOMAIN, target, 'chr_file') & {'open', 'read', 'write', 'ioctl'}, target
    for target in ('etc_t', 'var_lib_t', 'shadow_t'):
        assert not perm(DOMAIN, target, 'file') & {'write', 'append', 'create', 'unlink'}, target
    assert 'execute' not in perm(DOMAIN, 'bin_t', 'file')
    for cls in ('tcp_socket', 'udp_socket', 'rawip_socket'):
        assert 'create' not in perm(DOMAIN, DOMAIN, cls), cls
    assert {'read', 'open', 'write', 'lock'} <= perm(DOMAIN, 'pocketfed_fpc_auth_state_t', 'file')
    assert {'getattr', 'open', 'read', 'write', 'ioctl'} <= perm(DOMAIN, 'pocketfed_fpc_tee_device_t', 'chr_file')
    ioctls = set()
    for rule in setools.TERuleQuery(after, ruletype=['allowxperm'], source=DOMAIN,
                                   target='pocketfed_fpc_tee_device_t', tclass=['chr_file']).results():
        ioctls.update(rule.perms)
    assert ioctls == {0xa400, 0xa401, 0xa402, 0xa403, 0xa405}
    transitions = list(setools.TERuleQuery(after, ruletype=['type_transition'],
        source='init_t', target=EXEC, tclass=['process']).results())
    assert len(transitions) == 1 and str(transitions[0].default) == DOMAIN
    assert 'nnp_transition' in perm('init_t', DOMAIN, 'process2')
    assert {'getattr', 'open', 'read', 'execute'} <= perm('init_t', EXEC, 'file')
    assert {'entrypoint', 'getattr', 'open', 'read', 'execute', 'map'} <= perm(DOMAIN, EXEC, 'file')
    fc = a.output / 'contexts'
    shutil.copytree(a.contexts, fc, ignore=shutil.ignore_patterns('*.bin'))
    with (fc / 'file_contexts').open('a') as f:
        f.write('\n' + (HERE / 'pocketfed_fpc_broker.fc').read_text())
    command('sefcontext_compile', '-o', fc / 'file_contexts.bin', fc / 'file_contexts')
    match = lambda path, mode, db: command('matchpathcon', '-n', '-N', '-m', mode, '-f', db, path).strip()
    assert match('/usr/bin/pocketfed-fpc-auth', 'file', fc / 'file_contexts').split(':')[2] == EXEC
    for path, mode in [('/usr/bin/pocketfed-fpc-auth', 'dir'),
                       ('/usr/bin/pocketfed-fpc-auth-extra', 'file'),
                       ('/usr/bin/pocketfed-keymaster-startup', 'file'),
                       ('/usr/bin/qsee-supplicant', 'file'),
                       ('/dev/teepriv0', 'chr_file')]:
        assert match(path, mode, fc / 'file_contexts') == match(path, mode, a.contexts / 'file_contexts')
    report = {'status': 'offline compile and boundaries passed; hardware acceptance pending',
              'base_policy_sha256': sha(a.policy), 'policy_sha256': sha(candidate),
              'module_sha256': sha(pp), 'sources': {x.name: sha(x) for x in [
                  HERE / 'pocketfed_fpc_broker.te', HERE / 'pocketfed_fpc_broker.fc', Path(__file__)]},
              'existing_policy_preserved_outside_new_types': True,
              'broker_domain_attributes': ['domain'], 'fprintd_still_confined': True,
              'fprintd_credential_access_denied': True, 'generic_service_peer_access_unchanged': True,
              'public_tee_ioctls': [hex(x) for x in sorted(ioctls)],
              'negative_checks': ['private/generic TEE and RPMB devices', 'sensor access',
                  'generic filesystem writes', 'subprocess execution', 'network socket creation',
                  'unrelated executable/path labels'], 'host_policy_loaded': False}
    (a.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: offline broker transition, peer, credential and device boundaries; existing policy preserved')


if __name__ == '__main__':
    main()
