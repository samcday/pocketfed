%global commit e5cc292dc95d3745341db67387d5fd0ff0e8c9e7

Name:           qcom-baseband-profile-manager
Version:        0.1.1
Release:        1.2.pocketfed%{?dist}
Summary:        Select modem-resident Qualcomm carrier configuration profiles
License:        GPL-2.0-or-later
URL:            https://gitlab.postmarketos.org/modem/openimsd/qcom-baseband-profile-manager
Source0:        %{url}/-/archive/%{commit}/%{name}-%{commit}.tar.gz
Source1:        test_regressions.py
Source2:        qcom-baseband-profile-manager.conf.example
Source3:        qcom-baseband-profile-manager.1
Patch0:         0001-fix-carrier-lookup-and-task-scheduling.patch
BuildArch:      noarch
BuildRequires:  python3-devel >= 3.12
BuildRequires:  pyproject-rpm-macros
BuildRequires:  python3-gobject-base >= 3.50
BuildRequires:  libqmi
BuildRequires:  libqrtr-glib
BuildRequires:  systemd-rpm-macros
Requires:       python3-gobject-base >= 3.50
# Backport of upstream 082bf345 fixes nested GArray introspection on PyGObject 3.56+.
Requires:       libqmi >= 1.36.0-4.1.pocketfed
Requires:       libqrtr-glib
%{?systemd_requires}

%description
An experimental OpenIMSd daemon that chooses and activates Qualcomm modem
software profiles using QMI PDC, based on the primary SIM's carrier identity.
It currently requires profiles to be uploaded separately. It does not discover
vendor MBN files, provision embedded SIM profiles, or supply an IMS implementation.

No service configuration is installed by default. An administrator must supply
device-appropriate resident profile IDs before enabling this service.

%prep
%autosetup -n %{name}-%{commit} -p1
sed -i '1{/^#!/d;}' src/qcom_baseband_profile_manager/main.py
mkdir -p tests
cp %{SOURCE1} tests/
cp %{SOURCE2} config.example.toml

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files -l qcom_baseband_profile_manager
install -Dpm0644 contrib/%{name}.service %{buildroot}%{_unitdir}/%{name}.service
install -Dpm0644 %{SOURCE3} %{buildroot}%{_mandir}/man1/%{name}.1
# Configuration must be explicit: do not use upstream's device-specific IDs.
sed -i '/^\[Unit\]/a ConditionPathExists=/etc/qcom-baseband-profile-manager.toml' \
    %{buildroot}%{_unitdir}/%{name}.service

%check
export PYTHONPATH=%{buildroot}%{python3_sitelib}
%{python3} -m unittest discover -s tests -v
%{python3} -m qcom_baseband_profile_manager --help

%post
%systemd_post %{name}.service

%preun
%systemd_preun %{name}.service

%postun
%systemd_postun_with_restart %{name}.service

%files -f %{pyproject_files}
%doc README.md config.example.toml
%{_bindir}/%{name}
%{_unitdir}/%{name}.service
%{_mandir}/man1/%{name}.1*

%changelog
* Thu Sep 10 2026 PocketFed maintainers <me@samcday.com> - 0.1.1-1.2.pocketfed
- Add a manual page and remove an unused library-module shebang

* Thu Sep 10 2026 PocketFed maintainers <me@samcday.com> - 0.1.1-1.1.pocketfed
- Initial experimental package; no automatic service or carrier policy
- Fix same-country carrier lookup and duplicate/invalid asyncio scheduling
