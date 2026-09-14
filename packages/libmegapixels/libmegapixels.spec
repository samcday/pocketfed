Name:           libmegapixels
Version:        0.2.3
Release:        3%{?dist}
Summary:        Media controller camera configuration for Megapixels
License:        GPL-3.0-only
URL:            https://gitlab.com/megapixels-org/libmegapixels
# Tag resolves to d50bf166972df4252d127f72f90986892f3cd901.
Source0:        %{url}/-/archive/%{version}/%{name}-%{version}.tar.gz
Source1:        test-bayer-order.py
Source2:        bayer-order-fixture.c
Patch0:         0001-prefer-pixel-3a-rear-camera.patch
Patch1:         0002-match-sensor-bayer-order.patch
BuildRequires:  gcc
BuildRequires:  meson
BuildRequires:  python3
BuildRequires:  pkgconfig(libconfig)

%description
Libmegapixels configures camera sensors and their media controller pipelines,
providing device discovery, raw capture modes and lens actuator discovery.

%package devel
Summary:        Development files for libmegapixels
Requires:       %{name}%{?_isa} = %{version}-%{release}

%description devel
Headers and pkg-config metadata for developing applications using libmegapixels.

%package tools
Summary:        Camera configuration and raw capture utilities
Requires:       %{name}%{?_isa} = %{version}-%{release}

%description tools
Utilities to inspect and validate camera configuration and capture raw frames.

%prep
%autosetup -p1

%build
%meson
%meson_build

%install
%meson_install
# Current mainline device trees identify the Pixel 3a as google,sargo; the
# upstream configuration still uses Google's earlier b4s4-sdm670 compatible.
ln -s google,b4s4-sdm670.conf %{buildroot}%{_datadir}/megapixels/config/google,sargo.conf

%check
%meson_test
python3 %{SOURCE1} src/pipeline.c
LIBMEGAPIXELS_DEBUG=2 %{_vpath_builddir}/megapixels-configlint config/google,b4s4-sdm670.conf 2>sargo-configlint.log
test "$(awk -F"'" '/Loading camera/ { print $2; exit }' sargo-configlint.log)" = Rear
cmp config/google,b4s4-sdm670.conf %{buildroot}%{_datadir}/megapixels/config/google,sargo.conf

%files
%license LICENSE
%{_libdir}/libmegapixels.so.1*
%dir %{_datadir}/megapixels
%dir %{_datadir}/megapixels/config
%{_datadir}/megapixels/config/*.conf

%files devel
%{_includedir}/libmegapixels.h
%{_libdir}/libmegapixels.so
%{_libdir}/pkgconfig/libmegapixels.pc

%files tools
%{_bindir}/megapixels-findconfig
%{_bindir}/megapixels-getframe
%{_bindir}/megapixels-configlint
%{_bindir}/megapixels-sensorprofile

%changelog
* Thu Sep 10 2026 Sam Day <me@samcday.com> - 0.2.3-3
- Match sensor flip controls to the requested Bayer order before setting pad formats

* Thu Sep 10 2026 Sam Day <me@samcday.com> - 0.2.3-2
- Prefer the rear camera in Pixel 3a discovery order

* Thu Sep 10 2026 Sam Day <me@samcday.com> - 0.2.3-1
- Package upstream Pixel 3a support and its current device-tree alias
