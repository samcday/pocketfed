%global gvc_commit d2442f455844e5292cb4a74ffc66ecc8d7595a9f
%global libcall_ui_version v0.1.5

Name:     phosh
Version:  0.57.0
Release:  1.1.pocketfed%{?dist}
Summary:  Graphical shell for mobile devices
License:  GPL-3.0-or-later
URL:      https://gitlab.gnome.org/World/Phosh/phosh
# Fedora mirrors the identical upstream archive (see sources).
# Source0:  https://gitlab.gnome.org/World/Phosh/phosh/-/archive/v%{version_no_tilde _}/%{name}-v%{version_no_tilde _}.tar.gz
Source0:  https://src.fedoraproject.org/repo/pkgs/rpms/phosh/phosh-v0.57.0.tar.gz/sha512/29c177cbc6ba25880160aafec2abc00fe0d02fee63466dd429dc7e0b70f8f2cbdb84e048004c4811932b53a63c56c49d3b597e8f55a77a9751483b51d5774bfc/phosh-v0.57.0.tar.gz
# This library doesn't compile into a DSO nor has any tagged releases.
# Other projects such as gnome-shell use it this way.
# Fedora mirrors the identical upstream archive (see sources).
# Source1:  https://gitlab.gnome.org/GNOME/libgnome-volume-control/-/archive/%{gvc_commit}/libgnome-volume-control-%{gvc_commit}.tar.gz
Source1:  https://src.fedoraproject.org/repo/pkgs/rpms/phosh/libgnome-volume-control-d2442f455844e5292cb4a74ffc66ecc8d7595a9f.tar.gz/sha512/6214f4c17f85b76b04f9f60c8fc4fd993bca8d7c61df40e4aa96cb921831b666719d6666474a8f2eda9fcd483dbd4d53cfc55773981fa1e6b1c214bdb698d1e0/libgnome-volume-control-d2442f455844e5292cb4a74ffc66ecc8d7595a9f.tar.gz
# Similar situation as gvc
# Fedora mirrors the identical upstream archive (see sources).
# Source2:  https://gitlab.gnome.org/World/Phosh/libcall-ui/-/archive/%{libcall_ui_version}/libcall-ui-%{libcall_ui_version}.tar.gz
Source2:  https://src.fedoraproject.org/repo/pkgs/rpms/phosh/libcall-ui-v0.1.5.tar.gz/sha512/e6cbcfd93396cee438262716f29dfe898fa9c061af977d92ff67014388cec71883dbd46500bfc6817647a3a86859daec5594444e3898b825caeac51fe9dac1b1/libcall-ui-v0.1.5.tar.gz
Source3:  phosh

# One user submission must not replay a token after PAM reports rejection.
Patch0:   0001-auth-do-not-replay-a-rejected-token.patch
Provides: phosh-pam-retry-fix = 1

ExcludeArch:  %{ix86}
# https://bugzilla.redhat.com/show_bug.cgi?id=2426735
ExcludeArch:  ppc64le
# We don't anticipate anybody running phosh on their legacy mainframe servers.
ExcludeArch:  s390x

BuildRequires:  gcc
BuildRequires:  meson
BuildRequires:  pam-devel
BuildRequires:  pkgconfig(appstream) >= 1.0.0
BuildRequires:  pkgconfig(libecal-2.0) >= 3.33.1
BuildRequires:  pkgconfig(libedataserver-1.2) >= 3.33.1
BuildRequires:  pkgconfig(fribidi)
BuildRequires:  pkgconfig(gcr-3) >= 3.7.5
BuildRequires:  pkgconfig(glib-2.0) >= 2.80
BuildRequires:  pkgconfig(gio-2.0) >= 2.80
BuildRequires:  pkgconfig(gio-unix-2.0) >= 2.80
BuildRequires:  pkgconfig(gmobile) >= 0.1.0
BuildRequires:  pkgconfig(gnome-bluetooth-3.0) >= 46.0
BuildRequires:  pkgconfig(gnome-desktop-3.0) >= 3.26
BuildRequires:  pkgconfig(gobject-2.0) >= 2.80
BuildRequires:  pkgconfig(gsettings-desktop-schemas) >= 47
BuildRequires:  pkgconfig(gtk+-3.0) >= 3.24.36
BuildRequires:  pkgconfig(gtk+-wayland-3.0) >= 3.22
BuildRequires:  pkgconfig(gudev-1.0)
BuildRequires:  pkgconfig(libfeedback-0.0) >= 0.7.0
BuildRequires:  pkgconfig(libhandy-1) >= 1.8.0
BuildRequires:  pkgconfig(libnm) >= 1.14
BuildRequires:  pkgconfig(polkit-agent-1) >= 0.122
BuildRequires:  pkgconfig(libsoup-3.0) >= 3.6
BuildRequires:  pkgconfig(libsystemd) >= 241
BuildRequires:  pkgconfig(libsecret-1)
BuildRequires:  pkgconfig(upower-glib) >= 1.90
BuildRequires:  pkgconfig(wayland-client) >= 1.14
BuildRequires:  pkgconfig(wayland-protocols) >= 1.12
BuildRequires:  pkgconfig(gtk4) >= 4.12
BuildRequires:  pkgconfig(libadwaita-1) >= 1.6
BuildRequires:  pkgconfig(evince-document-3.0)
BuildRequires:  pkgconfig(evince-view-3.0)
BuildRequires:  pkgconfig(alsa)
BuildRequires:  pkgconfig(libpulse) >= 12.99.3
BuildRequires:  pkgconfig(libpulse-mainloop-glib)
BuildRequires:  pkgconfig(libcallaudio-0.1)
BuildRequires:  pkgconfig(mm-glib) >= 1.24.0
BuildRequires:  pkgconfig(qrcodegen)
BuildRequires:  pkgconfig(wlroots-0.20) >= 0.20.2
BuildRequires:  /usr/bin/xvfb-run
BuildRequires:  /usr/bin/xauth
BuildRequires:  dbus-daemon
BuildRequires:  desktop-file-utils
BuildRequires:  systemd-rpm-macros
BuildRequires:  xmlstarlet

Requires:  gnome-session >= 49.0
Requires:  gnome-settings-daemon >= 49.0
Requires:  gnome-shell-common >= 49.0
Requires:  hicolor-icon-theme
Requires:  lato-fonts
Requires:  mutter-common
Requires:  phoc >= 0.52.0
Requires:  phosh-osk = 1.0
Requires:  xorg-x11-server-Xwayland

Recommends:  gnome-control-center
Recommends:  phosh-mobile-settings
Suggests:    stevia-phosh-osk-provider

%description
Phosh is a simple shell for Wayland compositors speaking the layer-surface
protocol. It currently supports

* a lockscreen
* brightness control and nightlight
* the GCR system-prompter interface
* acting as a polkit auth agent
* enough of org.gnome.Mutter.DisplayConfig to make gnome-settings-daemon happy
* a homebutton that toggles a simple favorites menu
* status icons for battery, wwan and wifi

%package devel
Summary:   Development headers for Phosh
Requires:  %{name}%{?_isa} = %{?epoch:%{epoch}:}%{version}-%{release}

%description devel
Development headers for Phosh.

%package -n libphosh
Summary:    Experimental library of Phosh components and functionality.
Requires:   %{name}%{?_isa} = %{?epoch:%{epoch}:}%{version}-%{release}

%description -n libphosh
Experimental shared library of Phosh components and functionality, allowing
other projects to embed Phosh.

%package -n libphosh-devel
Summary:    Development headers for libphosh.
Requires:   lib%{name}%{?_isa} = %{?epoch:%{epoch}:}%{version}-%{release}

%description -n libphosh-devel
Development headers for libphosh.

%prep
%setup -a1 -a2 -q -n %{name}-v%{version_no_tilde _}
%autopatch -p1

mv libgnome-volume-control-%{gvc_commit} subprojects/gvc
mv libcall-ui-%{libcall_ui_version} subprojects/libcall-ui

%build
%meson -Dphoc_tests=disabled -Dbindings-lib=true -Dsearchd=true
%meson_build

%install
install -d %{buildroot}%{_sysconfdir}/pam.d/
cp %{SOURCE3} %{buildroot}%{_sysconfdir}/pam.d/

%meson_install
%find_lang %{name}

%{__install} -Dpm 0644 data/phosh.service %{buildroot}%{_unitdir}/phosh.service
rm %{buildroot}%{_libdir}/libphosh-0.45.a

%check
# Fail if the patch or its regression target is accidentally omitted.
test -x %{_vpath_builddir}/tests/test-auth
desktop-file-validate \
%{buildroot}%{_datadir}/applications/mobi.phosh.Shell.desktop
%{shrink:LC_ALL=C.UTF-8 xvfb-run %meson_test}

%files -f %{name}.lang
%{_bindir}/phosh-session
%{_libexecdir}/phosh
%{_libexecdir}/phosh-calendar-server
%{_libexecdir}/phosh-searchd
%{_datadir}/applications/mobi.phosh.Shell.desktop
%{_datadir}/glib-2.0/schemas/mobi.phosh.shell.gschema.xml
%{_datadir}/glib-2.0/schemas/mobi.phosh.shell.enums.xml
%{_datadir}/glib-2.0/schemas/00_mobi.Phosh.gschema.override
%{_datadir}/glib-2.0/schemas/sm.puri.phosh.plugins.ticket-box.gschema.xml
%{_datadir}/glib-2.0/schemas/sm.puri.phosh.plugins.launcher-box.gschema.xml
%{_datadir}/glib-2.0/schemas/sm.puri.phosh.plugins.upcoming-events.gschema.xml
%{_datadir}/glib-2.0/schemas/mobi.phosh.plugins.pomodoro.gschema.xml
%{_datadir}/glib-2.0/schemas/mobi.phosh.plugins.caffeine-quick-setting.gschema.xml
%{_datadir}/gnome-session/sessions/phosh.session
%{_datadir}/wayland-sessions/phosh.desktop
%{_datadir}/phosh
%{_sysconfdir}/pam.d/phosh
%{_userunitdir}/gnome-session@phosh.target.d/session.conf
%{_userunitdir}/mobi.phosh.OSK.target
%{_userunitdir}/mobi.phosh.Shell.service
%{_userunitdir}/mobi.phosh.Shell.target
%{_datadir}/xdg-desktop-portal/portals/phosh-shell.portal
%{_datadir}/xdg-desktop-portal/phosh-portals.conf
%{_datadir}/icons/hicolor/symbolic/apps/mobi.phosh.Shell-symbolic.svg
%{_datadir}/dbus-1/services/mobi.phosh.Shell.CalendarServer.service
%{_datadir}/dbus-1/services/mobi.phosh.Shell.Search.service
%{_libdir}/phosh/plugins/caffeine-quick-setting.plugin
%{_libdir}/phosh/plugins/calendar.plugin
%{_libdir}/phosh/plugins/dark-mode-quick-setting.plugin
%{_libdir}/phosh/plugins/emergency-info.plugin
%{_libdir}/phosh/plugins/launcher-box.plugin
%{_libdir}/phosh/plugins/load-meter-status-icon.plugin
%{_libdir}/phosh/plugins/location-quick-setting.plugin
%{_libdir}/phosh/plugins/mobile-data-quick-setting.plugin
%{_libdir}/phosh/plugins/night-light-quick-setting.plugin
%{_libdir}/phosh/plugins/simple-custom-quick-setting.plugin
%{_libdir}/phosh/plugins/ticket-box.plugin
%{_libdir}/phosh/plugins/upcoming-events.plugin
%{_libdir}/phosh/plugins/wifi-hotspot-quick-setting.plugin
%{_libdir}/phosh/plugins/pomodoro-quick-setting.plugin
%{_libdir}/phosh/plugins/scaling-quick-setting.plugin
%{_libdir}/phosh/plugins/media-players.plugin
%{_libdir}/phosh/plugins/simple-custom-status-icon.plugin
%{_libdir}/phosh/plugins/syncthing-quick-setting.plugin
%{_libdir}/phosh/plugins/libphosh-plugin-caffeine-quick-setting.so
%{_libdir}/phosh/plugins/libphosh-plugin-calendar.so
%{_libdir}/phosh/plugins/libphosh-plugin-dark-mode-quick-setting.so
%{_libdir}/phosh/plugins/libphosh-plugin-emergency-info.so
%{_libdir}/phosh/plugins/libphosh-plugin-launcher-box.so
%{_libdir}/phosh/plugins/libphosh-plugin-load-meter-status-icon.so
%{_libdir}/phosh/plugins/libphosh-plugin-location-quick-setting.so
%{_libdir}/phosh/plugins/libphosh-plugin-mobile-data-quick-setting.so
%{_libdir}/phosh/plugins/libphosh-plugin-night-light-quick-setting.so
%{_libdir}/phosh/plugins/libphosh-plugin-simple-custom-quick-setting.so
%{_libdir}/phosh/plugins/libphosh-plugin-ticket-box.so
%{_libdir}/phosh/plugins/libphosh-plugin-upcoming-events.so
%{_libdir}/phosh/plugins/libphosh-plugin-wifi-hotspot-quick-setting.so
%{_libdir}/phosh/plugins/libphosh-plugin-pomodoro-quick-setting.so
%{_libdir}/phosh/plugins/libphosh-plugin-scaling-quick-setting.so
%{_libdir}/phosh/plugins/libphosh-plugin-media-players.so
%{_libdir}/phosh/plugins/libphosh-plugin-simple-custom-status-icon.so
%{_libdir}/phosh/plugins/libphosh-plugin-syncthing-quick-setting.so
%{_libdir}/phosh/plugins/prefs/libphosh-plugin-prefs-emergency-info.so
%{_libdir}/phosh/plugins/prefs/libphosh-plugin-prefs-ticket-box.so
%{_libdir}/phosh/plugins/prefs/libphosh-plugin-prefs-upcoming-events.so
%{_libdir}/phosh/plugins/prefs/libphosh-plugin-prefs-pomodoro-quick-setting.so
%{_libdir}/phosh/plugins/prefs/libphosh-plugin-prefs-caffeine-quick-setting.so

%doc README.md
%license COPYING

%files devel
%{_datadir}/gir-1.0/Phosh-0.gir
%{_includedir}/phosh
%{_libdir}/pkgconfig/phosh-plugins.pc
%{_libdir}/pkgconfig/phosh-settings.pc
%{_unitdir}/phosh.service

%files -n libphosh
%{_libdir}/girepository-1.0/Phosh-0.typelib
%{_libdir}/libphosh-0.45.so.0

%files -n libphosh-devel
%{_includedir}/libphosh-0.45
%{_libdir}/libphosh-0.45.so
%{_libdir}/pkgconfig/libphosh-0.45.pc

%changelog
* Thu Sep 10 2026 Sam Day <me@samcday.com> - 0.57.0-1.1.pocketfed
- Stop replaying a rejected PIN in the lockscreen PAM conversation
- Test rejected-token retries and per-submission PAM transaction cleanup

* Thu Aug 20 2026 Sam Day <me@samcday.com> - 0.57.0-1
- v0.57.0 (fedora#2519850)

* Sun Aug 16 2026 Sam Day <me@samcday.com> - 0.57_rc1-1
- 0.57_rc1 (fedora#2515972)

* Fri Jul 31 2026 Sam Day <me@samcday.com> - 0.56.0-6
- Rebuild for libedataserver soname bump

* Thu Jul 30 2026 Sam Day <me@samcday.com> - 0.56.0-5
- Add missing libappstream BR

* Thu Jul 16 2026 Fedora Release Engineering <releng@fedoraproject.org> - 0.56.0-4
- Rebuilt for https://fedoraproject.org/wiki/Fedora_45_Mass_Rebuild

* Sun Jul 05 2026 Sam Day <me@samcday.com> - 0.56.0-2
- Exclude s390x

* Sun Jul 05 2026 Sam Day <me@samcday.com> - 0.56.0-1
- v0.56.0 (fedora#2497123)

* Tue Jun 30 2026 Sam Day <me@samcday.com> - 0.56~rc1-2
- Rebuild for new gnome-desktop3

* Mon Jun 29 2026 Tomi Lähteenmäki <lihis@lihis.net> - 0.56~rc1-1
- Upstream release 0.56~rc1 (fedora#2493934)

* Sun May 17 2026 Tomi Lähteenmäki <lihis@lihis.net> - 0.55.0-1
- Upstream release 0.55.0 (fedora#2476989)

* Sun Apr 05 2026 Tomi Lähteenmäki <lihis@lihis.net> - 0.54.0-1
- Upstream release 0.54.0 (fedora#2455179)

* Fri Mar 27 2026 Tomi Lähteenmäki <lihis@lihis.net> - 0.54~rc1-1
- Upstream release 0.54~rc1 (fedora#2452206)

* Sun Feb 22 2026 Tomi Lähteenmäki <lihis@lihis.net> - 0.53.1-1
- Upstream release 0.53.1 (fedora#2441657)

* Sun Feb 15 2026 Tomi Lähteenmäki <lihis@lihis.net> - 0.53.0-1
- Upstream release 0.53.0 (fedora#2440033)

* Tue Feb 10 2026 Tomi Lähteenmäki <lihis@lihis.net> - 0.53~rc1-1
- Upstream release 0.53-rc1 (fedora#2438553)

* Sat Jan 17 2026 Fedora Release Engineering <releng@fedoraproject.org> - 0.52.1-3
- Rebuilt for https://fedoraproject.org/wiki/Fedora_44_Mass_Rebuild

* Wed Jan 07 2026 Sam Day <me@samcday.com> - 0.52.1-2
- fixup! Upstream release 0.52.1 (fedora#2427645)

* Wed Jan 07 2026 Sam Day <me@samcday.com> - 0.52.1-1
- Upstream release 0.52.1 (fedora#2427645)

* Mon Jan 05 2026 Sam Day <me@samcday.com> - 0.52.0-3
- %%{shrink} the test execution command

* Mon Jan 05 2026 Sam Day <me@samcday.com> - 0.52.0-2
- fixup! ExcludeArch ppc64le

* Sun Jan 04 2026 Sam Day <me@samcday.com> - 0.52.0-1
- Upstream release 0.52.0 (fedora#2427020)

* Wed Dec 31 2025 Sam Day <me@samcday.com> - 0.52~rc1-1
- Upstream release 0.52_rc1 (fedora#2426508)

* Sun Nov 16 2025 Sam Day <me@samcday.com> - 0.51.0-1
- Upstream release 0.51.0

* Sun Nov 09 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.51_rc1-1
- Upstream release 0.51_rc1 (fedora#2400452)

* Wed Oct 22 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.50.1-1
- Upstream release 0.50.1 (fedora#2400452)

* Sat Oct 11 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.50.0-1
- Upstream release 0.50.0 (fedora#2400452)

* Wed Oct 08 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.49.0-4
- Suggest stevia-phosh-osk-provider

* Sat Aug 16 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.49.0-1
- Upstream release 0.49.0 (fedora#2388754)

* Sat Aug 09 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.49~rc1-1
- Upstream release 0.49-rc1 (fedora#2387418)

* Fri Jul 25 2025 Fedora Release Engineering <releng@fedoraproject.org> - 0.48.0-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_43_Mass_Rebuild

* Tue Jul 01 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.48.0-1
- Upstream release 0.48.0

* Sun Jun 22 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.48~rc1-1
- Upstream release 0.48-rc1

* Sun May 18 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.47.0-1
- Upstream release 0.47.0 (fedora#2367062)

* Fri May 09 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.47~rc1-1
- Upstream release 0.47-rc1 (fedora#2365299)

* Mon Mar 31 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.46.0-1
- Upstream release 0.46.0

* Mon Mar 31 2025 Sam Day <me@samcday.com> - 0.46~rc1-4
- Drop gnome-shell dependency

* Wed Mar 26 2025 Tomi Laehteenmaeki <lihis@lihis.net> - 0.46~rc1-2
- RPMAUTOSPEC: unresolvable merge
