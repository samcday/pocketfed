Name:     stevia
Version:  0.57.0
Release:  1.3.pocketfed%{?dist}
Summary:  On screen keyboard (OSK) Phosh
License:  GPL-3.0-or-later
URL:      https://gitlab.gnome.org/World/Phosh/stevia
Source:   %{url}/-/archive/v%{version_no_tilde _}/%{name}-v%{version_no_tilde _}.tar.gz

Patch0:   stevia-0.57.0-verbisage-completer.patch
Patch1:   stevia-0.57.0-ranked-completion.patch
Patch2:   stevia-0.57.0-swipe-and-undo.patch

Provides: stevia-completer-verbisage = 1
Provides: stevia-completer-verbisage-ranked = 1
Provides: stevia-swipe-typing = 1
Provides: stevia-completion-undo = 1

ExcludeArch:  %{ix86}
# Tests fail on s390x. Nobody's asking to run an OSK on their mainframe.
ExcludeArch:  s390x

BuildRequires:  dbus-daemon
BuildRequires:  gcc
BuildRequires:  meson
BuildRequires:  pkgconfig(glib-2.0) >= 2.80
BuildRequires:  pkgconfig(gio-2.0) >= 2.80
BuildRequires:  pkgconfig(gobject-2.0) >= 2.80
BuildRequires:  pkgconfig(gmobile) >= 0.2.0
BuildRequires:  pkgconfig(gnome-desktop-3.0) >= 3.26
BuildRequires:  pkgconfig(gsettings-desktop-schemas) >= 47
BuildRequires:  pkgconfig(gtk+-3.0) >= 3.22
BuildRequires:  pkgconfig(gtk+-wayland-3.0) >= 3.22
BuildRequires:  pkgconfig(gdk-3.0) >= 3.22
BuildRequires:  pkgconfig(gdk-wayland-3.0) >= 3.22
BuildRequires:  pkgconfig(json-glib-1.0)
BuildRequires:  pkgconfig(libfeedback-0.0)
BuildRequires:  pkgconfig(libhandy-1) >= 1.8.0
BuildRequires:  pkgconfig(libsystemd) >= 241
BuildRequires:  pkgconfig(wayland-client) >= 1.14
BuildRequires:  pkgconfig(wayland-protocols) >= 1.39
BuildRequires:  pkgconfig(xkbcommon)
BuildRequires:  pkgconfig(hunspell)
# FIXME: uim test fails "Didn't find our IM, can't parse outputs"
# BuildRequires:  pkgconfig(uim)
BuildRequires:  pkgconfig(dconf) >= 0.49
BuildRequires:  /usr/bin/fzf
BuildRequires:  /usr/bin/rst2man
BuildRequires:  /usr/bin/xwfb-run
BuildRequires:  mutter
BuildRequires:  gettext
BuildRequires:  systemd-rpm-macros
BuildRequires:  libappstream-glib
BuildRequires:  desktop-file-utils
BuildRequires:  words
BuildRequires:  systemd-rpm-macros

%description
Stevia is an on screen keyboard (OSK) for Phosh.

The purpose of Stevia is:
* to make typing pleasant and fast on touch screens
* be helpful when debugging input-method related issues
* be quick and easy to (cross)compile
* to be easy to extend (hence the API documentation)

%package phosh-osk-provider
Summary:   Use Stevia as Phosh's default OSK
BuildArch: noarch
Requires:  %{name}
Provides:  phosh-osk = 1.0
Conflicts: phosh-osk
Conflicts: squeekboard-phosh-osk-provider

%description phosh-osk-provider
%{summary}.

%prep
%autosetup -p1 -n %{name}-v%{version_no_tilde _}

%conf
%meson -Dman=true

%build
%meson_build

%install
%meson_install
%find_lang phosh-osk-%{name} --with-man

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/sm.puri.OSK0.desktop
# Using mutter because https://gitlab.freedesktop.org/ofourdan/xwayland-run/-/issues/12
LC_ALL=C.UTF-8 xwfb-run -c mutter -- sh <<'SH'
%meson_test
SH

%files -f phosh-osk-%{name}.lang
%doc README.md SWIPE-PROTOTYPE.md
%license COPYING
%{_bindir}/phosh-osk-stevia
%{_datadir}/glib-2.0/schemas/mobi.phosh.osk.enums.xml
%{_datadir}/glib-2.0/schemas/mobi.phosh.osk.gschema.xml
%{_datadir}/metainfo/mobi.phosh.Stevia.metainfo.xml
%{_datadir}/phosh-osk-stevia/
%{_mandir}/man1/phosh-osk-stevia.1*

%files phosh-osk-provider
%{_datadir}/applications/sm.puri.OSK0.desktop
%{_userunitdir}/mobi.phosh.OSK.service

%changelog
* Wed Sep 09 2026 Sam Day <me@samcday.com> - 0.57.0-1.3.pocketfed
- Add tested whole-word swipes, fading trail, editable guesses and selection undo
- Preserve stationary alternate-character holds and support Shift/Caps Lock
- Keep swipe disabled by default; personal images opt in separately

* Mon Sep 07 2026 PocketFed contributors <pocketfed@localhost> - 0.57.0-1.2.pocketfed
- Use one ranked Verbisage Complete reply and retain the original typed spelling
- Improve all-caps candidates and cover ranking, caps, and unsupported daemons
* Mon Sep 07 2026 PocketFed contributors <pocketfed@localhost> - 0.57.0-1.1.pocketfed
- Add opt-in asynchronous Verbisage completion backend and private D-Bus tests
