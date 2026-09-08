%global crate verbisage
%global commit 97aabc197c4e08555bb716f910f614c7c6e601aa
%global shortcommit 97aabc1
%global patricia_commit cdab42d9b93a0b33070804b37098568c3a3227f8
%global cargo_install_lib 0

Name:           verbisage
Version:        0.1.0
Release:        1.2.pocketfed%{?dist}
Summary:        Dictionary completion and prediction service

# Source declares MIT OR Apache-2.0. Select Apache-2.0 for Verbisage;
# the linked Patricia reader is GPL-3.0-only. Remaining selectable dependency
# expressions from %%cargo_license_summary all permit MIT; Unicode-3.0 also
# applies. LICENSE.dependencies preserves the complete generated breakdown.
License:        GPL-3.0-only AND Apache-2.0 AND MIT AND Unicode-3.0
URL:            https://gitlab.com/InsanePrawn/verbisage
# Curated, deterministic repack of the pinned source. See prepare-sources;
# bundled RPMs, language models, planning notes and chat logs are excluded.
Source0:        %{name}-%{version}-%{shortcommit}.tar.xz
Source1:        %{name}-%{version}-%{shortcommit}-vendor.tar.xz
Source2:        org.verbisage.Dictionary.service
Source3:        verbisage.toml
Source4:        LICENSE-APACHE
Source5:        test-dbus.py
# Identical Rust to pinned upstream, with author-confirmed GPL-3.0-only
# metadata and license text applied downstream. See LICENSE-PROVENANCE.md.
Source6:        pocketfed-patricia-rust-gpl3-%{patricia_commit}.tar.gz
Source7:        collect-notices.py
Source8:        README.md
Source9:        verbisage.1
Source10:       verbisaged.1
Patch0:         verbisage-pocketfed-integration.patch

BuildRequires:  cargo-rpm-macros >= 28
BuildRequires:  cargo
BuildRequires:  rust
BuildRequires:  gcc
BuildRequires:  pkgconfig(sqlite3)
BuildRequires:  dbus-daemon
BuildRequires:  python3
BuildRequires:  python3-gobject-base
Requires:       android-patricia-dictionaries-en-US
Provides:       verbisage-dbus-query-limited = 1
Provides:       verbisage-dbus-complete = 1
# The separate path dependency is outside the registry vendor manifest.
Provides:       bundled(crate(patricia_dict)) = 0.1.0

%description
Verbisage serves word completion, spelling suggestions and prediction over the
session D-Bus. This build uses Android Patricia dictionaries and retains the
optional Presage SQLite backend. It includes a command-line client and starts
on demand. The system dictionary is read-only; user learning is not enabled.

%prep
%autosetup -n %{name}-%{version} -p1
%{__tar} -xf %{SOURCE1}
%{__tar} -xf %{SOURCE6}
cp -p %{SOURCE4} LICENSE-APACHE
cp -p %{SOURCE8} README.packaging.md
%cargo_prep -v vendor

%build
%cargo_build -n -f sqlite,dbus,patricia -- --locked --bins
%cargo_license_summary -n -f sqlite,dbus,patricia
%{cargo_license -n -f sqlite,dbus,patricia} > LICENSE.dependencies
# cargo2rpm currently rewrites slashes in local dependency paths as license ORs.
sed -i '/^GPL-3.0-only: patricia_dict /s/ (.*)$//' LICENSE.dependencies
%cargo_vendor_manifest
%{__python3} %{SOURCE7}
./target/release/verbisage-introspect org.verbisage.Dictionary.xml

%install
install -Dpm0755 target/release/verbisage %{buildroot}%{_bindir}/verbisage
install -Dpm0755 target/release/verbisaged %{buildroot}%{_bindir}/verbisaged
install -Dpm0644 %{SOURCE2} %{buildroot}%{_datadir}/dbus-1/services/org.verbisage.Dictionary.service
install -Dpm0644 org.verbisage.Dictionary.xml %{buildroot}%{_datadir}/dbus-1/interfaces/org.verbisage.Dictionary.xml
install -Dpm0644 %{SOURCE3} %{buildroot}%{_sysconfdir}/verbisage/config.toml
install -Dpm0644 %{SOURCE9} %{buildroot}%{_mandir}/man1/verbisage.1
install -Dpm0644 %{SOURCE10} %{buildroot}%{_mandir}/man1/verbisaged.1

%check
%cargo_test -n -f sqlite,dbus,patricia -- --locked
dbus-run-session -- %{__python3} %{SOURCE5} --daemon "$PWD/target/release/verbisaged"
test -x %{buildroot}%{_bindir}/verbisaged
grep -Fq 'name="QueryLimited"' org.verbisage.Dictionary.xml
grep -Fq 'name="Complete"' org.verbisage.Dictionary.xml

%files
%license LICENSE-APACHE Cargo.toml LICENSE.dependencies cargo-vendor.txt LICENSE.vendor
%license patricia_dict/COPYING patricia_dict/LICENSE-PROVENANCE.md
%doc README.packaging.md
%{_bindir}/verbisage
%{_bindir}/verbisaged
%{_mandir}/man1/verbisage.1*
%{_mandir}/man1/verbisaged.1*
%{_datadir}/dbus-1/services/org.verbisage.Dictionary.service
%{_datadir}/dbus-1/interfaces/org.verbisage.Dictionary.xml
%dir %{_sysconfdir}/verbisage
%config(noreplace) %{_sysconfdir}/verbisage/config.toml

%changelog
* Mon Sep 07 2026 Sam Day <me@samcday.com> - 0.1.0-1.2.pocketfed
- Rank current-word prefixes and typo candidates in a single bounded Complete call.
- Keep literal SQLite patterns and explicit stdio transport independent of config.
- Add client/daemon manual pages and Patricia bundled-component metadata.

* Mon Sep 07 2026 Sam Day <me@samcday.com> - 0.1.0-1.1.pocketfed
- Add the Patricia dictionary backend and bounded session D-Bus completion API.
