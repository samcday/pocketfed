Name:           feedbackd-device-themes
Version:        0.8.9
Release:        2%{?dist}
Summary:        Device-specific haptic and LED themes for feedbackd

License:        GPL-3.0-or-later
URL:            https://gitlab.freedesktop.org/feedbackd/feedbackd-device-themes
Source0:        https://sources.phosh.mobi/releases/%{name}/%{name}-%{version}.tar.xz
Source1:        https://sources.phosh.mobi/releases/%{name}/%{name}-%{version}.tar.xz.asc
# Upstream release-signing key: 0DB3932762F78E592F6522AFBB5A2C77584122D3
Source2:        https://sources.phosh.mobi/misc/signing-keys/signing-key-2025.asc
BuildArch:      noarch

BuildRequires:  openpgpverify
BuildRequires:  meson >= 1.7.0
BuildRequires:  /usr/bin/json-glib-validate
# feedbackd 0.8.4 introduced the keyboard events used by these themes.
BuildRequires:  feedbackd >= 0.8.4
Requires:       feedbackd >= 0.8.4

%description
Device-specific feedback themes adapt haptic and LED patterns to supported
phones, including Google Pixel 3a and OnePlus 6/6T. feedbackd selects the
matching theme automatically using the device-tree compatible string and
inherits other events from its standard theme.

%prep
%{openpgpverify} --keyring='%{SOURCE2}' --signature='%{SOURCE1}' --data='%{SOURCE0}'
%autosetup

%conf
%meson -Dvalidate=enabled

%build
%meson_build

%install
%meson_install

%check
export GSETTINGS_BACKEND=memory
%meson_test

%files
%license COPYING
%doc README.md NEWS
%{_datadir}/feedbackd/themes/*.json

%changelog
* Mon Sep 07 2026 Sam Day <me@samcday.com> - 0.8.9-2
- Verify signed upstream releases and prepare for Fedora review
- Require feedbackd with support for separate keyboard events

* Sun Sep 06 2026 Sam Day <me@samcday.com> - 0.8.9-1
- Package upstream device themes for PocketFed
