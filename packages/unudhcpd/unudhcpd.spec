Name:           unudhcpd
Version:        0.5.0
Release:        %autorelease
Summary:        Minimal DHCP server that leases one address to one USB peer

License:        GPL-3.0-or-later
URL:            https://gitlab.postmarketos.org/postmarketOS/unudhcpd
Source:         %{url}/-/archive/%{version}/%{name}-%{version}.tar.gz

BuildRequires:  gcc
BuildRequires:  meson
BuildRequires:  systemd-rpm-macros

%description
unudhcpd is a very small DHCP server that answers every DHCPDISCOVER and
DHCPREQUEST on one interface with the same client address. It suits
point-to-point links such as USB networking gadgets, where exactly one peer is
present but its MAC address may change. It advertises no router and no DNS
server.

%prep
%autosetup -p1

%build
%meson
%meson_build

%install
%meson_install
# OpenRC service script
rm %{buildroot}%{_sysconfdir}/init.d/unudhcpd

%check
%meson_test

%post
%systemd_post unudhcpd@.service

%preun
%systemd_preun 'unudhcpd@*.service'

%postun
%systemd_postun_with_restart 'unudhcpd@*.service'

%files
%license LICENSE
%doc README.md
%{_bindir}/unudhcpd
%{_unitdir}/unudhcpd@.service

%changelog
%autochangelog
