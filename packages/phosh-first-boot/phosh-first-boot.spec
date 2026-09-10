%bcond check 1

%global app_id mobi.phosh.FirstBoot
%global gettext_domain PhoshFirstBoot

Name:           phosh-first-boot
Version:        0.1.1
Release:        1.4.pocketfed%{?dist}
Summary:        First boot setup assistant for Phosh

SourceLicense:  GPL-3.0-or-later
# Select MIT for the dual-licensed Rust dependencies. The generated
# LICENSE.dependencies records the complete linked dependency breakdown.
License:        GPL-3.0-or-later AND MIT AND Unicode-3.0
URL:            https://gitlab.gnome.org/World/Phosh/phosh-first-boot
Source0:        %{url}/-/archive/v%{version}/%{name}-v%{version}.tar.gz

# See prepare-sources for the deterministic locked Rust vendor archive.
Source1:        vendor-%{version}.tar.xz
Source2:        defaults.conf
Source3:        collect-notices.py
Source4:        check-build-configuration.py
Patch0:         0001-update-rust-dependencies.patch
Patch1:         0002-import-from-configured-output-directory.patch
Patch2:         0003-timezone-and-recoverable-setup.patch
Patch3:         0004-handle-unavailable-locale-names.patch
Patch4:         0005-commit-account-setup-navigation.patch
Patch5:         0006-keep-setup-visible-until-completion.patch
Patch6:         0007-preserve-meson-package-configuration.patch
Patch7:         0008-filter-timezone-city-search.patch

ExclusiveArch:  %{rust_arches}

BuildRequires:  cargo-rpm-macros >= 25
BuildRequires:  desktop-file-utils
BuildRequires:  gettext-devel
BuildRequires:  glib2-devel
BuildRequires:  libxcrypt-devel
BuildRequires:  meson
BuildRequires:  pkgconfig(gtk4) >= 4.20
BuildRequires:  pkgconfig(libadwaita-1) >= 1.8
BuildRequires:  pkgconfig(pms-1.0)
BuildRequires:  pkgconfig(systemd)
BuildRequires:  systemd-rpm-macros
BuildRequires:  python3

Requires:       bash
Requires:       accountsservice
Requires:       dconf
Requires:       greetd
Requires:       polkit
# Fedora ships homed in systemd-udev; depend on the actual account backend.
Requires:       /usr/lib/systemd/systemd-homed
Requires:       systemd-pam
Requires:       tzdata
Recommends:     phrog >= 0.53.0

%description
Phosh First Boot is a first boot assistant that helps users configure
their system after booting a device for the first time.

%prep
%autosetup -n %{name}-v%{version} -p1 -a1
%cargo_prep -v vendor

%build
export GETTEXT_SYSTEM=1 PFB_MESON_PRECONFIGURED=1
%meson \
  -Dsetup-user=greetd \
  -Doutput-dir-group=greetd \
  -Doutput-dir=/var/lib/phosh-first-boot \
  -Dsystemd_user_unit_dir=%{_userunitdir} \
  -Dtmpfiles_dir=%{_tmpfilesdir}
%meson_build
%cargo_build -- --locked
%cargo_vendor_manifest
%{cargo_license_summary}
%{cargo_license} > LICENSE.dependencies
%{__python3} %{SOURCE3}

%install
export GETTEXT_SYSTEM=1
%meson_install
install -Dpm 0755 target/rpm/%{name} -t %{buildroot}%{_bindir}
install -Dpm 0755 target/rpm/%{name}-importer -t %{buildroot}%{_libexecdir}
install -Dpm 0644 %{SOURCE2} %{buildroot}%{_datadir}/%{name}/defaults.conf
%find_lang %{gettext_domain}

%check
%if %{with check}
export GETTEXT_SYSTEM=1 PFB_MESON_PRECONFIGURED=1
%meson_test
%cargo_test -- --locked
%{__python3} %{SOURCE4} --config src/pfb/config.rs --binary %{buildroot}%{_bindir}/%{name}
%endif

%post
%tmpfiles_create %{_tmpfilesdir}/%{name}.conf
%systemd_user_post %{name}-importer.service

%preun
%systemd_user_preun %{name}-importer.service

%files -f %{gettext_domain}.lang
%license COPYING
%license LICENSE.dependencies
%license cargo-vendor.txt
%license LICENSE.vendor
%doc NEWS README.md
%{_bindir}/%{name}
%{_libexecdir}/%{name}-importer
%{_userunitdir}/%{name}-importer.service
%{_tmpfilesdir}/%{name}.conf
%{_datadir}/applications/%{app_id}.desktop
%{_datadir}/glib-2.0/schemas/00_%{app_id}.gschema.override
%{_datadir}/glib-2.0/schemas/%{app_id}.gschema.xml
%{_datadir}/icons/hicolor/symbolic/apps/%{app_id}-symbolic.svg
%{_datadir}/polkit-1/rules.d/20-%{name}.rules
%{_datadir}/%{name}/

%changelog
* Thu Sep 10 2026 Sam Day <me@samcday.com> - 0.1.1-1.4.pocketfed
- Preserve packaged Meson paths during Cargo builds and test the installed binary
- Keep first boot visible until the final Get started action
- Match time zone city names with case-insensitive substring search

* Thu Sep 10 2026 Sam Day <me@samcday.com> - 0.1.1-1.3.pocketfed
- Commit setup navigation when the first account is created
- Prevent changes to the saved settings during and after account creation

* Thu Sep 10 2026 Sam Day <me@samcday.com> - 0.1.1-1.2.pocketfed
- Display the locale identifier when libpms cannot translate its name
- Avoid aborting setup when a supplied locale is not installed

* Thu Sep 10 2026 Sam Day <me@samcday.com> - 0.1.1-1.1.pocketfed
- Update the Fedora Mobility package to 0.1.1 with upstream dependency fixes
- Use the Fedora greetd user and group for firstboot settings output
- Require systemd-homed for account creation and handle importer user presets
- Include the bundled Rust dependency licenses in the package license
- Create a Fedora administrator account and preserve settings until first login
- Add offline touch timezone selection and recoverable locale/account setup
