Name:           81voltd
Version:        1.2.0
Release:        %autorelease
Summary:        IMS data service for Qualcomm modems using QMI over QRTR

License:        GPL-2.0-or-later
URL:            https://gitlab.postmarketos.org/modem/81voltd
# The signed, annotated upstream v1.2.0 tag resolves to commit
# 7c0cd9442d71b55260c9917c89ebc4bd20e283a8.
Source0:        %{url}/-/archive/v%{version}/%{name}-v%{version}.tar.gz

BuildRequires:  gcc
BuildRequires:  meson
BuildRequires:  pkgconfig(mm-glib)
BuildRequires:  pkgconfig(qmi-glib)
BuildRequires:  pkgconfig(qrtr)
BuildRequires:  systemd-rpm-macros
Requires:       ModemManager
%{?systemd_requires}

%description
81voltd implements the IMS Data Service exposed by Qualcomm modem firmware over
QMI/QRTR. It creates and controls the modem-requested IMS bearer through the
ModemManager D-Bus API.

%prep
%autosetup -n %{name}-v%{version}

%build
%meson
%meson_build

%install
%meson_install
# Fedora does not use the OpenRC unit installed by upstream.
rm -f %{buildroot}%{_sysconfdir}/init.d/%{name}

%check
%meson_test
test -x %{buildroot}%{_bindir}/%{name}
grep -Fxq 'ExecStart=%{_bindir}/%{name}' \
    %{buildroot}%{_unitdir}/%{name}.service

%post
%systemd_post 81voltd.service

%preun
%systemd_preun 81voltd.service

%postun
%systemd_postun_with_restart 81voltd.service

%files
%license LICENSE
%doc README.md
%{_bindir}/%{name}
%{_mandir}/man1/%{name}.1*
%{_unitdir}/%{name}.service

%changelog
%autochangelog
