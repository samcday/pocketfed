Name:           q6voiced
Version:        0.3.1
Release:        %autorelease
Summary:        Userspace daemon for the QDSP6 voice call audio driver

License:        MIT
URL:            https://gitlab.postmarketos.org/postmarketOS/q6voiced
# Tag 0.3.1 resolves to upstream commit
# 21061751b80850e37de371d61a039cc2297999e0.
Source0:        %{url}/-/archive/%{version}/%{name}-%{version}.tar.gz
Source1:        test-fake-alsa.c
Source2:        test-route-readiness-retry
Patch0:         q6voiced-0.3.1-retry-voice-pcm-open.patch

BuildRequires:  gcc
BuildRequires:  dbus-daemon
BuildRequires:  meson >= 1.10.0
BuildRequires:  pkgconfig(alsa)
BuildRequires:  pkgconfig(dbus-1)
BuildRequires:  systemd
BuildRequires:  systemd-rpm-macros

%description
q6voiced listens for telephony call state changes from services such as
ModemManager and opens the QDSP6 voice PCM while a call is active. This starts
modem-routed call audio on Qualcomm platforms with a dedicated voice PCM.

%prep
%autosetup

%build
%meson \
    -Dopenrc=disabled \
    -Dsystemd=enabled
%meson_build

%install
%meson_install

%check
%meson_test
dbus-run-session -- sh -c '\
    export DBUS_SYSTEM_BUS_ADDRESS="$DBUS_SESSION_BUS_ADDRESS"; \
    exec sh "$1" "$2" "$3"\
' sh %{SOURCE2} %{SOURCE1} %{_vpath_builddir}/q6voiced

%post
%systemd_post q6voiced.service

%preun
%systemd_preun q6voiced.service

%postun
%systemd_postun_with_restart q6voiced.service

%files
%license LICENSE
%doc README.md
%{_bindir}/q6voiced
%{_unitdir}/q6voiced.service

%changelog
%autochangelog
