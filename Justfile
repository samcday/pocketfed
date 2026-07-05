set dotenv-load

mkosi := env("PF_MKOSI", "mkosi")
sudo := env("PF_SUDO", "sudo")

base_dir := env("PF_BASE_DIR", "base")
base_output := env("PF_BASE_OUTPUT", base_dir / "mkosi.output")
base_rootfs := env("PF_BASE_ROOTFS", base_output / ("pocketfed-base_" + tag))
base_erofs := env("PF_BASE_EROFS", base_output / "rootfs.ero")
base_oci_dir := env("PF_BASE_OCI_DIR", base_output / "pocketfed-base.oci")

tag := env("PF_TAG", "rawhide")
owner := env("PF_OWNER", "samcday")
base_image := env("PF_BASE_IMAGE", "ghcr.io/" + owner + "/pocketfed-base:" + tag)
oci_output := env("PF_OCI_OUTPUT", "oci:" + base_oci_dir + ":" + tag)

base := env("PF_DEVICE_BASE", "ghcr.io/" + owner + "/pocketfed-phosh:" + tag)
device := env("PF_DEVICE", "")
image := env("PF_DEVICE_IMAGE", "")
desktop_base := env("PF_DESKTOP_BASE", base_image)
desktop := env("PF_DESKTOP", "")
desktop_image := env("PF_DESKTOP_IMAGE", "")
desktop_build_image := env("PF_DESKTOP_BUILD_IMAGE", "")
desktop_pull := env("PF_DESKTOP_PULL", "missing")
builder_image := env("PF_BUILDER_IMAGE", "ghcr.io/" + owner + "/pocketfed-image-builder:" + tag)

default: base

base: (submodule "vendor/make-dynpart-mappings")
    #!/usr/bin/env bash
    set -euo pipefail

    SUDO="{{sudo}}"
    $SUDO {{mkosi}} -f -C "{{base_dir}}" --image-version "{{tag}}" build
    $SUDO skopeo copy --all "{{oci_output}}" "containers-storage:{{base_image}}"

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

desktop:
    #!/usr/bin/env bash
    set -euo pipefail

    desktop="{{desktop}}"
    base="{{desktop_base}}"
    image="{{desktop_image}}"
    build_image="{{desktop_build_image}}"
    pull="{{desktop_pull}}"
    SUDO="{{sudo}}"

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

    $SUDO podman build \
        --arch arm64 \
        --pull="$pull" \
        --build-arg "BASE_IMAGE=$base" \
        -f "$containerfile" \
        -t "$build_image" \
        .

    if command -v rpm-ostree >/dev/null 2>&1; then
        $SUDO rpm-ostree compose build-chunked-oci \
            --bootc \
            --format-version=1 \
            --from "$build_image" \
            --output "containers-storage:$image"
    else
        graph_root=$($SUDO podman info --format '{{ "{{" }}.Store.GraphRoot{{ "}}" }}')
        $SUDO podman run --rm --privileged \
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
    SUDO="{{sudo}}"

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

    $SUDO podman build \
        --arch arm64 \
        --build-arg "BASE_IMAGE=$base" \
        -f "$containerfile" \
        -t "$image" \
        .

builder:
    {{sudo}} podman build \
        --pull=missing \
        -f builder/Containerfile \
        -t "{{builder_image}}" \
        .

base-inspect:
    {{sudo}} skopeo inspect "{{oci_output}}"

vars:
    @printf 'base_dir=%s\n' "{{base_dir}}"
    @printf 'base_rootfs=%s\n' "{{base_rootfs}}"
    @printf 'base_erofs=%s\n' "{{base_erofs}}"
    @printf 'base_oci_dir=%s\n' "{{base_oci_dir}}"
    @printf 'base_image=%s\n' "{{base_image}}"
    @printf 'owner=%s\n' "{{owner}}"
    @printf 'desktop=%s\n' "{{desktop}}"
    @printf 'desktop_base=%s\n' "{{desktop_base}}"
    @printf 'desktop_image=%s\n' "{{desktop_image}}"
    @printf 'desktop_build_image=%s\n' "{{desktop_build_image}}"
    @printf 'desktop_pull=%s\n' "{{desktop_pull}}"
    @printf 'builder_image=%s\n' "{{builder_image}}"
    @printf 'sudo=%s\n' "{{sudo}}"
    @printf 'oci_output=%s\n' "{{oci_output}}"
