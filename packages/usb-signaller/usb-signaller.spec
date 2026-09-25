# Adapted from rust2rpm 28 output for a local `cargo package` archive of the
# v0.4.2 tag; usb-signaller is not published on crates.io.
%bcond check 1

Name:           usb-signaller
Version:        0.4.2
Release:        %autorelease
Summary:        USB gadget mode daemon for mobile devices running mainline Linux

# usb-signaller itself is GPL-3.0-or-later. The binary statically links Rust
# crates; output of %%cargo_license_summary:
# (MIT OR Apache-2.0) AND Unicode-3.0
# AGPL-3.0-only
# Apache-2.0 OR MIT
# Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT
# GPL-3.0-or-later
# MIT
# MIT OR Apache-2.0
License:        GPL-3.0-or-later AND AGPL-3.0-only AND MIT AND (Apache-2.0 OR MIT) AND (Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT) AND Unicode-3.0
# LICENSE.dependencies contains a full license breakdown
URL:            https://codeberg.org/DylanVanAssche/usb-signaller
Source:         %{url}/archive/v%{version}.tar.gz#/%{name}-%{version}.tar.gz
# Bring the NCM interface down with ip(8) instead of net-tools' ifconfig.
# Prepared for upstream submission; not yet sent.
Patch:          0001-distro-scripts-use-ip-instead-of-ifconfig.patch

BuildRequires:  cargo-rpm-macros >= 24
BuildRequires:  systemd-rpm-macros

# D-Bus policy directory and a system bus for com.meego.usb_moded
Requires:       dbus
# modprobe@libcomposite.service
Requires:       kmod
# mount(8) and umount(8) for the MTP FunctionFS instance
Requires:       util-linux-core
# nmcli in the developer and tethering mode helpers
Requires:       NetworkManager
# ip(8) in the developer and tethering mode helpers
Requires:       iproute
# DHCP server started by the developer mode helper (unudhcpd@.service)
Requires:       unudhcpd

%description
usb-signaller manages the USB gadget of mobile devices that run mainline Linux
kernels. It switches between charging only, developer networking, tethering,
MTP and mass storage modes, detects cables through the USB Type-C class and
USB role switches, and implements the part of the usb-moded D-Bus interface
that clients use to query and change the USB mode.

MTP mode additionally needs an MTP responder daemon, which is not packaged
here.

%prep
%autosetup -n %{name} -p1
%cargo_prep

%generate_buildrequires
%cargo_generate_buildrequires

%build
%cargo_build
%{cargo_license_summary}
%{cargo_license} > LICENSE.dependencies

%install
%cargo_install
install -Dpm 0644 usb-signaller.service -t %{buildroot}%{_unitdir}
for mode in developer mtp tethering; do
    install -Dpm 0644 distro/systemd/usb-signaller-${mode}-mode.service \
        -t %{buildroot}%{_unitdir}
    install -Dpm 0755 distro/scripts/usb-signaller-${mode}-mode.sh \
        %{buildroot}%{_bindir}/usb-signaller-${mode}-mode
done
install -Dpm 0644 com.meego.usb_moded.conf \
    -t %{buildroot}%{_datadir}/dbus-1/system.d
# Vendor and administrator drop-in locations read through uapi-config
install -dm 0755 %{buildroot}%{_prefix}/lib/usb-signaller/usb-signaller.toml.d
install -dm 0755 %{buildroot}%{_sysconfdir}/usb-signaller/usb-signaller.toml.d

%if %{with check}
%check
# Gadget and UDC tests are #[ignore]d upstream: they need libcomposite,
# dummy_hcd and root (scripts/run-tests).
%cargo_test
%endif

%post
%systemd_post usb-signaller.service usb-signaller-developer-mode.service usb-signaller-mtp-mode.service usb-signaller-tethering-mode.service

%preun
%systemd_preun usb-signaller.service usb-signaller-developer-mode.service usb-signaller-mtp-mode.service usb-signaller-tethering-mode.service

%postun
# No restart on upgrade: stopping usb-signaller tears down the USB gadget,
# which may carry the session performing the upgrade. The mode units are
# started and stopped by usb-signaller itself.
%systemd_postun usb-signaller.service usb-signaller-developer-mode.service usb-signaller-mtp-mode.service usb-signaller-tethering-mode.service

%files
%license LICENSE
%license LICENSE.dependencies
%doc CHANGELOG.md
%doc README.md
%{_bindir}/usb-signaller
%{_bindir}/usb-signaller-developer-mode
%{_bindir}/usb-signaller-mtp-mode
%{_bindir}/usb-signaller-tethering-mode
%{_unitdir}/usb-signaller.service
%{_unitdir}/usb-signaller-developer-mode.service
%{_unitdir}/usb-signaller-mtp-mode.service
%{_unitdir}/usb-signaller-tethering-mode.service
%{_datadir}/dbus-1/system.d/com.meego.usb_moded.conf
%dir %{_prefix}/lib/usb-signaller
%dir %{_prefix}/lib/usb-signaller/usb-signaller.toml.d
%dir %{_sysconfdir}/usb-signaller
%dir %{_sysconfdir}/usb-signaller/usb-signaller.toml.d

%changelog
%autochangelog
