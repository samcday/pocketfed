#!/usr/bin/python3
"""Compose the reviewed FPC module with an image policy without loading it."""
import argparse
from collections import Counter
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('--contexts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir()
    helper = load('smoo_policy', HERE.parents[1] / 'tools/liveboot/prepare-smoo-policy.py')
    contract = load('fpc_contract', HERE / 'test-policy.py')
    preservation = load('fpc_preservation', HERE / 'test-preservation.py')
    import setools
    before = setools.SELinuxPolicy(str(args.policy))
    assert not contract.TYPES.intersection(str(t) for t in before.types())
    mod = args.output / 'pocketfed_fpc.mod'
    pp = args.output / 'pocketfed_fpc.pp'
    subprocess.run(['checkmodule', '-M', '-m', '-o', str(mod), str(HERE / 'pocketfed_fpc.te')], check=True)
    subprocess.run(['semodule_package', '-o', str(pp), '-m', str(mod), '-f', str(HERE / 'pocketfed_fpc.fc')], check=True)
    module = subprocess.check_output(['/usr/libexec/selinux/hll/pp', str(pp)], text=True)
    assert contract.cil_forms(module) == contract.cil_forms(contract.EXPECTED_MODULE_CIL)
    original = helper.to_cil(args.policy, args.output / 'before.cil', before.mls)
    attributes = re.findall(r'^\(typeattribute ([^()\s]+)\)$', original, re.M)
    keep = '\n(expandtypeattribute (' + ' '.join(attributes) + ') false)\n'
    if 'cil_gen_require' not in attributes:
        keep += '(typeattribute cil_gen_require)\n'
    candidate = args.output / 'policy.35'
    candidate.write_bytes(helper.compile_cil(original + keep + module, before.version))
    after = setools.SELinuxPolicy(str(candidate))
    assert (before.version, before.mls) == (after.version, after.mls)
    resulting = helper.to_cil(candidate, args.output / 'after.cil', after.mls)

    def atoms(form):
        if isinstance(form, str):
            return {form}
        return set().union(*(atoms(x) for x in form)) if form else set()

    def strip_types(form):
        if not isinstance(form, tuple):
            return form
        return tuple(strip_types(x) for x in form if x not in contract.TYPES)

    normalized = []
    for form in contract.cil_forms(resulting):
        if form[0] == 'typeattributeset':
            form = strip_types(form)
            if form[-1] == ():
                continue
        elif atoms(form) & contract.TYPES:
            continue
        if form[0] in ('typeattribute', 'typeattributeset', 'roleattribute', 'roleattributeset') and form[1] == 'cil_gen_require':
            continue
        normalized.append(form)
    assert Counter(normalized) == Counter(contract.cil_forms(original)), 'existing policy forms changed'
    contexts = args.output / 'contexts'
    shutil.copytree(args.contexts, contexts, ignore=shutil.ignore_patterns('*.bin'))
    with (contexts / 'file_contexts').open('a') as stream:
        stream.write(''.join(line + '\n' for line in sorted(preservation.NEW_CONTEXTS)))
    subprocess.run(['python3', str(HERE / 'test-policy.py'), '--policy', str(args.policy),
                    '--contexts', str(args.contexts / 'file_contexts'), '--merged-policy', str(candidate),
                    '--merged-contexts', str(contexts / 'file_contexts'),
                    '--report', str(args.output / 'contract.json')], check=True)
    # The counter comparison above retains nesting and multiplicity, and strips
    # only new types after checking the exact complete module contract.
    (args.output / 'preservation.txt').write_text('PASS: every existing CIL form preserved outside the four reviewed new types.\n')
    print('PASS: reviewed FPC module composed; existing policy forms preserved')


if __name__ == '__main__':
    main()
