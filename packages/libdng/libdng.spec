Name:           libdng
Version:        0.2.2
Release:        1%{?dist}
Summary:        Read and write Digital Negative images with libtiff
License:        MIT
URL:            https://gitlab.com/megapixels-org/libdng
# Tag resolves to 438df53ee06d9f21202e0398c90a9c3bf9e86591.
Source0:        %{url}/-/archive/%{version}/%{name}-%{version}.tar.gz
BuildRequires:  gcc
BuildRequires:  meson
BuildRequires:  pkgconfig(libtiff-4)
BuildRequires:  pkgconfig(scdoc)

%description
Libdng provides a small interface for storing raw camera frames and their
metadata in Digital Negative files, including packed Bayer formats and stride.

%package devel
Summary:        Development files for libdng
Requires:       %{name}%{?_isa} = %{version}-%{release}

%description devel
Headers and pkg-config metadata for developing applications using libdng.

%package tools
Summary:        Digital Negative image utilities
Requires:       %{name}%{?_isa} = %{version}-%{release}

%description tools
Utilities to generate and inspect Digital Negative images.

%prep
%autosetup

%build
%meson -Dman-pages=enabled
%meson_build

%install
%meson_install

%check
%meson_test

%files
%license LICENSE
%doc README.md
%{_libdir}/libdng.so.1*

%files devel
%{_includedir}/libdng.h
%{_libdir}/libdng.so
%{_libdir}/pkgconfig/libdng.pc

%files tools
%{_bindir}/makedng
%{_bindir}/dumpdng
%{_mandir}/man1/makedng.1*

%changelog
* Thu Sep 10 2026 Sam Day <me@samcday.com> - 0.2.2-1
- Package the upstream release for Megapixels 2
