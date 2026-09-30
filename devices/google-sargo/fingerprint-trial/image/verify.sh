#!/bin/bash
# Offline-only image inspection; this script never opens a sensor or TA.
set -euo pipefail
if [ "$#" -ne 4 ]; then
    echo "Usage: $0 LOCAL_CANDIDATE_IMAGE NEW_EVIDENCE_DIRECTORY SUCCESSFUL_BUILD_LOG BASELINE_LINT_LOG" >&2
    exit 2
fi
candidate=$1
evidence=$2
build_log=$(realpath "$3")
base_lint=$(realpath "$4")
test ! -e "$evidence"
here=$(cd -- "$(dirname -- "$0")" && pwd)
base=7abbae67bf384120c183f236b02909dc398f01ff929a565fc4b10865f0655b85
candidate_id=$(podman image inspect "$candidate" --format '{{.Id}}')
test -n "$candidate_id"
mkdir -p "$evidence"
evidence=$(realpath "$evidence")
cp "$here/../../camera-trial/image-facts.py" "$evidence/camera-image-facts.py"
cp "$build_log" "$evidence/build.log"
cp "$base_lint" "$evidence/base-lint.log"
cp "$here/runtime-artifacts.json" "$evidence/runtime-artifacts.json"
cp "$here/policy-artifacts.json" "$evidence/policy-artifacts.json"
for kind in base candidate; do
    image=$base
    extra=()
    if [ "$kind" = candidate ]; then
        image=$candidate_id
        extra=(--require-fingerprint)
    fi
    podman run --rm --network none --arch arm64 --security-opt label=disable \
        -v "$here:/validation:ro" \
        -v "$evidence/camera-image-facts.py:/base-parser.py:ro" \
        --entrypoint /usr/bin/python3 "$image" /validation/image-facts.py \
        --base-parser /base-parser.py "${extra[@]}" > "$evidence/$kind-facts.json"
done
python3 "$here/compare-facts.py" "$evidence/base-facts.json" \
    "$evidence/candidate-facts.json" "$evidence/runtime-artifacts.json" "$evidence/policy-artifacts.json" > "$evidence/comparison.json"
# The successful final RUN already performs the full inherited OCI verifier
# and bootc lint. Bind its output to the produced image instead of repeating it.
podman image inspect "$candidate_id" > "$evidence/image-inspect.json"
python3 - "$evidence" "$candidate_id" "$here" <<'PY'
import hashlib,json,pathlib,re,sys
p=pathlib.Path(sys.argv[1]); image=json.loads((p/'image-inspect.json').read_text())[0]
log=(p/'build.log').read_text()
assert log.strip().splitlines()[-1] == sys.argv[2]
assert 'verified pocketfed kernel release 7.1.2-0.pocketfed.sdm670.11.fc46.aarch64' in log
assert 'Checks passed: 10' in log and 'Checks skipped: 1' in log
baseline_lint=(p/'base-lint.log').read_text()
warning_names=lambda s: sorted(set(re.findall(r'^Lint warning: ([^:]+):',s,re.M)))
assert warning_names(log)==warning_names(baseline_lint)
assert len(warning_names(log))==4
comparison=json.loads((p/'comparison.json').read_text())
facts=json.loads((p/'candidate-facts.json').read_text())
policy_sha=facts['selinux_policy']['/etc/selinux/targeted/policy/policy.35']['sha256']
policy_manifest=json.loads((p/'policy-artifacts.json').read_text())
assert policy_sha==policy_manifest['files']['policy.35']['candidate']['sha256']
result={'state':'local build and offline validation passed; no publish or device changes',
        'base_image_id':'7abbae67bf384120c183f236b02909dc398f01ff929a565fc4b10865f0655b85',
        'image_id':sys.argv[2], 'architecture':image['Architecture'],
        'activation':'fprintd, Phosh fingerprint socket, QSEE supplicant, broker socket and provisioning template masked; no credential or DB initialization',
        'functional_limitations': {
            'enrollment':'Production broker/backend and access policy included; genuine token issuance and successful sensor enrollment remain untested on hardware.',
            'selinux_policy_sha256':policy_sha,
            'selinux':'The image contains the exact policy and context outputs from the normal offline module-store integration and preservation checks. Actual process/device/state labels and enforcing operations remain to be tested.',
            'metadata_scope':'Policy comparison covers file bytes and symlink targets, not a full ownership, mode, xattr or SELinux inode-label audit. Mutable-state comparison covers path, type and mode, not file contents or ownership.',
            'hardware':'No sensor, secure-app, enrollment, verification, suspend/wakeup or trial boot has been exercised by this offline image validation.'},
        'full_oci_and_bootc_lint':'passed in the successful final image build layer; bound build log included',
        'initramfs_comparison':{'same_module_paths_as_working_base':len(facts['initramfs_inventory']['kernel_modules']),
            'same_dracut_modules_and_critical_config':True,
            'critical_drivers':facts['initramfs_inventory']['critical_drivers_present'],
            'dracut_warning_explanation':'The inherited strict config omits the generic drm dracut module and Plymouth, while explicitly including Sargo display drivers. Storage, display, input and rootfs support match the base.'},
        'lint_comparison':{'same_warning_categories_as_base':warning_names(log),
            'new_mutable_paths':comparison['added_mutable_state_paths']},
        'verification_sources_sha256':{name:hashlib.sha256((pathlib.Path(sys.argv[3])/name).read_bytes()).hexdigest()
            for name in ['verify.sh','image-facts.py','compare-facts.py','install-policy.py']},
        'evidence_sha256':{x.name:hashlib.sha256(x.read_bytes()).hexdigest()
                           for x in sorted(p.iterdir()) if x.is_file()}}
assert image['Architecture']=='arm64'
(p/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
PY
