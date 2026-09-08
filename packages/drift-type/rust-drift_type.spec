# Adapted from rust2rpm 28 output for the pinned, metadata-corrected crate.
%bcond check 1
%global debug_package %{nil}
%global crate drift_type
%global commit f63256a5bb973b10a4e11e190cfbb105fc89da0a
%global shortcommit f63256a

Name:           rust-drift_type
Version:        0.0.0
Release:        0.1.20260904git%{shortcommit}%{?dist}
Summary:        Gesture typing library for on-screen keyboards

License:        Apache-2.0
URL:            https://codeberg.org/eclexic/drift_type
Source0:        %{url}/archive/%{commit}.tar.gz#/%{crate}-%{commit}.tar.gz
# Correct a license-file value that names an SPDX identifier, not a file.
Patch0:         drift_type-license-metadata.patch

BuildRequires:  cargo-rpm-macros >= 26

%global _description %{expand:
Drift Type resolves touch gestures against keyboard geometry, candidate word
dictionaries and language-model scores. Applications provide input handling,
text composition and their own dictionary data. This is an experimental API.}

%description %{_description}

%package devel
Summary:        %{summary}
BuildArch:      noarch

%description devel %{_description}

This package contains library source for building applications that use the
drift_type crate.

%files devel
%license %{crate_instdir}/LICENSE
%doc %{crate_instdir}/CONTRIBUTING.md
%doc %{crate_instdir}/README.md
%{crate_instdir}/

%package -n %{name}+default-devel
Summary:        Default feature of the drift_type crate
BuildArch:      noarch

%description -n %{name}+default-devel
This package contains metadata for the default feature of drift_type.

%files -n %{name}+default-devel
%ghost %{crate_instdir}/Cargo.toml

%package -n %{name}+doc-images-devel
Summary:        Embedded documentation images for the drift_type crate
BuildArch:      noarch

%description -n %{name}+doc-images-devel
This package contains metadata for the doc-images feature of drift_type.

%files -n %{name}+doc-images-devel
%ghost %{crate_instdir}/Cargo.toml

%prep
%autosetup -n %{crate} -p1
%cargo_prep

%generate_buildrequires
%cargo_generate_buildrequires -a

%build
%cargo_build -a

%install
%cargo_install -a

%if %{with check}
%check
%cargo_test
%cargo_test -a
%endif

%changelog
* Mon Sep 07 2026 Sam Day <me@samcday.com> - 0.0.0-0.1.20260904gitf63256a
- Package pinned experimental gesture library for PocketFed integration work
- Correct Cargo license metadata without changing the upstream license
