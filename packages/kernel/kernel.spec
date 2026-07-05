%undefine _debugsource_packages
%global debug_package %{nil}

%global commit 8f62f796de277aefff54af1191907927799431fb
%global shortcommit %(echo %{commit} | cut -c1-12)
%global profile pocketfed-configs/profiles/fedora.list

Name:           kernel
Version:        7.2~rc1
Release:        %autorelease
Summary:        PocketFed Linux kernel
License:        GPL-2.0-only
URL:            https://github.com/samcday/linux
Source0:        %{url}/archive/%{commit}/linux-%{shortcommit}.tar.gz

ExclusiveArch:  aarch64

BuildRequires:  bash
BuildRequires:  bc
BuildRequires:  bison
BuildRequires:  diffutils
BuildRequires:  elfutils-libelf-devel
BuildRequires:  findutils
BuildRequires:  flex
BuildRequires:  gcc
BuildRequires:  hostname
BuildRequires:  kmod
BuildRequires:  make
BuildRequires:  openssl
BuildRequires:  openssl-devel
BuildRequires:  perl-interpreter
BuildRequires:  python3
BuildRequires:  rsync
BuildRequires:  tar
BuildRequires:  xz
BuildRequires:  zstd

%global uname_r %{version}-%{release}.%{_target_cpu}
%global make_kernel ARCH=arm64 EXTRAVERSION= LOCALVERSION=-%{release}.%{_target_cpu}

Provides:       kernel = %{version}-%{release}
Provides:       kernel-core = %{version}-%{release}
Provides:       kernel-devel = %{version}-%{release}
Provides:       kernel-headers = %{version}-%{release}
Provides:       kernel-modules = %{version}-%{release}
Provides:       kernel-modules-core = %{version}-%{release}
Provides:       kernel-uname-r = %{uname_r}

%description
Linux kernel built from the PocketFed branch for supported PocketFed devices.

%prep
%autosetup -n linux-%{commit}

%build
mkdir -p build
cat >build/kconfig-rpm.conf <<'EOF'
CONFIG_LOCALVERSION=""
# CONFIG_LOCALVERSION_AUTO is not set
EOF

config_root="$(dirname "%{profile}")/.."
fragments=
while IFS= read -r fragment; do
  case "$fragment" in
    ''|'#'*) continue ;;
    /*) path="$fragment" ;;
    *) path="$config_root/$fragment" ;;
  esac
  if [ ! -f "$path" ]; then
    printf 'missing kernel config fragment: %s\n' "$fragment" >&2
    exit 1
  fi
  fragments="$fragments $path"
done < "%{profile}"

ARCH=arm64 scripts/kconfig/merge_config.sh -n -r -O build /dev/null \
  $fragments build/kconfig-rpm.conf

%make_build O=build %{make_kernel} olddefconfig
%make_build O=build %{make_kernel} Image modules dtbs

%install
%make_build O=build %{make_kernel} \
  INSTALL_MOD_PATH=%{buildroot}%{_prefix} \
  INSTALL_HDR_PATH=%{buildroot}%{_prefix} \
  INSTALL_MOD_STRIP=1 \
  DEPMOD=true \
  modules_install headers_install

dtb_src=build/arch/arm64/boot/dts
dtb_dst=%{buildroot}%{_prefix}/lib/modules/%{uname_r}/dtb
mkdir -p "$dtb_dst"
rsync -a --chmod=D755,F644 \
  --include='*/' --include='*.dtb' --exclude='*' \
  "$dtb_src/" "$dtb_dst/"

install -Dm644 build/arch/arm64/boot/Image \
  %{buildroot}%{_prefix}/lib/modules/%{uname_r}/vmlinuz
install -Dm644 build/System.map \
  %{buildroot}%{_prefix}/lib/modules/%{uname_r}/System.map
install -Dm644 build/.config \
  %{buildroot}%{_prefix}/lib/modules/%{uname_r}/config

depmod -b %{buildroot}%{_prefix} %{uname_r}

%files
%license COPYING
%{_includedir}
%{_prefix}/lib/modules/%{uname_r}

%changelog
%autochangelog
