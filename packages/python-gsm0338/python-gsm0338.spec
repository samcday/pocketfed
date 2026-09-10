Name:           python-gsm0338
Version:        1.1.0
Release:        1.1.pocketfed%{?dist}
Summary:        GSM 03.38 character codec for Python
License:        MIT
URL:            https://github.com/dsch/gsm0338
# Use the release archive rather than the PyPI sdist, which omits tests.
# v1.1.0 resolves to 86d6be13c1fac99a89fcb81247d88348e04aded9.
Source0:        %{url}/archive/refs/tags/v%{version}.tar.gz#/gsm0338-v%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  python3-pytest

%global _description %{expand:
A Python codec for the GSM 03.38 default alphabet and extension table.}

%description %_description

%package -n python3-gsm0338
Summary:        %{summary}

%description -n python3-gsm0338 %_description

%prep
%autosetup -n gsm0338-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files -l gsm0338

%check
%pytest

%files -n python3-gsm0338 -f %{pyproject_files}
%doc README.rst

%changelog
* Thu Sep 10 2026 PocketFed maintainers <me@samcday.com> - 1.1.0-1.1.pocketfed
- Initial package for the Qualcomm profile-manager trial
