set dotenv-load

mkosi := env("PF_MKOSI", "mkosi")
sudo := env("PF_SUDO", "sudo")

base_dir := env("PF_BASE_DIR", "base")
base_output := env("PF_BASE_OUTPUT", base_dir / "mkosi.output")
base_rootfs := env("PF_BASE_ROOTFS", base_output / "rootfs")
base_erofs := env("PF_BASE_EROFS", base_output / "rootfs.ero")
base_oci_dir := env("PF_BASE_OCI_DIR", base_output / "pocketfed-base.oci")
base_ostree_erofs := env("PF_BASE_OSTREE_EROFS", base_output / "rootfs.ostree.ero")
base_ostree_metadata := env("PF_BASE_OSTREE_METADATA", base_output / "rootfs.ostree.json")
ostree_stateroot := env("PF_OSTREE_STATEROOT", "pocketfed")

tag := env("PF_TAG", "rawhide")
oci_output := env("PF_OCI_OUTPUT", "oci:" + base_oci_dir + ":" + tag)

default: base

base: base-erofs

base-summary:
    {{mkosi}} -C "{{base_dir}}" summary

base-rootfs:
    #!/usr/bin/env bash
    set -euo pipefail

    SUDO="{{sudo}}"
    $SUDO {{mkosi}} -f -C "{{base_dir}}" --image-version "{{tag}}" build

base-normalize-rootfs: base-rootfs
    #!/usr/bin/env bash
    set -euo pipefail

    rootfs="{{base_rootfs}}"

    if [[ ! -d "$rootfs" ]]; then
        echo "missing base rootfs: $rootfs" >&2
        exit 1
    fi

base-clean:
    {{sudo}} {{mkosi}} -C "{{base_dir}}" clean

base-lint-rootfs: base-normalize-rootfs
    {{sudo}} bootc container lint --rootfs "{{base_rootfs}}" --no-truncate

base-erofs: base-normalize-rootfs
    #!/usr/bin/env bash
    set -euo pipefail

    SUDO="{{sudo}}"
    rootfs="{{base_rootfs}}"
    output="{{base_erofs}}"

    if [[ ! -d "$rootfs" ]]; then
        echo "missing base rootfs: $rootfs" >&2
        exit 1
    fi

    mkdir -p "$(dirname "$output")"
    $SUDO rm -f "$output"
    $SUDO mkfs.erofs "$output" "$rootfs"
    if [[ -n "$SUDO" && "$(id -u)" != 0 ]]; then
        $SUDO chown "$(id -u):$(id -g)" "$output"
    fi

base-oci: base-rootfs
    #!/usr/bin/env bash
    set -euo pipefail

    oci_dir="{{base_oci_dir}}"

    if [[ ! -f "$oci_dir/index.json" ]]; then
        echo "missing base OCI layout: $oci_dir" >&2
        exit 1
    fi

    printf '%s\n' "$oci_dir"

ostree-erofs imgref output:
    #!/usr/bin/env bash
    set -euo pipefail

    SUDO="{{sudo}}"
    args=(
        --imgref "{{imgref}}"
        --output "{{output}}"
        --stateroot "{{ostree_stateroot}}"
    )

    if [[ -n "${PF_OSTREE_METADATA:-}" ]]; then
        args+=(--metadata "$PF_OSTREE_METADATA")
    fi
    if [[ -n "${PF_OSTREE_TARGET_IMGREF:-}" ]]; then
        args+=(--target-imgref "$PF_OSTREE_TARGET_IMGREF")
    fi
    if [[ -n "${PF_OSTREE_EROFS_CLUSTER_SIZE:-}" ]]; then
        args+=(--erofs-cluster-size "$PF_OSTREE_EROFS_CLUSTER_SIZE")
    fi
    if [[ -n "${PF_OSTREE_KEEP_WORK:-}" ]]; then
        args+=(--keep-work)
    fi
    if [[ -n "${PF_OSTREE_KARGS:-}" ]]; then
        while IFS= read -r karg; do
            [[ -n "$karg" ]] || continue
            args+=(--karg "$karg")
        done <<<"$PF_OSTREE_KARGS"
    fi

    $SUDO scripts/oci-to-ostree-erofs "${args[@]}"

base-ostree-erofs: base-oci
    #!/usr/bin/env bash
    set -euo pipefail

    SUDO="{{sudo}}"
    args=(
        --imgref "{{oci_output}}"
        --output "{{base_ostree_erofs}}"
        --metadata "{{base_ostree_metadata}}"
        --stateroot "{{ostree_stateroot}}"
    )

    if [[ -n "${PF_OSTREE_TARGET_IMGREF:-}" ]]; then
        args+=(--target-imgref "$PF_OSTREE_TARGET_IMGREF")
    fi
    if [[ -n "${PF_OSTREE_EROFS_CLUSTER_SIZE:-}" ]]; then
        args+=(--erofs-cluster-size "$PF_OSTREE_EROFS_CLUSTER_SIZE")
    fi
    if [[ -n "${PF_OSTREE_KEEP_WORK:-}" ]]; then
        args+=(--keep-work)
    fi
    if [[ -n "${PF_OSTREE_KARGS:-}" ]]; then
        while IFS= read -r karg; do
            [[ -n "$karg" ]] || continue
            args+=(--karg "$karg")
        done <<<"$PF_OSTREE_KARGS"
    fi

    $SUDO scripts/oci-to-ostree-erofs "${args[@]}"

base-inspect:
    {{sudo}} skopeo inspect "{{oci_output}}"

vars:
    @printf 'base_dir=%s\n' "{{base_dir}}"
    @printf 'base_rootfs=%s\n' "{{base_rootfs}}"
    @printf 'base_erofs=%s\n' "{{base_erofs}}"
    @printf 'base_oci_dir=%s\n' "{{base_oci_dir}}"
    @printf 'base_ostree_erofs=%s\n' "{{base_ostree_erofs}}"
    @printf 'base_ostree_metadata=%s\n' "{{base_ostree_metadata}}"
    @printf 'ostree_stateroot=%s\n' "{{ostree_stateroot}}"
    @printf 'oci_output=%s\n' "{{oci_output}}"
