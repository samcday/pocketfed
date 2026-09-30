#!/bin/bash
# Assemble a small explicit context; never send the shared dirty repo as context.
set -euo pipefail
if [ "$#" -ne 5 ]; then
    echo "Usage: $0 KERNEL_IMAGE VERIFIED_RUNTIME_RPMS VERIFIED_POLICY_INPUTS NEW_CONTEXT LOCAL_IMAGE_TAG" >&2
    exit 2
fi
kernel_image=$1
runtime_rpms=$(realpath "$2")
policy_inputs=$(realpath "$3")
context=$4
tag=$5
case "$tag" in localhost/*) ;; *) echo 'A local trial tag is required' >&2; exit 2;; esac
test ! -e "$context"
test -f "$runtime_rpms/SHA256SUMS"
here=$(cd -- "$(dirname -- "$0")" && pwd)
python3 "$here/validate-inputs.py" "$runtime_rpms"
cmp "$here/policy-artifacts.json" "$policy_inputs/manifest.json"
python3 "$here/install-policy.py" --check-only "$policy_inputs"
kernel_id=$(podman image inspect --format '{{.Id}}' "$kernel_image")
test -n "$kernel_id"
mkdir -p "$context/firmware"
cp "$here/Containerfile" "$here/install-userspace.sh" "$here/validate-inputs.py" \
    "$here/install-policy.py" "$here/policy-artifacts.json" "$context/"
cp -a "$runtime_rpms" "$context/runtime-rpms"
cp -a "$policy_inputs" "$context/policy-inputs"
for name in extract-firmware.py firmware-manifest.json pocketfed-fingerprint-firmware.service \
    qsee-shared-loader@cmnlib64.service.d qsee-app-loader@fpctzappfingerprint.service.d; do
    cp -a "$here/../$name" "$context/firmware/"
done
podman build --layers --pull=never --network=none --arch=aarch64 --security-opt label=disable \
    --build-arg "KERNEL_IMAGE=$kernel_id" --tag "$tag" "$context"
