Name:           plymouth-theme-fedora-mobile
Version:        0.1.0
Release:        1%{?dist}
Summary:        Readable Plymouth boot theme for phones and tablets
License:        MIT
URL:            https://github.com/samcday/pocketfed
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  python3-pillow
BuildRequires:  fontconfig
BuildRequires:  font(cantarell)
Requires:       plymouth-plugin-two-step
Requires:       font(cantarell)
# The keyboard label atlas must match the installed Plymouth implementation.
# Share Fedora's maintained atlas instead of freezing a private copy of its ABI.
Requires:       plymouth-theme-spinner

%description
A quiet black canvas, a large blue orbit and clear typography for mobile
Fedora installations. Uses Plymouth's standard two-step plugin, including
password and question prompts, messages, update progress and display handoff.
It needs no GPU acceleration. Installation makes the theme available without
changing the system's selected theme or rebuilding any initramfs.

%prep
%autosetup

%build
%{python3} generate-assets.py assets

%install
install -d %{buildroot}%{_datadir}/plymouth/themes/fedora-mobile
install -pm0644 fedora-mobile.plymouth assets/*.png \
    %{buildroot}%{_datadir}/plymouth/themes/fedora-mobile/
ln -s ../spinner/keymap-render.png \
    %{buildroot}%{_datadir}/plymouth/themes/fedora-mobile/keymap-render.png

%check
%{python3} test-assets.py assets

%files
%license LICENSE
%doc README.md
%{_datadir}/plymouth/themes/fedora-mobile/

%changelog
* Fri Sep 11 2026 Sam Day <me@samcday.com> - 0.1.0-1
- Add a portrait-friendly theme using Plymouth's standard two-step plugin
