Name:           feedbackd-device-themes
Version:        0.8.9
Release:        1%{?dist}
Summary:        Device-specific haptic and LED themes for feedbackd

License:        GPL-3.0-or-later
URL:            https://gitlab.freedesktop.org/feedbackd/feedbackd-device-themes
Source0:        %{url}/-/archive/v%{version}/%{name}-v%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  meson >= 1.7.0
BuildRequires:  /usr/bin/json-glib-validate
BuildRequires:  /usr/bin/fbd-theme-validate
Requires:       feedbackd >= 0.8.2

%description
Device-specific feedback themes adapt haptic and LED patterns to supported
phones, including Google Pixel 3a and OnePlus 6/6T. feedbackd selects the
matching theme automatically using the device-tree compatible string and
inherits other events from its standard theme.

%prep
%autosetup -n %{name}-v%{version}

%build
%meson -Dvalidate=enabled
%meson_build

%install
%meson_install

%check
%meson_test

%files
%license COPYING
%doc README.md NEWS
%{_datadir}/feedbackd/themes/*.json

%changelog
* Sun Sep 06 2026 Sam Day <me@samcday.com> - 0.8.9-1
- Package upstream device themes for PocketFed
