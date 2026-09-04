Name:           pocketfed-qmicli-pdc-fixed
Version:        1.36.0
Release:        %autorelease
Summary:        Patched qmicli for loading Qualcomm PDC configurations

License:        GPL-2.0-or-later
URL:            https://gitlab.freedesktop.org/mobile-broadband/libqmi
# This is the exact archive carried by libqmi-1.36.0-4.fc45.src.rpm. The
# upstream signed 1.36.0 tag resolves to defb13dcab0adc7f44f6741807244507a14a30c5.
Source0:        %{url}/-/archive/%{version}/libqmi-%{version}.tar.bz2
Source1:        test-pdc-load-ownership
# g_mapped_file_get_contents() returns storage owned by the mapped file. This
# one-line fix removes the invalid free added by upstream e7651c90.
Patch0:         0001-qmicli-pdc-do-not-free-mapped-file-contents.patch

BuildRequires:  binutils
BuildRequires:  gcc
BuildRequires:  glib2-devel >= 2.56
BuildRequires:  libqrtr-glib-devel
BuildRequires:  meson >= 0.53
BuildRequires:  python3

%description
This package contains a narrowly scoped qmicli build for provisioning Qualcomm
PDC modem configurations. It uses Fedora's system libqmi libraries and carries
only the ownership fix needed to make --pdc-load-config reliable. It does not
replace Fedora's qmicli or any libqmi library.

%prep
%autosetup -n libqmi-%{version} -p1

%build
%meson \
    -Dbash_completion=false \
    -Dcollection=full \
    -Dfirmware_update=false \
    -Dgtk_doc=false \
    -Dintrospection=false \
    -Dman=false \
    -Dmbim_qmux=false \
    -Dmm_runtime_check=false \
    -Dqrtr=true \
    -Drmnet=false \
    -Dudev=false
%meson_build

%install
# A staged Meson install strips the build-tree RUNPATH. Retain only the
# standalone CLI so all libqmi libraries continue to come from Fedora.
stage="$PWD/pocketfed-stage"
DESTDIR="$stage" meson install -C %{_vpath_builddir} --no-rebuild
install -Dpm0755 \
    "$stage%{_bindir}/qmicli" \
    %{buildroot}%{_libexecdir}/pocketfed-qmicli-pdc

%check
%meson_test
%{SOURCE1} src/qmicli/qmicli-pdc.c
LD_LIBRARY_PATH="$PWD/pocketfed-stage%{_libdir}" \
    %{buildroot}%{_libexecdir}/pocketfed-qmicli-pdc --version | \
    grep -Fq 'qmicli %{version}'
if readelf -d %{buildroot}%{_libexecdir}/pocketfed-qmicli-pdc | \
        grep -Eq '(RPATH|RUNPATH)'; then
    echo 'pocketfed-qmicli-pdc retains a build-tree library search path' >&2
    exit 1
fi

%files
%license COPYING
%{_libexecdir}/pocketfed-qmicli-pdc

%changelog
%autochangelog
