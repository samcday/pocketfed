%global commit c2fcf5e4b21c712d54e35a11da2ad9ad134fb821

Name:           lpac
Version:        2.3.0
Release:        1.1.pocketfed%{?dist}
Summary:        Local profile assistant for eSIM and eUICC cards

# libeuicc is used under its LGPL option, not its commercial alternative.
License:        AGPL-3.0-only AND LGPL-2.1-only AND MIT
URL:            https://github.com/estkme-group/lpac
# Upstream v2.3.0, pinned to its resolved commit rather than a movable tag.
Source0:        %{url}/archive/%{commit}/%{name}-%{version}.tar.gz
Source1:        SHA256SUMS
Source2:        README.pocketfed.md
# System cJSON/reproducible build support, QRTR lifecycle/mapping hardening,
# HTTPS verification, and hardware-independent regression tests.
Patch0:         lpac-2.3.0-pocketfed-hardening.patch

BuildRequires:  gcc
BuildRequires:  cmake
BuildRequires:  ninja-build
BuildRequires:  pkgconfig(libcjson) >= 1.7.15
BuildRequires:  pkgconfig(libcurl)
BuildRequires:  pkgconfig(libpcsclite)
BuildRequires:  pkgconfig(qmi-glib) >= 1.35.5
BuildRequires:  pkgconfig(qrtr-glib)
BuildRequires:  pkgconfig(mbim-glib)
BuildRequires:  python3
BuildRequires:  openssl
BuildRequires:  binutils
Requires:       ca-certificates
# PC/SC readers need the daemon; Qualcomm QRTR users do not.
Recommends:     pcsc-lite

%description
lpac implements a local profile assistant for consumer eSIM/eUICC cards.
It can inspect cards and profiles, download and manage profiles, and process
profile-management notifications. This build supports Qualcomm QMI-over-QRTR,
QMI device nodes, MBIM devices, AT-command modems, and PC/SC readers.

Managing an eSIM profile is separate from choosing the modem's active SIM
mapping. Operations that change either can interrupt cellular service.

%prep
(cd "%{_sourcedir}" && sha256sum --check --status "%{SOURCE1}")
%autosetup -n %{name}-%{commit} -p1
# Keep lpac's tiny cJSON extension, but never build or include bundled cJSON.
rm -v cjson/cJSON.c cjson/cJSON.h
cp -p "%{SOURCE2}" README.pocketfed.md

%build
%cmake -G Ninja \
    -DBUILD_TESTING=ON \
    -DLPAC_WITH_SYSTEM_CJSON=ON \
    -DLPAC_VERSION_OVERRIDE=v%{version}-%{release} \
    -DLPAC_DYNAMIC_LIBEUICC=OFF \
    -DLPAC_DYNAMIC_DRIVERS=OFF \
    -DLPAC_WITH_APDU_PCSC=ON \
    -DLPAC_WITH_APDU_AT=ON \
    -DLPAC_WITH_APDU_QMI=ON \
    -DLPAC_WITH_APDU_QMI_QRTR=ON \
    -DLPAC_WITH_APDU_MBIM=ON \
    -DLPAC_WITH_APDU_GBINDER=OFF \
    -DLPAC_WITH_HTTP_CURL=ON \
    -DCMAKE_SKIP_INSTALL_RPATH=ON
%cmake_build

%install
%cmake_install

%check
%ctest --no-tests=error
# These commands only enumerate compiled-in drivers and report the version;
# they do not connect to a card, modem, PC/SC daemon, or provisioning server.
LPAC_APDU=stdio LPAC_HTTP=stdio %{__cmake_builddir}/output/lpac driver list > drivers.json
python3 -c 'import json; d = json.load(open("drivers.json"))["payload"]; assert {"qmi_qrtr", "qmi", "mbim", "at", "pcsc"} <= set(d["LPAC_APDU"]); assert "curl" in d["LPAC_HTTP"]'
LPAC_APDU=stdio LPAC_HTTP=stdio %{__cmake_builddir}/output/lpac version > version.json
python3 -c 'import json; d = json.load(open("version.json")); assert d["payload"]["data"] == "v%{version}-%{release}"'
# A dynamic system cJSON dependency, not bundled parser code in the executable.
readelf -d %{buildroot}%{_bindir}/lpac | grep -F 'libcjson.so.'
! readelf -d %{buildroot}%{_bindir}/lpac | grep -E '\((RPATH|RUNPATH)\)'

%files
%license LICENSES/AGPL-3.0-only.txt LICENSES/LGPL-2.1-only.txt LICENSES/MIT.txt REUSE.toml cjson/LICENSE
%doc README.md README.pocketfed.md docs/USAGE.md
%{_bindir}/lpac

%changelog
* Wed Sep 09 2026 PocketFed maintainers - 2.3.0-1.1.pocketfed
- Initial Fedora packaging with system cJSON and explicit Qualcomm QRTR support
- Harden QRTR mapping and cleanup, enable verified HTTPS, add regression tests
