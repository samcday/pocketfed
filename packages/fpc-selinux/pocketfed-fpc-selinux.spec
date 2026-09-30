Name:           pocketfed-fpc-selinux
Version:        0.1.0
Release:        0.2.pocketfed%{?dist}
Summary:        Offline policy module for the native Sargo fingerprint trial
License:        MIT
URL:            https://github.com/samcday/pocketfed
BuildArch:      noarch
Source0:        pocketfed_fpc.te
Source1:        pocketfed_fpc.fc
Source2:        Makefile
Source3:        README.package.md
Source4:        COPYING
Source5:        pocketfed_fpc_broker.te
Source6:        pocketfed_fpc_broker.fc
Source7:        README.broker.md

BuildRequires:  make
BuildRequires:  checkpolicy
BuildRequires:  policycoreutils
Requires:       selinux-policy-targeted >= 45.15-2

%description
Compiled SELinux modules for native FPC/QSEE device access and a dedicated
confined enrollment broker, with a separate private credential state label.
This package only supplies policy data. It does not register or load the module,
relabel files, enable services, create credentials or change authentication.
The trial image must integrate it with a verified complete distribution store.

%prep
%setup -q -c -T
cp %{SOURCE0} %{SOURCE1} %{SOURCE2} %{SOURCE3} %{SOURCE4} .
mkdir broker
cp %{SOURCE5} %{SOURCE6} broker/
cp %{SOURCE7} README.broker.md

%build
%make_build

%install
install -Dm0644 build/pocketfed_fpc.pp %{buildroot}%{_datadir}/selinux/packages/targeted/pocketfed_fpc.pp
install -Dm0644 build/pocketfed_fpc_broker.pp %{buildroot}%{_datadir}/selinux/packages/targeted/pocketfed_fpc_broker.pp

%files
%license COPYING
%doc README.package.md README.broker.md
%{_datadir}/selinux/packages/targeted/pocketfed_fpc.pp
%{_datadir}/selinux/packages/targeted/pocketfed_fpc_broker.pp

%changelog
* Sat Sep 12 2026 PocketFed contributors - 0.1.0-0.2.pocketfed
- Add an inactive supplementary module for a confined enrollment broker peer.
- Keep generic unconfined-service connections and fprintd credential reads denied.

* Fri Sep 11 2026 PocketFed contributors - 0.1.0-0.1.pocketfed
- Package the device and broker object-label policy as inactive data.
