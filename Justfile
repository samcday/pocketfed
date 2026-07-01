set dotenv-load

mkosi := env("PF_MKOSI", "mkosi")
sudo := env("PF_SUDO", "sudo")

kernel_tree := env("PF_KERNEL_TREE", "linux")
kernel_build_dir := env("PF_KERNEL_BUILD_DIR", ".linux-build")
kernel_stage := env("PF_KERNEL_STAGE", "base/mkosi.local/kernel")
kernel_profile := env("PF_KERNEL_PROFILE", "pocketfed-configs/profiles/fedora.list")
kernel_config := env("PF_KERNEL_CONFIG", "pocketfed-local.config")
kernel_image := env("PF_KERNEL_IMAGE", "Image")

base_dir := env("PF_BASE_DIR", "base")
base_output := env("PF_BASE_OUTPUT", base_dir / "mkosi.output")
base_rootfs := env("PF_BASE_ROOTFS", base_output / "rootfs")
base_erofs := env("PF_BASE_EROFS", base_output / "rootfs.ero")
base_oci_dir := env("PF_BASE_OCI_DIR", base_output / "pocketfed-base.oci")
base_ostree_erofs := env("PF_BASE_OSTREE_EROFS", base_output / "rootfs.ostree.ero")
base_ostree_metadata := env("PF_BASE_OSTREE_METADATA", base_output / "rootfs.ostree.json")
base_aboot_output := env("PF_BASE_ABOOT_OUTPUT", base_output / "fajita")
ostree_stateroot := env("PF_OSTREE_STATEROOT", "pocketfed")
aboot_compatible := env("PF_ABOOT_COMPATIBLE", "oneplus,fajita")
aboot_root_label := env("PF_ABOOT_ROOT_LABEL", "pfroot")
aboot_ext4_size := env("PF_ABOOT_EXT4_SIZE", "8G")

tag := env("PF_TAG", "rawhide")
oci_output := env("PF_OCI_OUTPUT", "oci:" + base_oci_dir + ":" + tag)

default: base

base: base-erofs

kernel-build:
    #!/usr/bin/env bash
    set -euo pipefail

    tree="{{kernel_tree}}"
    build_dir="{{kernel_build_dir}}"
    profile="{{kernel_profile}}"
    extra_config="{{kernel_config}}"

    if [[ ! -f "$tree/Makefile" ]]; then
        echo "missing kernel submodule: $tree" >&2
        echo "run: git submodule update --init linux" >&2
        exit 1
    fi
    if [[ ! -f "$tree/$profile" ]]; then
        echo "missing kernel profile: $tree/$profile" >&2
        exit 1
    fi
    if [[ ! -f "$extra_config" ]]; then
        echo "missing kernel config override: $extra_config" >&2
        exit 1
    fi

    mkdir -p "$build_dir"
    tree=$(realpath "$tree")
    build_dir=$(realpath "$build_dir")
    extra_config=$(realpath "$extra_config")

    cross_compile="${PF_KERNEL_CROSS_COMPILE:-}"
    if [[ -z "$cross_compile" && "$(uname -m)" != "aarch64" ]]; then
        cross_compile=aarch64-linux-gnu-
    fi

    make_args=(ARCH=arm64)
    if [[ -n "$cross_compile" ]]; then
        make_args+=(CROSS_COMPILE="$cross_compile")
    fi
    if [[ -n "${PF_KERNEL_LLVM:-}" ]]; then
        make_args+=(LLVM="$PF_KERNEL_LLVM")
    fi

    jobs="${PF_KERNEL_JOBS:-}"
    if [[ -z "$jobs" ]]; then
        jobs=$(nproc)
    fi

    mapfile -t fragments < <(grep -vE '^[[:space:]]*($|#)' "$tree/$profile")
    (
        cd "$tree"
        env "${make_args[@]}" scripts/kconfig/merge_config.sh -n -r -O "$build_dir" /dev/null "${fragments[@]}" "$extra_config"
    )

    make -C "$tree" O="$build_dir" "${make_args[@]}" olddefconfig
    make -C "$tree" O="$build_dir" "${make_args[@]}" -j "$jobs" Image Image.gz modules dtbs

kernel-stage: kernel-build
    #!/usr/bin/env bash
    set -euo pipefail

    scripts/stage-local-kernel \
        --tree "{{kernel_tree}}" \
        --build-dir "{{kernel_build_dir}}" \
        --stage "{{kernel_stage}}" \
        --image "{{kernel_image}}"

kernel-clean:
    rm -rf "{{kernel_build_dir}}" "{{kernel_stage}}"

base-summary:
    {{mkosi}} -C "{{base_dir}}" summary

base-rootfs: kernel-stage
    #!/usr/bin/env bash
    set -euo pipefail

    SUDO="{{sudo}}"
    $SUDO {{mkosi}} -f -C "{{base_dir}}" --image-version "{{tag}}" build

base-bootc-rootfs: kernel-stage
    #!/usr/bin/env bash
    set -euo pipefail

    SUDO="{{sudo}}"
    $SUDO {{mkosi}} -f -C "{{base_dir}}" --profile bootc --image-version "{{tag}}" build

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

base-lint-rootfs: base-bootc-rootfs
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

base-oci: base-bootc-rootfs
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

base-fajita-images: base-oci
    #!/usr/bin/env bash
    set -euo pipefail

    SUDO="{{sudo}}"
    args=(
        --imgref "{{oci_output}}"
        --output-dir "{{base_aboot_output}}"
        --stateroot "{{ostree_stateroot}}"
        --compatible "{{aboot_compatible}}"
        --root-label "{{aboot_root_label}}"
        --size "{{aboot_ext4_size}}"
    )

    if [[ -n "${PF_ABOOT_NAME:-}" ]]; then
        args+=(--name "$PF_ABOOT_NAME")
    fi
    if [[ -n "${PF_ABOOT_RUNTIME_CMDLINE:-}" ]]; then
        args+=(--runtime-cmdline "$PF_ABOOT_RUNTIME_CMDLINE")
    fi
    if [[ -n "${PF_DROID_EXORCIST:-}" ]]; then
        args+=(--droid-exorcist "$PF_DROID_EXORCIST")
    fi
    if [[ -n "${PF_DROID_EXORCIST_ASSEMBLER:-}" ]]; then
        args+=(--droid-exorcist-assembler "$PF_DROID_EXORCIST_ASSEMBLER")
    fi
    if [[ -n "${PF_DROID_EXORCIST_SHIM:-}" ]]; then
        args+=(--droid-exorcist-shim "$PF_DROID_EXORCIST_SHIM")
    fi
    if [[ -n "${PF_OSTREE_TARGET_IMGREF:-}" ]]; then
        args+=(--target-imgref "$PF_OSTREE_TARGET_IMGREF")
    fi
    if [[ -n "${PF_ABOOT_KEEP_WORK:-}" ]]; then
        args+=(--keep-work)
    fi
    if [[ -n "${PF_ABOOT_WORK_DIR:-}" ]]; then
        args+=(--work-dir "$PF_ABOOT_WORK_DIR")
    fi
    if [[ -n "${PF_OSTREE_KARGS:-}" ]]; then
        while IFS= read -r karg; do
            [[ -n "$karg" ]] || continue
            args+=(--karg "$karg")
        done <<<"$PF_OSTREE_KARGS"
    fi

    $SUDO scripts/oci-to-aboot-ext4 "${args[@]}"

base-inspect:
    {{sudo}} skopeo inspect "{{oci_output}}"

vars:
    @printf 'base_dir=%s\n' "{{base_dir}}"
    @printf 'base_rootfs=%s\n' "{{base_rootfs}}"
    @printf 'base_erofs=%s\n' "{{base_erofs}}"
    @printf 'base_oci_dir=%s\n' "{{base_oci_dir}}"
    @printf 'base_ostree_erofs=%s\n' "{{base_ostree_erofs}}"
    @printf 'base_ostree_metadata=%s\n' "{{base_ostree_metadata}}"
    @printf 'base_aboot_output=%s\n' "{{base_aboot_output}}"
    @printf 'kernel_tree=%s\n' "{{kernel_tree}}"
    @printf 'kernel_build_dir=%s\n' "{{kernel_build_dir}}"
    @printf 'kernel_stage=%s\n' "{{kernel_stage}}"
    @printf 'kernel_profile=%s\n' "{{kernel_profile}}"
    @printf 'kernel_config=%s\n' "{{kernel_config}}"
    @printf 'kernel_image=%s\n' "{{kernel_image}}"
    @printf 'ostree_stateroot=%s\n' "{{ostree_stateroot}}"
    @printf 'aboot_compatible=%s\n' "{{aboot_compatible}}"
    @printf 'aboot_root_label=%s\n' "{{aboot_root_label}}"
    @printf 'aboot_ext4_size=%s\n' "{{aboot_ext4_size}}"
    @printf 'oci_output=%s\n' "{{oci_output}}"
