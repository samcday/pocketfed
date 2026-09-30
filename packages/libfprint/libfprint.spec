%global commit 430e24e538ba137b6edcfe2e1b3b8cc29c66fa6a

Name:           libfprint
Version:        1.94.100
Release:        1.6.pocketfed%{?dist}
Summary:        Toolkit for fingerprint readers, including native Sargo FPC QSEE
License:        LGPL-2.1-or-later AND NIST-PD AND (GPL-2.0-only WITH Linux-syscall-note)
URL:            https://fprint.freedesktop.org/
Source0:        https://github.com/wrobelda/libfprint/archive/%{commit}/libfprint-%{commit}.tar.gz
Source1:        90-fpc-qsee.conf
Patch0:         0001-fpcqsee-native-sargo-driver.patch
Patch1:         0002-goodixqsee-include-protocol-header.patch
Patch2:         0003-fpcqsee-handle-empty-database-identification.patch
Patch3:         0004-fpcqsee-complete-identification-state.patch

BuildRequires:  meson
BuildRequires:  gcc
BuildRequires:  gcc-c++
BuildRequires:  openssl-devel
BuildRequires:  pkgconfig(glib-2.0) >= 2.68
BuildRequires:  pkgconfig(gio-2.0)
BuildRequires:  pkgconfig(gio-unix-2.0)
BuildRequires:  pkgconfig(gusb) >= 0.3.0
BuildRequires:  pkgconfig(pixman-1)
BuildRequires:  libgudev-devel
BuildRequires:  systemd
BuildRequires:  systemd-rpm-macros
BuildRequires:  gobject-introspection-devel
BuildRequires:  python3-cairo
BuildRequires:  python3-gobject
BuildRequires:  cairo-devel
BuildRequires:  umockdev >= 0.13.2

%description
libfprint provides consumer fingerprint reader support. This build adds an
experimental native Pixel 3a FPC QSEE driver to the public upstream driver tree.
It contains no proprietary firmware, credentials, keys or biometric templates.

%package devel
Summary:        Development files for libfprint
Requires:       %{name}%{?_isa} = %{version}-%{release}
%description devel
Headers, libraries and introspection data for developing with libfprint.

%package tests
Summary:        Installed tests for libfprint
Requires:       %{name}%{?_isa} = %{version}-%{release}
%description tests
Tests and public test fixtures for libfprint.

%package fpc-qsee
Summary:        Pixel 3a FPC QSEE integration for fprintd
Requires:       %{name}%{?_isa} = %{version}-%{release}
Requires:       fprintd
Requires:       qsee-supplicant >= 0.1.1
Requires:       pocketfed-fpc-auth >= 0.1.0-0.4.pocketfed
%{?systemd_requires}
%description fpc-qsee
Optional Pixel 3a service configuration for the native FPC QSEE driver. It
requires the matching kernel, device-local stock firmware preparation and
ordered common-library/application loader units. Enrollment additionally
requires a genuine Gatekeeper authorization broker. No database is initialized
or replaced automatically, and installation does not start a trusted app.

%prep
%autosetup -n libfprint-%{commit} -p1

%build
# Preserve the distribution's regular drivers and virtual integration drivers.
# systemd owns the autosuspend hwdb on the supported Fedora versions.
%meson -Ddrivers=all -Ddoc=false -Dudev_hwdb=disabled
%meson_build

%install
%meson_install
install -Dpm0644 %{SOURCE1} %{buildroot}%{_unitdir}/fprintd.service.d/90-fpc-qsee.conf
install -d -m0700 %{buildroot}%{_localstatedir}/lib/fprint/fpc-qsee

%check
# Hardware-free core and FPC boundary tests. Hardware replay suites need their
# separate device fixtures; they are not evidence of live Sargo functionality.
%meson_test --suite unit-tests --suite fpcqsee

%post fpc-qsee
%systemd_post fprintd.service

%postun fpc-qsee
%systemd_postun fprintd.service

%files
%license COPYING
%doc NEWS THANKS AUTHORS README.md
%{_libdir}/*.so.*
%{_libdir}/girepository-1.0/*.typelib
%{_udevrulesdir}/70-libfprint-2.rules
%{_datadir}/metainfo/org.freedesktop.libfprint.metainfo.xml

%files devel
%doc HACKING.md
%{_includedir}/*
%{_libdir}/*.so
%{_libdir}/pkgconfig/libfprint-2.pc
%{_datadir}/gir-1.0/*.gir

%files tests
%{_libexecdir}/installed-tests/libfprint-2/
%{_datadir}/installed-tests/libfprint-2/

%files fpc-qsee
%doc libfprint/drivers/fpcqsee/README.md
%{_unitdir}/fprintd.service.d/90-fpc-qsee.conf
%attr(0700,root,root) %dir %{_localstatedir}/lib/fprint/fpc-qsee

%changelog
* Sat Sep 12 2026 PocketFed contributors - 1.94.100-1.6.pocketfed
- Complete firmware identification state before accepting a match or nonmatch.
- Reject finalization failures and keep adaptive changes out of persisted records.

* Sat Sep 12 2026 PocketFed contributors - 1.94.100-1.5.pocketfed
- Handle a verified empty device database before attempting identification.
- Report recognized out-of-gallery prints for fprintd duplicate enrollment checks.
- Require the corrected fingerprint recipient ordering during Keymaster startup.
- Drop the obsolete NSS build dependency; this source tree uses OpenSSL.

* Fri Sep 11 2026 PocketFed contributors - 1.94.100-1.4.pocketfed
- Require Keymaster per-boot HMAC readiness before opening the FPC sensor.

* Fri Sep 11 2026 PocketFed contributors - 1.94.100-1.3.pocketfed
- Bind isolated driver test boundaries explicitly so Fedora LTO cannot bypass mocks.
- Preserve production compiler optimization and trusted device paths unchanged.

* Fri Sep 11 2026 PocketFed contributors - 1.94.100-1.2.pocketfed
- Include the upstream Goodix transport's existing protocol declaration.
- Leave autosuspend hwdb ownership to systemd and remove its stale file entry.

* Fri Sep 11 2026 PocketFed contributors - 1.94.100-1.1.pocketfed
- Add source-only native Sargo FPC QSEE protocol and libfprint integration.
- Require root-peer enrollment authorization and caller-bound actual matches.
- Add isolated transport/broker, capture-order and failure-path tests.
- Keep device service access in an optional Sargo integration subpackage.
