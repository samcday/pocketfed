Name:           phosh-fingerprint-auth
Version:        0.1.0
Release:        0.1.pocketfed%{?dist}
Summary:        Isolated fingerprint PAM transaction helper for Phosh
License:        GPL-3.0-or-later
URL:            https://github.com/samcday/pocketfed
Source0:        phosh-fingerprint-auth.c
Source1:        phosh-fingerprint.pam
Source2:        Makefile
Source3:        test-helper.c
Source4:        fingerprint-auth.c
Source5:        fingerprint-auth.h
Source6:        test-client.c
Source7:        fake-helper.c
Source8:        COPYING
Source9:        README.md
Source10:       phosh-fingerprint-worker.c
Source11:       fingerprint-wire.h
Source12:       phosh-fingerprint-auth.socket
Source13:       phosh-fingerprint-auth@.service

BuildRequires:  gcc
BuildRequires:  make
BuildRequires:  pam-devel
BuildRequires:  pkgconfig(gio-2.0)
BuildRequires:  systemd-rpm-macros
Requires:       fprintd-pam
Requires:       systemd-pam
Requires:       systemd

%description
A socket client and privileged, peer-UID-bound worker for a separate,
cancellable fingerprint PAM transaction in Phosh. Authentication and account
management must both succeed. The worker cannot accept passwords, select
another account, or switch services.
The matching Phosh source integration must be built separately. Installation
does not modify the existing PIN service, greetd configuration, or authselect.

%prep
%setup -q -c -T
cp %{SOURCE0} %{SOURCE1} %{SOURCE2} %{SOURCE3} %{SOURCE4} %{SOURCE5} %{SOURCE6} %{SOURCE7} %{SOURCE8} %{SOURCE9} %{SOURCE10} %{SOURCE11} %{SOURCE12} %{SOURCE13} .

%build
%make_build CFLAGS="%{build_cflags}"

%check
%make_build check CFLAGS="%{build_cflags}"

%install
install -Dm0755 build/phosh-fingerprint-auth %{buildroot}%{_libexecdir}/phosh-fingerprint-auth
install -Dm0755 build/phosh-fingerprint-worker %{buildroot}%{_libexecdir}/phosh-fingerprint-worker
install -Dm0644 phosh-fingerprint.pam %{buildroot}%{_prefix}/lib/pam.d/phosh-fingerprint
install -Dm0644 phosh-fingerprint-auth.socket %{buildroot}%{_unitdir}/phosh-fingerprint-auth.socket
install -Dm0644 phosh-fingerprint-auth@.service %{buildroot}%{_unitdir}/phosh-fingerprint-auth@.service

%files
%license COPYING
%doc README.md
%{_libexecdir}/phosh-fingerprint-auth
%{_libexecdir}/phosh-fingerprint-worker
%{_prefix}/lib/pam.d/phosh-fingerprint
%{_unitdir}/phosh-fingerprint-auth.socket
%{_unitdir}/phosh-fingerprint-auth@.service

%changelog
* Fri Sep 11 2026 PocketFed contributors - 0.1.0-0.1.pocketfed
- Prepare isolated fingerprint authentication while preserving the PIN path
