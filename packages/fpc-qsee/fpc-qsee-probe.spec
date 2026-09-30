Name:           fpc-qsee-probe
Version:        0.1.0
Release:        0.1.pocketfed%{?dist}
Summary:        Explicit diagnostic for the native Sargo fingerprint transport
License:        LGPL-2.1-or-later AND (GPL-2.0-only WITH Linux-syscall-note)
URL:            https://github.com/samcday/pocketfed
Source0:        %{name}-%{version}.tar.gz
BuildRequires:  gcc
BuildRequires:  make
BuildRequires:  kernel-headers
Requires:       qsee-supplicant >= 0.1.1

%description
An explicit initialization or capture-readiness diagnostic for the Pixel 3a
FPC trusted application and native sensor-control device. It does not enroll,
identify or return biometric templates. The application must already be loaded
through the separately controlled QSEECOM loader. No service is installed or
started by this package, and no proprietary firmware is included.

%prep
%autosetup

%build
%set_build_flags
%make_build

%check
%set_build_flags
%make_build check

%install
install -Dpm0755 fpc-qsee-probe %{buildroot}%{_bindir}/fpc-qsee-probe

%files
%license COPYING
%doc README.md protocol.md gatekeeper.md
%{_bindir}/fpc-qsee-probe

%changelog
* Fri Sep 11 2026 PocketFed contributors - 0.1.0-0.1.pocketfed
- Package the explicit Sargo FPC initialization and capture diagnostic.
- Check recovered protocol, TEE transport, sensor and Gatekeeper boundaries.
