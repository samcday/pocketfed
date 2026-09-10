Name:           python-statemachine
Version:        2.6.0
Release:        1.1.pocketfed%{?dist}
Summary:        Synchronous and asynchronous finite state machines for Python
License:        MIT
URL:            https://github.com/fgmacedo/python-statemachine
Source0:        %{pypi_source python_statemachine}
# pytest 9 removed the legacy py.path hook argument; test-only compatibility.
Patch0:         0001-pytest9-collection-hook.patch
BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  python3-pytest
BuildRequires:  python3-pytest-asyncio
BuildRequires:  python3-pytest-mock
BuildRequires:  python3-pytest-benchmark
BuildRequires:  python3-pydot
BuildRequires:  graphviz

%global _description %{expand:
Declarative finite state machines with states, transitions, callbacks,
validators and synchronous or asyncio execution engines.}

%description %_description

%package -n python3-statemachine
Summary:        %{summary}

%description -n python3-statemachine %_description

%prep
%autosetup -n python_statemachine-%{version} -p1

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files -l statemachine

%check
# No coverage/debugger/benchmark output, and no optional Django integration.
%pytest -o addopts= --benchmark-disable --ignore=tests/django_project tests

%files -n python3-statemachine -f %{pyproject_files}
%doc README.md

%changelog
* Thu Sep 10 2026 PocketFed maintainers <me@samcday.com> - 2.6.0-1.1.pocketfed
- Initial package including upstream synchronous and asyncio tests
