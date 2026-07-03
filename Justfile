set dotenv-load

mkosi := env("PF_MKOSI", "mkosi")
sudo := env("PF_SUDO", "sudo")
podman := env("PF_PODMAN", "podman")

kernel_tree := env("PF_KERNEL_TREE", "vendor/kernel")
kernel_build_dir := env("PF_KERNEL_BUILD_DIR", ".linux-build")
kernel_stage := env("PF_KERNEL_STAGE", "base/mkosi.local/kernel")
kernel_configs := env("PF_KERNEL_CONFIGS", "kernel/configs")
kernel_profile := env("PF_KERNEL_PROFILE", kernel_configs / "profiles/fedora.list")
kernel_config := env("PF_KERNEL_CONFIG", "pocketfed-local.config")
kernel_image := env("PF_KERNEL_IMAGE", "Image")

base_dir := env("PF_BASE_DIR", "base")
base_output := env("PF_BASE_OUTPUT", base_dir / "mkosi.output")
base_rootfs := env("PF_BASE_ROOTFS", base_output / ("pocketfed-base_" + tag))
base_erofs := env("PF_BASE_EROFS", base_output / "rootfs.ero")
base_oci_dir := env("PF_BASE_OCI_DIR", base_output / "pocketfed-base.oci")

tag := env("PF_TAG", "rawhide")
owner := env("PF_OWNER", "samcday")
oci_output := env("PF_OCI_OUTPUT", "oci:" + base_oci_dir + ":" + tag)

base := env("PF_DEVICE_BASE", "ghcr.io/" + owner + "/pocketfed-phosh:" + tag)
device := env("PF_DEVICE", "")
image := env("PF_DEVICE_IMAGE", "")
desktop_base := env("PF_DESKTOP_BASE", "ghcr.io/" + owner + "/pocketfed-base:" + tag)
desktop := env("PF_DESKTOP", "")
desktop_image := env("PF_DESKTOP_IMAGE", "")
desktop_build_image := env("PF_DESKTOP_BUILD_IMAGE", "")
desktop_pull := env("PF_DESKTOP_PULL", "missing")

default: base

base: (submodule "vendor/make-dynpart-mappings") kernel-stage
    #!/usr/bin/env bash
    set -euo pipefail

    SUDO="{{sudo}}"
    $SUDO {{mkosi}} -f -C "{{base_dir}}" --image-version "{{tag}}" build

kernel-build: (submodule "vendor/kernel")
    #!/usr/bin/env bash
    set -euo pipefail

    tree="{{kernel_tree}}"
    build_dir="{{kernel_build_dir}}"
    profile="{{kernel_profile}}"
    extra_config="{{kernel_config}}"

    if [[ ! -f "$tree/Makefile" ]]; then
        echo "missing kernel tree: $tree" >&2
        echo "run: just submodule vendor/kernel" >&2
        echo "or set PF_KERNEL_TREE to an existing kernel checkout" >&2
        exit 1
    fi
    if [[ ! -f "$profile" ]]; then
        echo "missing kernel profile: $profile" >&2
        exit 1
    fi
    if [[ ! -f "$extra_config" ]]; then
        echo "missing kernel config override: $extra_config" >&2
        exit 1
    fi

    mkdir -p "$build_dir"
    tree=$(realpath "$tree")
    build_dir=$(realpath "$build_dir")
    profile=$(realpath "$profile")
    config_dir=$(realpath "$(dirname "$profile")/..")
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

    mapfile -t fragment_specs < <(grep -vE '^[[:space:]]*($|#)' "$profile")
    fragments=()
    for fragment in "${fragment_specs[@]}"; do
        if [[ "$fragment" = /* ]]; then
            fragment_path="$fragment"
        else
            fragment_path="$config_dir/$fragment"
        fi
        if [[ ! -f "$fragment_path" ]]; then
            echo "missing kernel config fragment: $fragment" >&2
            echo "looked under: $config_dir" >&2
            exit 1
        fi
        fragments+=("$fragment_path")
    done

    (
        cd "$tree"
        env "${make_args[@]}" scripts/kconfig/merge_config.sh -n -r -O "$build_dir" /dev/null "${fragments[@]}" "$extra_config"
    )

    make -C "$tree" O="$build_dir" "${make_args[@]}" olddefconfig
    make -C "$tree" O="$build_dir" "${make_args[@]}" -j "$jobs" Image Image.gz modules dtbs

kernel-stage: kernel-build
    #!/usr/bin/env bash
    set -euo pipefail

    tree=$(realpath "{{kernel_tree}}")
    build_dir=$(realpath "{{kernel_build_dir}}")
    stage=$(realpath -m "{{kernel_stage}}")
    image="{{kernel_image}}"

    kver=$(<"$build_dir/include/config/kernel.release")
    module_dir="$stage/usr/lib/modules/$kver"

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

    rm -rf "$stage"
    mkdir -p "$stage"

    make -C "$tree" O="$build_dir" \
        "${make_args[@]}" \
        INSTALL_MOD_PATH="$stage/usr" \
        INSTALL_MOD_STRIP="${PF_KERNEL_INSTALL_MOD_STRIP:-1}" \
        DEPMOD=true \
        modules_install

    rm -f "$module_dir/build" "$module_dir/source"
    install -Dm0644 "$build_dir/arch/arm64/boot/$image" "$module_dir/vmlinuz"
    install -Dm0644 "$build_dir/.config" "$module_dir/config"
    if [[ -f "$build_dir/System.map" ]]; then
        install -Dm0644 "$build_dir/System.map" "$module_dir/System.map"
    fi

    dtb_src="$build_dir/arch/arm64/boot/dts"
    dtb_dst="$module_dir/dtb"
    while IFS= read -r -d '' dtb; do
        rel=${dtb#"$dtb_src"/}
        install -Dm0644 "$dtb" "$dtb_dst/$rel"
    done < <(find "$dtb_src" -type f -name '*.dtb' -print0)

    depmod -b "$stage/usr" "$kver"

    [[ -f "$module_dir/dtb/qcom/sdm845-oneplus-fajita.dtb" ]] || {
        echo "staged kernel is missing fajita DTB" >&2
        exit 1
    }
    if ! modinfo -b "$stage/usr" -k "$kver" ublk_drv >/dev/null 2>&1 \
        && ! grep -Eq '^CONFIG_BLK_DEV_UBLK=y$' "$module_dir/config"; then
        echo "staged kernel is missing ublk_drv" >&2
        exit 1
    fi

    printf 'staged local kernel %s at %s\n' "$kver" "$stage"

kernel-clean:
    rm -rf "{{kernel_build_dir}}" "{{kernel_stage}}"

submodule path:
    git submodule update --init --recursive --depth 1 -- "{{path}}"

base-summary:
    {{mkosi}} -C "{{base_dir}}" summary

base-clean:
    {{sudo}} {{mkosi}} -C "{{base_dir}}" clean

base-erofs: base
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

base-oci: base
    #!/usr/bin/env bash
    set -euo pipefail

    oci_dir="{{base_oci_dir}}"
    if [[ ! -f "$oci_dir/index.json" ]]; then
        echo "missing base OCI layout: $oci_dir" >&2
        exit 1
    fi
    if [[ ! -r "$oci_dir/index.json" ]]; then
        echo "base OCI index is not readable: $oci_dir/index.json" >&2
        exit 1
    fi

    printf '%s\n' "$oci_dir"

desktop:
    #!/usr/bin/env bash
    set -euo pipefail

    desktop="{{desktop}}"
    base="{{desktop_base}}"
    image="{{desktop_image}}"
    build_image="{{desktop_build_image}}"
    pull="{{desktop_pull}}"

    if [[ -z "$desktop" ]]; then
        echo "PF_DESKTOP is required" >&2
        exit 1
    fi
    if [[ -z "$image" ]]; then
        image="ghcr.io/{{owner}}/pocketfed-$desktop:{{tag}}"
    fi
    if [[ -z "$build_image" ]]; then
        build_image="localhost/pocketfed-$desktop:build"
    fi

    containerfile="$desktop/Containerfile"
    if [[ ! -f "$containerfile" ]]; then
        echo "missing desktop Containerfile: $containerfile" >&2
        exit 1
    fi

    {{podman}} build \
        --arch arm64 \
        --pull="$pull" \
        --build-arg "BASE_IMAGE=$base" \
        -f "$containerfile" \
        -t "$build_image" \
        .

    if command -v rpm-ostree >/dev/null 2>&1; then
        rpm-ostree compose build-chunked-oci \
            --bootc \
            --format-version=1 \
            --from "$build_image" \
            --output "containers-storage:$image"
    else
        graph_root=$({{podman}} info --format '{{ "{{" }}.Store.GraphRoot{{ "}}" }}')
        {{podman}} run --rm --privileged \
            -v "$graph_root:/var/lib/containers/storage" \
            "$build_image" \
            rpm-ostree compose build-chunked-oci \
                --bootc \
                --format-version=1 \
                --from "$build_image" \
                --output "containers-storage:$image"
    fi

device: (submodule "vendor/abl-exorcist")
    #!/usr/bin/env bash
    set -euo pipefail

    device="{{device}}"
    base="{{base}}"
    image="{{image}}"

    if [[ -z "$device" ]]; then
        echo "device= is required" >&2
        exit 1
    fi
    if [[ -z "$image" ]]; then
        image="ghcr.io/{{owner}}/pocketfed-phosh-$device:{{tag}}"
    fi

    containerfile="devices/$device/Containerfile"
    if [[ ! -f "$containerfile" ]]; then
        echo "missing device Containerfile: $containerfile" >&2
        exit 1
    fi

    {{podman}} build \
        --arch arm64 \
        --build-arg "BASE_IMAGE=$base" \
        -f "$containerfile" \
        -t "$image" \
        .

base-inspect:
    {{sudo}} skopeo inspect "{{oci_output}}"

vars:
    @printf 'base_dir=%s\n' "{{base_dir}}"
    @printf 'base_rootfs=%s\n' "{{base_rootfs}}"
    @printf 'base_erofs=%s\n' "{{base_erofs}}"
    @printf 'base_oci_dir=%s\n' "{{base_oci_dir}}"
    @printf 'owner=%s\n' "{{owner}}"
    @printf 'desktop=%s\n' "{{desktop}}"
    @printf 'desktop_base=%s\n' "{{desktop_base}}"
    @printf 'desktop_image=%s\n' "{{desktop_image}}"
    @printf 'desktop_build_image=%s\n' "{{desktop_build_image}}"
    @printf 'desktop_pull=%s\n' "{{desktop_pull}}"
    @printf 'podman=%s\n' "{{podman}}"
    @printf 'kernel_tree=%s\n' "{{kernel_tree}}"
    @printf 'kernel_build_dir=%s\n' "{{kernel_build_dir}}"
    @printf 'kernel_stage=%s\n' "{{kernel_stage}}"
    @printf 'kernel_configs=%s\n' "{{kernel_configs}}"
    @printf 'kernel_profile=%s\n' "{{kernel_profile}}"
    @printf 'kernel_config=%s\n' "{{kernel_config}}"
    @printf 'kernel_image=%s\n' "{{kernel_image}}"
    @printf 'oci_output=%s\n' "{{oci_output}}"
