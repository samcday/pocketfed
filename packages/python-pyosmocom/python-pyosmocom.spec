Name:           python-pyosmocom
Version:        0.0.12
Release:        1.2.pocketfed%{?dist}
Summary:        Core Osmocom utilities and protocols for Python
License:        GPL-2.0-or-later
URL:            https://gitea.osmocom.org/osmocom/pyosmocom
Source0:        %{pypi_source pyosmocom}
BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  python3-pytest

%global _description %{expand:
Core Osmocom data conversion, TLV, Construct and cellular-protocol utilities.}

%description %_description

%package -n python3-pyosmocom
Summary:        %{summary}

%description -n python3-pyosmocom %_description

%prep
%autosetup -n pyosmocom-%{version}
# This is an imported module, not an executable script.
sed -i '1{/^#!/d;}' src/osmocom/gsup/message.py

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files -l osmocom

%check
%pytest tests

%files -n python3-pyosmocom -f %{pyproject_files}
%doc README.md

%changelog
* Thu Sep 10 2026 PocketFed maintainers <me@samcday.com> - 0.0.12-1.2.pocketfed
- Remove an unused shebang from an installed library module

* Thu Sep 10 2026 PocketFed maintainers <me@samcday.com> - 0.0.12-1.1.pocketfed
- Initial package with the upstream protocol/conversion tests
