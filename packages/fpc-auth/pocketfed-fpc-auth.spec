Name:           pocketfed-fpc-auth
Version:        0.1.0
Release:        0.4.pocketfed%{?dist}
Summary:        Root broker for native fingerprint enrollment tokens
License:        LGPL-2.1-or-later
URL:            https://github.com/samcday/pocketfed
Source0:        auth-broker.c
Source1:        auth-store.c
Source2:        auth-store.h
Source3:        test-auth-store.c
Source4:        Makefile
Source5:        auth-broker.h
Source6:        gatekeeper-protocol.c
Source7:        gatekeeper-protocol.h
Source8:        pocketfed-fpc-auth.socket
Source9:        pocketfed-fpc-auth.service
Source10:       COPYING
Source11:       README.md
Source12:       auth-backend.c
Source13:       auth-backend.h
Source14:       test-auth-backend.c
Source15:       qsee-transport.c
Source16:       qsee-transport.h
Source17:       pocketfed-fpc-provision@.service
Source18:       keymaster-startup.c
Source19:       test-keymaster-startup.c
Source20:       protocol.c
Source21:       protocol.h
Source22:       pocketfed-keymaster-startup.service

BuildRequires:  gcc
BuildRequires:  make
BuildRequires:  systemd-rpm-macros
BuildRequires:  kernel-headers
Requires:       qsee-supplicant >= 0.1.1-1.3.pocketfed
Requires:       kernel-core >= 7.1.2-0.pocketfed.sdm670.11
Requires:       /usr/bin/flock
%{?systemd_requires}

%description
A root-only enrollment token socket service and explicit provisioning command
for Linux-owned Sargo fingerprint credentials. Durable exclusive state prevents
automatic replacement after interrupted provisioning. The backend attaches to
resident keymaster64 and uses the verified Sargo version and Gatekeeper formats.
The listener service and a kernel with sensitive-buffer clearing are required.
This package contains no firmware and does not enable its static socket or
provisioning unit, create credentials, or change authentication configuration.
The static startup service validates the Keymaster handshake and establishes
the per-boot HMAC agreement only when the TA reports it uninitialized.

%prep
%setup -q -c -T
cp %{SOURCE0} %{SOURCE1} %{SOURCE2} %{SOURCE3} %{SOURCE4} %{SOURCE5} %{SOURCE6} %{SOURCE7} %{SOURCE8} %{SOURCE9} %{SOURCE10} %{SOURCE11} %{SOURCE12} %{SOURCE13} %{SOURCE14} %{SOURCE15} %{SOURCE16} %{SOURCE17} .
cp %{SOURCE18} %{SOURCE19} %{SOURCE20} %{SOURCE21} %{SOURCE22} .

%build
%set_build_flags
%make_build FPC_QSEE_DIR=.

%check
%set_build_flags
%make_build check FPC_QSEE_DIR=.

%install
install -Dm0755 build/pocketfed-fpc-auth %{buildroot}%{_bindir}/pocketfed-fpc-auth
install -Dm0755 build/pocketfed-keymaster-startup %{buildroot}%{_bindir}/pocketfed-keymaster-startup
install -Dm0644 pocketfed-fpc-auth.socket %{buildroot}%{_unitdir}/pocketfed-fpc-auth.socket
install -Dm0644 pocketfed-fpc-auth.service %{buildroot}%{_unitdir}/pocketfed-fpc-auth.service
install -Dm0644 pocketfed-fpc-provision@.service %{buildroot}%{_unitdir}/pocketfed-fpc-provision@.service
install -Dm0644 pocketfed-keymaster-startup.service %{buildroot}%{_unitdir}/pocketfed-keymaster-startup.service

%post
%systemd_post pocketfed-fpc-auth.socket pocketfed-fpc-auth.service pocketfed-fpc-provision@.service pocketfed-keymaster-startup.service

%preun
%systemd_preun pocketfed-fpc-auth.socket pocketfed-fpc-auth.service pocketfed-fpc-provision@.service pocketfed-keymaster-startup.service

%postun
%systemd_postun pocketfed-fpc-auth.socket pocketfed-fpc-auth.service pocketfed-fpc-provision@.service pocketfed-keymaster-startup.service

%files
%license COPYING
%doc README.md
%{_bindir}/pocketfed-fpc-auth
%{_bindir}/pocketfed-keymaster-startup
%{_unitdir}/pocketfed-fpc-auth.socket
%{_unitdir}/pocketfed-fpc-auth.service
%{_unitdir}/pocketfed-fpc-provision@.service
%{_unitdir}/pocketfed-keymaster-startup.service

%changelog
* Fri Sep 11 2026 PocketFed contributors - 0.1.0-0.4.pocketfed
- Load the recipient fingerprint TA before requesting its wrapped auth key.
- Withdraw startup readiness when the fingerprint loader stops.

* Fri Sep 11 2026 PocketFed contributors - 0.1.0-0.3.pocketfed
- Prepare per-boot Keymaster HMAC agreement before token services.
- Preserve provisioning phase and transport/secure status in diagnostics.
- Test startup idempotence, cancellation and genuine uninitialized-state gating.

* Fri Sep 11 2026 PocketFed contributors - 0.1.0-0.2.pocketfed
- Wire the verified stock Keymaster handshake and genuine Gatekeeper operations.
- Bind broker and explicit provisioning to listener service readiness.
- Test exact TEE framing, shared-memory clearing and credential lifecycle.

* Fri Sep 11 2026 PocketFed contributors - 0.1.0-0.1.pocketfed
- Prepare root token broker and exclusive durable service-credential storage
- Keep the unverified Keymaster negotiation backend disabled
