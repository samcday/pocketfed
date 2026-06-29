%undefine _debugsource_packages
%global debug_package %{nil}

%global commit 1e727c55e66d2cd89316acd6453241f1761e6b5c
%global shortcommit %(echo %{commit} | cut -c1-12)
%global profile pocketfed-configs/profiles/oneplus-fajita-fedora.list

Name:           kernel
Version:        7.2.0
Release:        0.rc1.1.g%{shortcommit}.pocketfed%{?dist}
Summary:        PocketFed Linux kernel
License:        GPL-2.0-only
URL:            https://github.com/samcday/linux
Source0:        %{url}/archive/%{commit}/linux-%{shortcommit}.tar.gz

ExclusiveArch:  aarch64

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

Requires(posttrans): dracut
Requires(posttrans): kmod
Requires(posttrans): systemd-udev
Requires(postun):     systemd-udev

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
Linux kernel built from the PocketFed branch for OnePlus 6T/fajita.

%prep
%autosetup -n linux-%{commit}

%build
mkdir -p build
printf 'CONFIG_LOCALVERSION=""\n# CONFIG_LOCALVERSION_AUTO is not set\n' > build/kconfig-local.conf
ARCH=arm64 scripts/kconfig/merge_config.sh -n -r -O build /dev/null \
  $(grep -vE '^[[:space:]]*($|#)' %{profile}) \
  build/kconfig-local.conf

%make_build O=build %{make_kernel} olddefconfig
%make_build O=build %{make_kernel} Image modules dtbs

%install
%make_build O=build %{make_kernel} \
  INSTALL_MOD_PATH=%{buildroot}%{_prefix} \
  INSTALL_HDR_PATH=%{buildroot}%{_prefix} \
  INSTALL_MOD_STRIP=1 \
  DEPMOD=true \
  modules_install headers_install

install -Dm644 build/arch/arm64/boot/dts/qcom/sdm845-oneplus-enchilada.dtb \
  %{buildroot}%{_prefix}/lib/modules/%{uname_r}/dtb/qcom/sdm845-oneplus-enchilada.dtb
install -Dm644 build/arch/arm64/boot/dts/qcom/sdm845-oneplus-fajita.dtb \
  %{buildroot}%{_prefix}/lib/modules/%{uname_r}/dtb/qcom/sdm845-oneplus-fajita.dtb
install -Dm644 build/arch/arm64/boot/Image \
  %{buildroot}%{_prefix}/lib/modules/%{uname_r}/vmlinuz
install -Dm644 build/System.map \
  %{buildroot}%{_prefix}/lib/modules/%{uname_r}/System.map
install -Dm644 build/.config \
  %{buildroot}%{_prefix}/lib/modules/%{uname_r}/config

%files
%license COPYING
%{_includedir}
%{_prefix}/lib/modules/%{uname_r}

%posttrans
set -e
depmod -a %{uname_r}
dracut --force %{_prefix}/lib/modules/%{uname_r}/initramfs.img %{uname_r}
kernel-install add %{uname_r} %{_prefix}/lib/modules/%{uname_r}/vmlinuz %{_prefix}/lib/modules/%{uname_r}/initramfs.img

%postun
if [ "$1" -eq 0 ]; then
  kernel-install remove %{uname_r}
fi

%changelog
* Mon Jun 29 2026 Sam Day <samcday@users.noreply.github.com> - 7.2.0-0.rc1.1.g1e727c55e66d.pocketfed
- Build PocketFed kernel from samcday/linux pocketfed/main.
