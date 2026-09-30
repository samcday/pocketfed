%global commit 36e06680cf7f690fccbdcd07abc2a64c4bb061d8

Name:           qsee-supplicant
Version:        0.1.1
Release:        1.4.pocketfed%{?dist}
Summary:        Userspace services for Qualcomm QSEECOM trusted applications
License:        BSD-2-Clause AND BSD-3-Clause-Clear
URL:            https://github.com/wrobelda/qsee-supplicant
Source0:        %{url}/archive/%{commit}/%{name}-%{commit}.tar.gz
Source1:        sargo-rpmb.tar
Patch0:         0001-loader-shared-libraries.patch
Patch1:         0002-listener-readiness-lifetime.patch

BuildRequires:  gcc
BuildRequires:  make
BuildRequires:  kernel-headers
BuildRequires:  systemd-rpm-macros
%{?systemd_requires}

%description
A machine-wide listener supplicant and per-application loader for trusted
applications using Qualcomm's legacy QSEECOM interface through the Linux TEE
subsystem. This package requires a kernel with the QSEECOM TEE backend. It
contains no proprietary firmware and does not select a trusted application.

%package sargo-rpmb
Summary:        Optional Sargo FS, GPFS and authenticated RPMB listener
License:        BSD-2-Clause AND BSD-3-Clause-Clear AND MIT
Requires:       %{name} = %{version}-%{release}

%description sargo-rpmb
Explicitly activated Sargo listener with named-device validation, bounded
authenticated-frame forwarding and write-failure latching. This subpackage
does not activate its service template, program RPMB keys, or provision users.

%prep
%autosetup -n %{name}-%{commit} -p1
tar -xf %{SOURCE1}
# Fedora's merged sbin places these programs in /usr/bin.
sed -i 's|/usr/sbin/|%{_sbindir}/|g' packaging/*.service

%build
%set_build_flags
%make_build
%make_build -C sargo-rpmb QSEE=.. all

%install
%{__make} DESTDIR=%{buildroot} PREFIX=%{_prefix} SBINDIR=%{_sbindir} \
    UNITDIR=%{_unitdir} DOCDIR=%{_docdir}/%{name} \
    install-bin install-systemd install-doc
install -m 0755 sargo-rpmb/build/qsee-sargo-rpmb %{buildroot}%{_sbindir}/qsee-sargo-rpmb
install -d %{buildroot}%{_docdir}/%{name}-sargo-rpmb
install -m 0644 sargo-rpmb/README.md sargo-rpmb/90-sargo-rpmb.conf \
    sargo-rpmb/source-origin.json sargo-rpmb/sources.json \
    %{buildroot}%{_docdir}/%{name}-sargo-rpmb/

%check
%set_build_flags
%make_build check
%make_build -C sargo-rpmb QSEE=.. check

%post
%systemd_post qsee-supplicant.service qsee-app-loader@.service qsee-shared-loader@.service

%preun
%systemd_preun qsee-supplicant.service qsee-app-loader@.service qsee-shared-loader@.service

%postun
%systemd_postun_with_restart qsee-supplicant.service qsee-app-loader@.service qsee-shared-loader@.service

%files
%license LICENSE LICENSES/BSD-3-Clause-Clear.txt
%{_sbindir}/qsee-supplicant
%{_sbindir}/qsee-app-loader
%{_unitdir}/qsee-supplicant.service
%{_unitdir}/qsee-app-loader@.service
%{_unitdir}/qsee-shared-loader@.service
%{_docdir}/%{name}/README.md

%files sargo-rpmb
%license LICENSE LICENSES/BSD-3-Clause-Clear.txt sargo-rpmb/LICENSE.MIT
%{_sbindir}/qsee-sargo-rpmb
%{_docdir}/%{name}-sargo-rpmb/

%changelog
* Sat Sep 12 2026 PocketFed contributors - 0.1.1-1.4.pocketfed
- Package the optional Sargo combined RPMB listener without activating it.
- Preserve tested framing/device checks and refuse writes after device or transport failure.

* Fri Sep 11 2026 PocketFed contributors - 0.1.1-1.3.pocketfed
- Exit on post-readiness transport loss so systemd withdraws stale readiness.
- Reject failed TEE listener registrations before announcing readiness.
- Cover initialization, shutdown and registration failures with offline tests.

* Fri Sep 11 2026 PocketFed contributors - 0.1.1-1.2.pocketfed
- Add explicit common-library loading, check TEE errors and avoid a stop race.
- Test normal and shared-loader request layouts and failure cleanup.
