%global gvdb_commit 4758f6fb7f889e074e13df3f914328f3eecb1fd3

Name:     phoc
Version:  0.57.0
Release:  2.1.pocketfed%{?dist}
Summary:  Display compositor designed for phones

License:  GPL-3.0-or-later
URL:      https://gitlab.gnome.org/World/Phosh/phoc
Source0:  https://gitlab.gnome.org/World/Phosh/phoc/-/archive/v%{version_no_tilde _}/%{name}-v%{version_no_tilde _}.tar.gz
Source1:  https://gitlab.gnome.org/GNOME/gvdb/-/archive/%{gvdb_commit}/gvdb-%{gvdb_commit}.tar.gz

# https://gitlab.gnome.org/World/Phosh/phoc/-/merge_requests/805
Patch0:   805.diff
# Reacquire the touch point after gesture-triggered cancellation.
Patch1:   phoc-0.57.0-touch-up-lifetime.patch

Provides: phoc-touch-up-lifetime-fix = 1

BuildRequires:  gcc
BuildRequires:  meson
BuildRequires:  cmake
BuildRequires:  gettext
BuildRequires:  /usr/bin/rst2man

BuildRequires:  pkgconfig(gio-2.0) >= 2.80
BuildRequires:  pkgconfig(glib-2.0) >= 2.80
BuildRequires:  pkgconfig(gobject-2.0) >= 2.80
BuildRequires:  pkgconfig(glesv2)
BuildRequires:  pkgconfig(gnome-desktop-3.0) >= 3.26
BuildRequires:  pkgconfig(libinput) >= 1.27.0
BuildRequires:  pkgconfig(libudev)
BuildRequires:  pkgconfig(libdrm)
BuildRequires:  pkgconfig(pixman-1) >= 0.43.4
BuildRequires:  pkgconfig(wayland-client) >= 1.23.1
BuildRequires:  pkgconfig(wayland-server) >= 1.23.1
BuildRequires:  pkgconfig(wayland-protocols) >= 1.15
BuildRequires:  pkgconfig(wayland-server)
BuildRequires:  pkgconfig(xkbcommon) >= 1.8.0
BuildRequires:  pkgconfig(gmobile) >= 0.6.0
BuildRequires:  pkgconfig(wlroots-0.20) >= 0.20.2
BuildRequires:  pkgconfig(gsettings-desktop-schemas)
BuildRequires:  pkgconfig(json-glib-1.0)
BuildRequires:  /usr/bin/xvfb-run
# tests need dbus-daemon, mutter gschemas and Xwayland
BuildRequires:  dbus-daemon
BuildRequires:  mutter-common
BuildRequires:  xorg-x11-server-Xwayland

Requires:       gmobile >= 0.6.0

ExcludeArch:  %{ix86}
# This package has no demonstrable use-cases for server/mainframe hardware.
ExcludeArch:  s390x
ExcludeArch:  ppc64le

%description
Phoc is a wlroots based Phone compositor as used on the Librem5. Phoc is
pronounced like the English word fog.

%prep
%autosetup -a1 -p1 -n %{name}-v%{version_no_tilde _}
mv gvdb-%{gvdb_commit} subprojects/gvdb

%conf
%meson -Dembed-wlroots=disabled -Dman=true

%build
%meson_build

%install
%meson_install
%find_lang %{name}

%check
%{shrink:xvfb-run -s -noreset %meson_test}

%files -f %{name}.lang
%doc README.md
%license LICENSES
%{_bindir}/phoc
%{_bindir}/phoc-outputs-states
%{_datadir}/phoc
%{_datadir}/glib-2.0/schemas/mobi.phosh.phoc.gschema.xml
%{_datadir}/applications/mobi.phosh.Phoc.desktop
%{_datadir}/icons/hicolor/symbolic/apps/mobi.phosh.Phoc.svg
%{_mandir}/man1/phoc.1.gz
%{_mandir}/man1/phoc-outputs-states.1.gz
%{_mandir}/man5/phoc.gsettings.5.gz
%{_mandir}/man5/phoc.ini.5.gz

%changelog
* Mon Sep 07 2026 Sam Day <me@samcday.com> - 0.57.0-2.1.pocketfed
- Fix touch-up use-after-free during top-panel gesture cancellation
- Add a regression test for touch cancellation during gesture dispatch

* Thu Aug 20 2026 Sam Day <me@samcday.com> - 0.57.0-2
- Backport fix for flaky screenshot tests

* Wed Aug 19 2026 Sam Day <me@samcday.com> - 0.57.0-1
- v0.57.0 (fedora#2519435)

* Sun Aug 16 2026 Sam Day <me@samcday.com> - 0.57_rc1-1
- 0.57_rc1 (fedora#2515194)

* Thu Jul 16 2026 Fedora Release Engineering <releng@fedoraproject.org> - 0.56.0-4
- Rebuilt for https://fedoraproject.org/wiki/Fedora_45_Mass_Rebuild

* Sat Jul 04 2026 Tomi Lähteenmäki <lihis@lihis.net> - 0.56.0-1
- Upstream release 0.56.0 (fedora#2497043)

* Tue Jun 30 2026 Sam Day <me@samcday.com> - 0.56~rc1-2
- Rebuild for new gnome-desktop3

* Sun Jun 28 2026 Tomi Lähteenmäki <lihis@lihis.net> - 0.56~rc1-1
- Upstream release 0.56~rc1

* Wed Jun 03 2026 Tomi Lähteenmäki <lihis@lihis.net> - 0.55.1-1
- Upstream release 0.55.1 (fedora#2483694)

* Wed Jun 03 2026 Tomi Lähteenmäki <lihis@lihis.net> - 0.55.0-2
- Disable xdg_shell_toplevel_maximized_scale test

* Fri May 15 2026 Tomi Lähteenmäki <lihis@lihis.net> - 0.55.0-1
- Upstream release 0.55.0 (fedora#2477941)

* Sun May 10 2026 Tomi Lähteenmäki <lihis@lihis.net> - 0.55~rc1-1
- Upstream release 0.55~rc1 (fedora#2468367)

* Sat Apr 11 2026 Tomi Lähteenmäki <lihis@lihis.net> - 0.55~alpha1-1
- Upstream release 0.55_alpha1 (fedora#2457242)

* Sat Apr 04 2026 Tomi Lähteenmäki <lihis@lihis.net> - 0.54.0-1
- Upstream release 0.54.0 (fedora#2454967)

* Thu Mar 26 2026 Tomi Lähteenmäki <lihis@lihis.net> - 0.54~rc1-1
- Upstream release 0.54~rc1 (fedora#2451742)

* Sun Feb 15 2026 Tomi Lähteenmäki <lihis@lihis.net> - 0.53.0-1
- Upstream release (fedora#2440012)

* Mon Feb 09 2026 Tomi Lähteenmäki <lihis@lihis.net> - 0.53~rc1-1
- Upstream release 0.53-rc1 (fedora#2437968)

* Mon Feb 02 2026 Sam Day <me@samcday.com> - 0.52.0-7
- phoc requires gmobile

* Sat Jan 17 2026 Fedora Release Engineering <releng@fedoraproject.org> - 0.52.0-5
- Rebuilt for https://fedoraproject.org/wiki/Fedora_44_Mass_Rebuild

* Mon Jan 05 2026 Sam Day <me@samcday.com> - 0.52.0-4
- %%{shrink} test execution command

* Mon Jan 05 2026 Sam Day <me@samcday.com> - 0.52.0-3
- Revert "Test with xwayland-run/xwfb-run instead of xvfb-run"

* Mon Jan 05 2026 Yaakov Selkowitz <yselkowi@redhat.com> - 0.52.0-2
- Test with xwayland-run/xwfb-run instead of xvfb-run

* Sun Jan 04 2026 Sam Day <me@samcday.com> - 0.52.0-1
- Upstream release 0.52.0 (fedora#2426944)

* Sun Dec 28 2025 Sam Day <me@samcday.com> - 0.52~rc1-1
- Upstream release 0.52_rc1 (fedora#2425382)

* Sun Nov 16 2025 Sam Day <me@samcday.com> - 0.51.0-1
- fixup! Upstream release 0.51.0 (fedora#2415187)

* Sun Nov 16 2025 Sam Day <me@samcday.com> - 0.51~rc1-2
- Upstream release 0.51.0 (fedora#2415187)

* Sun Nov 09 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.51~rc1-1
- Upstream release 0.51_rc1 (fedora#2400106)

* Sat Oct 11 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.50.0-1
- Upstream release (fedora#2400106)

* Sat Aug 16 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.49.0-1
- Upstream release 0.49.0 (fedora#2388744)

* Sat Aug 09 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.49~rc1-1
- Upstream release 0.49-rc1 (fedora#2387245)

* Fri Jul 25 2025 Fedora Release Engineering <releng@fedoraproject.org> - 0.48.0-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_43_Mass_Rebuild

* Tue Jul 01 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.48.0-1
- Upstream release 0.48.0 (fedora#2375534)

* Sat May 17 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.47.0-1
- Upstream release 0.47.0 (fedora#2366969)

* Fri May 09 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.47~rc1-1
- Upstream release 0.47-rc1 (fedora#2365067)

* Mon Mar 31 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.46.0-1
- Upstream release 0.46.0 (fedora#2355283)

* Thu Mar 27 2025 Sam Day <me@samcday.com> - 0.46~rc2-1
- 0.46~rc2

* Tue Mar 25 2025 Sam Day <me@samcday.com> - 0.46~rc1-2
- Use version_no_tilde macro

* Tue Mar 25 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.46~rc1-1
- Upstream release 0.46-rc1

* Sat Feb 15 2025 Sam Day <me@samcday.com> - 0.45.0-4
- Package manpages

* Fri Feb 14 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.45.0-1
- Upstream release v0.45.0 (fedora#2345796)

* Sun Feb 09 2025 Sam Day <me@samcday.com> - 0.44.1-2
- Enable phoc tests

* Sat Jan 18 2025 Tomi Lähteenmäki <lihis@lihis.net> - 0.44.1-1
- Upstream release 0.44.1 (fedora#2338444)

* Sat Jan 18 2025 Fedora Release Engineering <releng@fedoraproject.org> - 0.44.0-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_42_Mass_Rebuild

* Wed Jan 01 2025 Sam Day <me@samcday.com> - 0.44.0-1
- Update to v0.44.0

* Mon Nov 18 2024 Tomi Lähteenmäki <lihis@lihis.net> - 0.43.0-1
- Upstream release v0.43.0 (fedora#2326435)

* Mon Oct 28 2024 Tomi Lähteenmäki <lihis@lihis.net> - 0.42.1-1
- Upstream release 0.42.1 (fedora#2315570)

* Mon Sep 30 2024 Tomi Lähteenmäki <lihis@lihis.net> - 0.42.0-1
- Upstream release v0.42.0 (fedora#2315570)

* Fri Aug 16 2024 Tomi Lähteenmäki <lihis@lihis.net> - 0.41.0-1
- Upstream release v0.41.0 (fedora#2305081)

* Tue Jul 23 2024 Tomi Lähteenmäki <lihis@lihis.net> - 0.40.1-1
- Update to v0.40.1 (fedora#2297886)

* Fri Jul 19 2024 Fedora Release Engineering <releng@fedoraproject.org> - 0.40.0-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_41_Mass_Rebuild

* Mon Jul 01 2024 Tomi Lähteenmäki <lihis@lihis.net> - 0.40.0-1
- Update to 0.40.0

* Sat Jun 29 2024 Tomi Lähteenmäki <lihis@lihis.net> - 0.40.0~rc1-1
- Update to 0.40.0~rc1 (fedora#1897807)

* Tue Apr 09 2024 Kevin Fenzi <kevin@scrye.com> - 0.37.0-1
- Update for new phosh.

* Thu Jan 25 2024 Fedora Release Engineering <releng@fedoraproject.org> - 0.32.0-3
- Rebuilt for https://fedoraproject.org/wiki/Fedora_40_Mass_Rebuild

* Sun Jan 21 2024 Fedora Release Engineering <releng@fedoraproject.org> - 0.32.0-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_40_Mass_Rebuild

* Fri Jul 21 2023 Fedora Release Engineering <releng@fedoraproject.org> - 0.29.0-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_39_Mass_Rebuild

* Fri Jan 20 2023 Fedora Release Engineering <releng@fedoraproject.org> - 0.23.0-2
- Rebuilt for https://fedoraproject.org/wiki/Fedora_38_Mass_Rebuild
