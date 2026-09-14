Name:           megapixels
Version:        2.1.0
Release:        5%{?dist}
Summary:        Camera application for phones with raw image processing
License:        GPL-3.0-or-later
URL:            https://gitlab.com/megapixels-org/Megapixels
%global commit 5fb1f24f1aeef80ea18224ab5829fda85653a4e8
Source0:        https://gitlab.com/megapixels-org/megapixels/-/archive/%{version}/%{name}-%{version}.tar.gz
Source1:        test-calibration-lookup.py
Source2:        calibration-lookup-fixture.c
Source3:        test-blank-capture-buffers.py
Source4:        blank-capture-buffers-fixture.c
Source5:        test-control-requests.py
Source6:        control-requests-fixture.c
Source7:        test-empty-dequeue.py
Source8:        empty-dequeue-fixture.c
Source9:        test-capture-state.py
Source10:       capture-state-fixture.c
Source11:       test-stream-generation.py
Source12:       stream-generation-fixture.c
Source13:       test-dng-neutral.py
Source14:       dng-neutral-fixture.c
Patch0:         0001-fix-prerelease-metadata-ordering.patch
Patch1:         0002-fix-calibration-lookup.patch
Patch2:         0003-requeue-blank-capture-buffers.patch
Patch3:         0004-fix-software-control-requests.patch
Patch4:         0005-skip-empty-buffer-dequeues.patch
Patch5:         0006-publish-capture-burst-state.patch
Patch6:         0007-reject-stale-stream-buffer-returns.patch
Patch7:         0008-store-reciprocal-dng-white-balance.patch

# Based on Fedora's 1.8.3 package, updated for the upstream 2.x libraries.
ExcludeArch:    %{ix86} armv7hl
BuildRequires:  gcc
BuildRequires:  meson
BuildRequires:  gperf
BuildRequires:  python3
BuildRequires:  desktop-file-utils
BuildRequires:  libappstream-glib
BuildRequires:  pkgconfig(gtk4)
BuildRequires:  pkgconfig(libfeedback-0.0)
BuildRequires:  pkgconfig(zbar)
BuildRequires:  pkgconfig(epoxy)
BuildRequires:  pkgconfig(libjpeg)
BuildRequires:  pkgconfig(libpulse-simple)
BuildRequires:  pkgconfig(wayland-client)
BuildRequires:  pkgconfig(x11)
BuildRequires:  pkgconfig(xrandr)
BuildRequires:  pkgconfig(libmegapixels) >= 1.0.0
BuildRequires:  pkgconfig(libdng) >= 1.1.0
Requires:       hicolor-icon-theme
# The bundled postprocessor needs both raw conversion and JPEG encoding.
Requires:       dcraw
Requires:       ImageMagick
Requires:       perl-Image-ExifTool
Requires:       python3

%description
Megapixels is a GTK camera application for phones. It configures V4L2 media
pipelines through libmegapixels, previews raw sensor frames, provides manual
exposure and focus controls, and saves processed photographs and DNG originals.

%prep
%autosetup -p1 -n Megapixels-%{version}-%{commit}

%build
%meson
%meson_build

%install
%meson_install

%check
python3 %{SOURCE1} src/dcp.c
python3 %{SOURCE3} src/io_pipeline.c
python3 %{SOURCE5} .
python3 %{SOURCE7} .
python3 %{SOURCE9} .
python3 %{SOURCE11} .
python3 %{SOURCE13} src/process_pipeline.c
desktop-file-validate %{buildroot}%{_datadir}/applications/*.desktop
appstream-util validate-relax --nonet %{buildroot}%{_datadir}/metainfo/*.metainfo.xml
glib-compile-schemas --strict --dry-run %{buildroot}%{_datadir}/glib-2.0/schemas
sh -n %{buildroot}%{_datadir}/megapixels/postprocess.sh

%files
%license LICENSE
%doc README.md
%{_bindir}/megapixels
%{_libexecdir}/megapixels/
%{_datadir}/applications/me.gapixels.Megapixels.desktop
%{_datadir}/icons/hicolor/scalable/apps/me.gapixels.Megapixels.svg
%dir %{_datadir}/megapixels
%dir %{_datadir}/megapixels/config
%{_datadir}/megapixels/config/*.dcp
%{_datadir}/megapixels/postprocess.sh
%{_datadir}/megapixels/movie.sh
%{_datadir}/metainfo/me.gapixels.Megapixels.metainfo.xml
%{_datadir}/glib-2.0/schemas/me.gapixels.Megapixels.gschema.xml

%changelog
* Thu Sep 10 2026 Sam Day <me@samcday.com> - 2.1.0-5
- Store reciprocal white-balance correction gains in DNG AsShotNeutral

* Thu Sep 10 2026 Sam Day <me@samcday.com> - 2.1.0-4
- Publish the capture burst state before asking the processing thread to capture
- Reject delayed buffer returns from stopped or replaced capture streams

* Thu Sep 10 2026 Sam Day <me@samcday.com> - 2.1.0-3
- Do not dispatch a frame callback when a nonblocking dequeue returns EAGAIN

* Thu Sep 10 2026 Sam Day <me@samcday.com> - 2.1.0-2
- Return blank capture buffers instead of exhausting the camera queue
- Preserve observed sensor values during software exposure and manual control

* Thu Sep 10 2026 Sam Day <me@samcday.com> - 2.1.0-1
- Update Fedora packaging to the current upstream camera stack
- Require JPEG postprocessing tools and preserve metadata
- Correct calibration lookup when the device has no DCP profile
