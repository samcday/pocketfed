set dotenv-load

mkosi := env("PF_MKOSI", "mkosi")
sudo := env("PF_SUDO", "sudo")

base_dir := env("PF_BASE_DIR", "base")
base_output := env("PF_BASE_OUTPUT", base_dir / "mkosi.output")
base_rootfs := env("PF_BASE_ROOTFS", base_output / "rootfs")
base_erofs := env("PF_BASE_EROFS", base_output / "rootfs.ero")

arch := env("PF_ARCH", "arm64")
tag := env("PF_TAG", "rawhide")
base_image := env("PF_BASE_IMAGE", "localhost/pocketfed/base")
base_full_image := env("PF_BASE_FULL_IMAGE", base_image + ":" + tag)
base_build_image := env("PF_BASE_BUILD_IMAGE", base_full_image + "-build")
oci_output := env("PF_OCI_OUTPUT", "containers-storage:" + base_full_image)
oci_reference := env("PF_OCI_REFERENCE", tag)

image_title := env("PF_IMAGE_TITLE", "PocketFed Base")
image_description := env("PF_IMAGE_DESCRIPTION", "Kernel-less PocketFed headless base")

default: base

base: base-erofs base-oci

base-summary:
    {{mkosi}} -C "{{base_dir}}" summary

base-rootfs:
    {{mkosi}} -f -C "{{base_dir}}" build

base-normalize-rootfs: base-rootfs
    #!/usr/bin/env bash
    set -euo pipefail

    SUDO="{{sudo}}"
    rootfs="{{base_rootfs}}"

    if [[ ! -d "$rootfs" ]]; then
        echo "missing base rootfs: $rootfs" >&2
        exit 1
    fi

    $SUDO mkdir -p "$rootfs/run" "$rootfs/tmp" "$rootfs/var/tmp"
    $SUDO find "$rootfs/run" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
    $SUDO find "$rootfs/tmp" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
    $SUDO find "$rootfs/var/tmp" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
    $SUDO rm -rf "$rootfs/buildroot"
    $SUDO chmod 1777 "$rootfs/tmp" "$rootfs/var/tmp"

    if [[ -d "$rootfs/usr/lib/sysimage/rpm" && ! -L "$rootfs/usr/lib/sysimage/rpm" ]]; then
        $SUDO mkdir -p "$rootfs/usr/share/rpm"
        $SUDO cp -a "$rootfs/usr/lib/sysimage/rpm/." "$rootfs/usr/share/rpm/"
        $SUDO rm -rf "$rootfs/usr/lib/sysimage/rpm"
        $SUDO ln -snf ../../share/rpm "$rootfs/usr/lib/sysimage/rpm"
    fi

base-clean:
    {{mkosi}} -C "{{base_dir}}" clean

base-lint-rootfs: base-normalize-rootfs
    bootc container lint --rootfs "{{base_rootfs}}" --no-truncate

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

base-oci-build: base-lint-rootfs
    #!/usr/bin/env bash
    set -euo pipefail

    SUDO="{{sudo}}"
    rootfs="{{base_rootfs}}"
    image="{{base_build_image}}"

    if [[ ! -d "$rootfs" ]]; then
        echo "missing base rootfs: $rootfs" >&2
        exit 1
    fi

    ctr="$($SUDO buildah from --arch "{{arch}}" scratch)"
    cleanup() {
        $SUDO buildah rm "$ctr" >/dev/null 2>&1 || true
    }
    trap cleanup EXIT

    $SUDO buildah copy "$ctr" "$rootfs/." /
    $SUDO buildah config \
        --arch "{{arch}}" \
        --os linux \
        --env container=oci \
        --label containers.bootc=1 \
        --label ostree.bootable=true \
        --label org.opencontainers.image.title="{{image_title}}" \
        --label org.opencontainers.image.description="{{image_description}}" \
        --label org.opencontainers.image.version="{{tag}}" \
        --stop-signal SIGRTMIN+3 \
        --cmd '["/sbin/init"]' \
        "$ctr"
    $SUDO buildah commit --format oci "$ctr" "$image"

    trap - EXIT
    cleanup

base-oci: base-oci-build
    #!/usr/bin/env bash
    set -euo pipefail

    SUDO="{{sudo}}"

    $SUDO rpm-ostree experimental compose build-chunked-oci \
        --bootc \
        --format-version=1 \
        --from="{{base_build_image}}" \
        --reference="{{oci_reference}}" \
        --output="{{oci_output}}" \
        --label containers.bootc=1 \
        --label ostree.bootable=true \
        --label org.opencontainers.image.title="{{image_title}}" \
        --label org.opencontainers.image.description="{{image_description}}" \
        --label org.opencontainers.image.version="{{tag}}"

base-inspect:
    {{sudo}} skopeo inspect "{{oci_output}}"

vars:
    @printf 'base_dir=%s\n' "{{base_dir}}"
    @printf 'base_rootfs=%s\n' "{{base_rootfs}}"
    @printf 'base_erofs=%s\n' "{{base_erofs}}"
    @printf 'base_build_image=%s\n' "{{base_build_image}}"
    @printf 'oci_output=%s\n' "{{oci_output}}"
