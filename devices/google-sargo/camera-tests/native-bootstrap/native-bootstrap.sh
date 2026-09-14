#!/usr/bin/env bash
# On-device native bootstrap for the Sargo camera stack.
#
# Clones, builds and locally installs the pinned libdng/libmegapixels/Megapixels
# stack inside a disposable PocketFed liveboot root. The liveboot root is already
# a writable overlay, so no rpm-ostree usroverlay is required or used.
#
# This script never captures a frame, suspends, reboots, or modifies a
# persistent deployment. It only runs `dnf install` and the maintained
# packages/megapixels/build-native helper.
set -euo pipefail

readonly SCRIPT_NAME=${0##*/}
readonly DEFAULT_BUILD_ROOT=/var/tmp/pocketfed-camera-native-bootstrap
readonly BUILD_JOBS=2

# Build order matters: Megapixels' BuildRequires need both libraries' -devel.
readonly PACKAGE_ORDER=(libdng libmegapixels megapixels)

# Build dependencies declared by the three package specs, as Fedora names.
readonly BUILD_PACKAGES=(
    rpm-build redhat-rpm-config systemd-rpm-macros meson gcc git gzip
    python3 pkgconf-pkg-config scdoc gperf desktop-file-utils
    libappstream-glib
    libtiff-devel libconfig-devel gtk4-devel feedbackd-devel zbar-devel
    libepoxy-devel libjpeg-turbo-devel pulseaudio-libs-devel wayland-devel
    libX11-devel libXrandr-devel
)
# Runtime dependencies the bundled postprocessor needs to save a JPEG.
readonly RUNTIME_PACKAGES=(
    dcraw ImageMagick perl-Image-ExifTool hicolor-icon-theme
)
# Camera diagnostics: libcamera 0.7.x stack plus the V4L2 userspace tools.
readonly CAMERA_PACKAGES=(
    libcamera libcamera-ipa libcamera-tools libcamera-gstreamer v4l-utils
)

check_mode=0
test_overrides=0
build_root=${DEFAULT_BUILD_ROOT}
build_user=${POCKETFED_BUILD_USER:-${SUDO_USER:-}}
expect_run_id=
machine_arch=$(uname -m)
cmdline_file=/proc/cmdline
root_fstype_override=
result_file=/run/pocketfed-liveboot/result.json
helper_topdir_template=
helper_dist=

log() { printf '%s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

usage() {
    cat <<EOF
${SCRIPT_NAME}: build and locally install the pinned Sargo camera stack in a
disposable PocketFed liveboot root.

Usage:
  sudo ${SCRIPT_NAME} --expect-run-id RUN_ID [options]

Required for an install:
  --expect-run-id RUN_ID  Exact pocketfed.liveboot= identity expected on the
                          kernel command line. The script refuses to install on
                          any other run.

Options:
  --build-root DIR        Disposable build directory (default ${DEFAULT_BUILD_ROOT}).
  --build-user USER       Unprivileged user for clone/build (default \$SUDO_USER).
                          The maintained helper builds with ${BUILD_JOBS} jobs.
  --check, --dry-run      Validate architecture, disposable liveboot root, run
                          identity and inputs, print the plan, then exit without
                          changing anything. Safe to run unprivileged.
  -h, --help              Show this help.

Advanced (--check only; never usable for an install):
  --machine-arch ARCH     Override \`uname -m\`.
  --cmdline-file PATH     Override /proc/cmdline.
  --root-fstype FSTYPE    Override the root filesystem type probe.
  --result-file PATH      Override /run/pocketfed-liveboot/result.json.

Build root:
  Must be an absolute, dedicated direct child of /var/tmp, must not be a
  symlink, and if it already exists must be owned by the build user. A
  resumable directory previously created by this helper is reused.

Safety:
  * Refuses to act unless the root filesystem is the disposable liveboot
    overlay and the run identity matches --expect-run-id.
  * Never changes a deployment or requests a system power transition, and
    never captures frames.
  * All build output stays under --build-root in /var/tmp; the liveboot root
    discards local installs on the next boot.
EOF
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --check|--dry-run) check_mode=1 ;;
            --build-root) [[ $# -ge 2 ]] || die '--build-root needs a value'; build_root=$2; shift ;;
            --build-user) [[ $# -ge 2 ]] || die '--build-user needs a value'; build_user=$2; shift ;;
            --expect-run-id) [[ $# -ge 2 ]] || die '--expect-run-id needs a value'; expect_run_id=$2; shift ;;
            --machine-arch) [[ $# -ge 2 ]] || die '--machine-arch needs a value'; machine_arch=$2; test_overrides=1; shift ;;
            --cmdline-file) [[ $# -ge 2 ]] || die '--cmdline-file needs a value'; cmdline_file=$2; test_overrides=1; shift ;;
            --root-fstype) [[ $# -ge 2 ]] || die '--root-fstype needs a value'; root_fstype_override=$2; test_overrides=1; shift ;;
            --result-file) [[ $# -ge 2 ]] || die '--result-file needs a value'; result_file=$2; test_overrides=1; shift ;;
            -h|--help) usage; exit 0 ;;
            *) die "unknown argument: $1 (try --help)" ;;
        esac
        shift
    done
}

cmdline_value() {
    local key=$1
    [[ -r $cmdline_file ]] || die "cannot read kernel command line at $cmdline_file"
    tr ' ' '\n' < "$cmdline_file" | sed -n "s/^${key}=//p" | head -n 1
}

detect_root_fstype() {
    if [[ -n $root_fstype_override ]]; then
        printf '%s' "$root_fstype_override"
    else
        findmnt -n -o FSTYPE --target / 2>/dev/null || true
    fi
}

validate_arch() {
    [[ $machine_arch == aarch64 ]] || \
        die "this bootstrap targets aarch64, but the machine is '$machine_arch'"
}

validate_liveboot_identity() {
    local fstype run_id
    fstype=$(detect_root_fstype)
    [[ -n $fstype ]] || die 'could not determine the root filesystem type'
    [[ $fstype == overlay ]] || die \
        "root filesystem is '$fstype', not the disposable liveboot overlay; refusing to modify a persistent system"
    run_id=$(cmdline_value pocketfed.liveboot)
    [[ -n $run_id ]] || die \
        'kernel command line has no pocketfed.liveboot= identity; not a PocketFed liveboot root'
    [[ -n $expect_run_id ]] || die \
        '--expect-run-id is required so installation is bound to a known liveboot run'
    [[ $run_id == "$expect_run_id" ]] || die \
        "run identity mismatch: expected '$expect_run_id', liveboot reports '$run_id'"
    if [[ -e $result_file ]]; then
        if ! python3 - "$result_file" <<'PY'
import json
import sys

with open(sys.argv[1]) as handle:
    data = json.load(handle)
checks = data.get("checks", {})
if data.get("result") != "pass" or checks.get("disposable_root") is not True:
    raise SystemExit(1)
PY
        then
            die "liveboot handoff result at $result_file is not a passing disposable-root run"
        fi
    else
        warn "no liveboot handoff result at $result_file yet; relying on root fstype and run id"
    fi
}

validate_build_root_path() {
    local target=$1 canonical base
    [[ -n $target ]] || die 'build root must not be empty'
    [[ $target == /* ]] || die "build root must be an absolute path: $target"
    [[ ! -L $target ]] || die "build root must not be a symlink: $target"
    canonical=$(realpath -m -- "$target") || die "could not canonicalize build root: $target"
    [[ $canonical == /var/tmp/* ]] || die "build root must be under /var/tmp: $canonical"
    [[ $(dirname -- "$canonical") == /var/tmp ]] || die \
        "build root must be a dedicated direct child of /var/tmp: $canonical"
    base=$(basename -- "$canonical")
    [[ -n $base && $base != . && $base != .. ]] || die 'build root must name a dedicated directory'
}

validate_build_root_owner() {
    local target=$1 uid=$2 owner
    [[ -e $target ]] || return 0
    [[ ! -L $target ]] || die "build root must not be a symlink: $target"
    [[ -d $target ]] || die "build root exists but is not a directory: $target"
    owner=$(stat -c %u -- "$target")
    [[ $owner == "$uid" ]] || die \
        "existing build root $target is owned by uid $owner, not build user uid $uid"
}

missing_commands() {
    local command
    for command in "$@"; do
        command -v "$command" >/dev/null 2>&1 || printf '%s\n' "$command"
    done
}

require_commands() {
    local missing
    missing=$(missing_commands "$@")
    [[ -z $missing ]] || die "missing required command(s): $(tr '\n' ' ' <<<"$missing")"
}

report_plan() {
    log "Sargo camera native bootstrap"
    log "  arch:            $machine_arch"
    log "  root fstype:     $(detect_root_fstype)"
    log "  liveboot run id: $(cmdline_value pocketfed.liveboot)"
    log "  expected run id: ${expect_run_id:-<none>}"
    log "  build root:      $build_root"
    log "  build user:      ${build_user:-<unset>}"
    log "  jobs:            ${BUILD_JOBS} (fixed by packages/megapixels/build-native)"
    log "  packages:        ${PACKAGE_ORDER[*]}"
    log "  dnf build deps:  ${BUILD_PACKAGES[*]}"
    log "  dnf runtime:     ${RUNTIME_PACKAGES[*]}"
    log "  dnf camera:      ${CAMERA_PACKAGES[*]}"
    log "  helper:          packages/megapixels/build-native (pinned clones, 2 jobs)"
}

check_missing_tools() {
    local missing
    missing=$(missing_commands dnf rpm rpmbuild rpmspec git gzip python3 findmnt \
        runuser meson realpath)
    [[ -z $missing ]] || warn "commands not present yet (dnf phase installs some): $(tr '\n' ' ' <<<"$missing")"
}

require_root() {
    [[ $(id -u) -eq 0 ]] || die 'run as root (for example via sudo) so the dnf phase can install packages'
}

require_build_user() {
    local uid
    [[ -n $build_user ]] || die \
        'no unprivileged build user: pass --build-user or run via sudo (SUDO_USER is used)'
    uid=$(id -u "$build_user" 2>/dev/null) || die "unknown build user '$build_user'"
    [[ $uid -ne 0 ]] || die "build user '$build_user' resolves to uid 0; refusing to build as root"
}

prepare_build_root() {
    mkdir -p "$build_root/logs"
    chown -R "$build_user" "$build_root"
}

install_system_packages() {
    log "== dnf phase: installing build, runtime and camera packages =="
    dnf install -y --setopt=install_weak_deps=False \
        "${BUILD_PACKAGES[@]}" "${RUNTIME_PACKAGES[@]}" "${CAMERA_PACKAGES[@]}" \
        2>&1 | tee "$build_root/logs/dnf-install.log"
}

run_as_build_user() {
    runuser -u "$build_user" -- "$@"
}

build_native_helper() {
    local repo_root=$1
    local helper="$repo_root/packages/megapixels/build-native"
    [[ -x $helper ]] || die "missing build helper: $helper"
    printf '%s\n' "$helper"
}

parse_helper_outputs() {
    local helper=$1
    helper_topdir_template=$(sed -n 's/.*--define "_topdir \(.*\)".*/\1/p' "$helper")
    helper_dist=$(sed -n "s/.*--define 'dist \(.*\)'.*/\1/p" "$helper")
    [[ -n $helper_topdir_template && -n $helper_dist ]] || die \
        "cannot read the build output path or dist define from $helper"
}

resolve_expected_rpms() {
    local spec=$1 rpm_dir=$2 dist=$3 arch=$4 line name version release
    while IFS= read -r line; do
        [[ -n $line ]] || continue
        read -r name version release <<<"$line"
        case $name in *-debuginfo|*-debugsource) continue ;; esac
        printf '%s/%s-%s-%s.%s.rpm\n' "$rpm_dir" "$name" "$version" "$release" "$arch"
    done < <(rpmspec -q --qf '%{NAME} %{VERSION} %{RELEASE}\n' --define "dist $dist" "$spec")
}

collect_rpms() {
    local spec=$1 rpm_dir=$2 dist=$3 arch=$4 path missing=0
    while IFS= read -r path; do
        [[ -n $path ]] || continue
        if [[ -f $path ]]; then
            printf '%s\n' "$path"
        else
            warn "expected build output missing: $path"
            missing=1
        fi
    done < <(resolve_expected_rpms "$spec" "$rpm_dir" "$dist" "$arch")
    (( missing == 0 )) || return 1
}

build_and_install() {
    local repo_root=$1
    local helper spec rpm_dir output package
    local -a rpms
    helper=$(build_native_helper "$repo_root")
    parse_helper_outputs "$helper"
    [[ $helper_topdir_template == '$build_root/rpmbuild' ]] || die \
        "unexpected build output path in $helper: $helper_topdir_template"
    rpm_dir="$build_root/rpmbuild/RPMS/$machine_arch"
    for package in "${PACKAGE_ORDER[@]}"; do
        log "== build phase: $package (as $build_user, ${BUILD_JOBS} job(s)) =="
        run_as_build_user "$helper" "$build_root" "$package" \
            2>&1 | tee "$build_root/logs/build-$package.log"
        spec="$repo_root/packages/$package/$package.spec"
        if ! output=$(collect_rpms "$spec" "$rpm_dir" "$helper_dist" "$machine_arch"); then
            die "missing expected build output for $package; refusing to install a stale set"
        fi
        [[ -n $output ]] || die "no RPMs resolved for $package"
        mapfile -t rpms <<<"$output"
        log "== install phase: ${rpms[*]} =="
        dnf install -y "${rpms[@]}" 2>&1 | tee "$build_root/logs/install-$package.log"
    done
}

verify_install() {
    local libcamera_version
    log "== verify installed packages =="
    if ! rpm -q libdng libmegapixels megapixels; then
        die 'verification failed: a built package is not installed'
    fi
    libcamera_version=$(rpm -q --queryformat '%{VERSION}' libcamera 2>/dev/null || true)
    log "libcamera version: ${libcamera_version:-unknown}"
    [[ $libcamera_version == 0.7* ]] || warn \
        "expected a libcamera 0.7.x toolchain; review the installed version"
}

main() {
    local repo_root build_uid
    parse_args "$@"
    if (( test_overrides )) && (( ! check_mode )); then
        die '--machine-arch/--cmdline-file/--root-fstype/--result-file are only allowed with --check'
    fi
    validate_arch
    validate_liveboot_identity
    validate_build_root_path "$build_root"
    if [[ -n $build_user ]]; then
        build_uid=$(id -u "$build_user" 2>/dev/null) || die "unknown build user '$build_user'"
        if [[ -e $build_root ]]; then
            validate_build_root_owner "$build_root" "$build_uid"
        fi
    fi
    report_plan
    if (( check_mode )); then
        check_missing_tools
        log "dry run complete; no changes were made"
        return 0
    fi
    require_root
    require_build_user
    require_commands dnf rpm findmnt id python3 runuser tee realpath
    prepare_build_root
    install_system_packages
    require_commands rpmbuild rpmspec git gzip python3 meson cc
    repo_root=$(CDPATH='' cd -- "$(dirname -- "$0")/../../../.." && pwd)
    build_and_install "$repo_root"
    verify_install
    log "bootstrap complete; no frame capture or system transition was performed"
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
    main "$@"
fi
