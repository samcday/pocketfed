%global commit 35e272af38405ef1e138d89bce7acb5ac8e305fb
%global app_id eu.lucaweiss.lpa_gtk

Name:           lpa-gtk
Version:        0.4
Release:        1.2.pocketfed%{?dist}
Summary:        Download and manage eSIM profiles
License:        GPL-3.0-only AND CC-BY-SA-4.0 AND CC0-1.0
URL:            https://codeberg.org/lucaweiss/lpa-gtk
# Upstream tag 0.4, pinned to its peeled commit.
Source0:        %{url}/archive/%{commit}.tar.gz#/%{name}-%{commit}.tar.gz
Source1:        test-package.py
Source2:        sources.sha256
Source3:        README.pocketfed.md
BuildArch:      noarch

BuildRequires:  meson
BuildRequires:  blueprint-compiler
BuildRequires:  python3-devel >= 3.12
BuildRequires:  python3-gobject
BuildRequires:  pkgconfig(gtk4)
BuildRequires:  pkgconfig(libadwaita-1) >= 1.7
BuildRequires:  appstream
BuildRequires:  desktop-file-utils
BuildRequires:  dbus-daemon
BuildRequires:  xorg-x11-server-Xvfb

Requires:       python3 >= 3.12
Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita >= 1.7
# The tested PocketFed baseline includes QRTR cleanup/mapping fixes and
# authenticated HTTPS with client-scoped production GSMA trust.
Requires:       lpac >= 2.3.0-1.2.pocketfed

%description
eSIM Manager is a GTK4 and Libadwaita application for Linux phones using
Phosh or GNOME Mobile. It uses lpac to inspect, download and manage profiles
on built-in or removable eUICC cards. Activation codes can be pasted into
the application; camera-based QR scanning is not currently supported.

%prep
(cd "%{_sourcedir}" && sha256sum --check --status "%{SOURCE2}")
%autosetup -n %{name}

%build
%meson -Dpython.purelibdir=%{python3_sitelib}
%meson_build

%install
%meson_install

%check
%meson_test
desktop-file-validate %{buildroot}%{_datadir}/applications/%{app_id}.desktop
# Validate the staged Python/resources using upstream's dummy backend only.
# No lpac executable, modem, profile operation or carrier access is needed.
GSETTINGS_BACKEND=memory GDK_BACKEND=x11 GSK_RENDERER=cairo GTK_A11Y=none \
    LPA_GTK_BACKEND=dummy \
    dbus-run-session -- xvfb-run -a \
    %{__python3} %{SOURCE1} %{buildroot} %{python3_sitelib}

%files
%license LICENSES/*
%doc README.md REUSE.toml %{SOURCE3}
%{_bindir}/lpa-gtk
%{python3_sitelib}/lpa_gtk/
%{_datadir}/lpa-gtk/
%{_datadir}/applications/%{app_id}.desktop
%{_datadir}/metainfo/%{app_id}.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/%{app_id}.svg

%changelog
* Fri Sep 11 2026 PocketFed maintainers <me@samcday.com> - 0.4-1.2.pocketfed
- Normalize equivalent Meson install paths in the staged-launcher test

* Fri Sep 11 2026 PocketFed maintainers <me@samcday.com> - 0.4-1.1.pocketfed
- Package upstream eSIM Manager without application or device-policy patches
- Test installed resources and mobile UI with the offline dummy backend
