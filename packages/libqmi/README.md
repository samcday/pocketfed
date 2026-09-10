# libqmi introspection backport

Fedora `libqmi-1.36.0-4.fc45` packaging, with release bumped to
`4.1.pocketfed` and upstream commit
[`082bf3454c011e1481375e843a0c91c9e338d422`](https://gitlab.freedesktop.org/mobile-broadband/libqmi/-/commit/082bf3454c011e1481375e843a0c91c9e338d422)
backported. The change supplies missing element-type annotations for nested
GArray fields; there is no C ABI change or modem-specific runtime patch.

This fixes the Python UIM/PDC array failures reproduced during the
[profile-manager trial](../qcom-baseband-profile-manager/README.md).
`%check` runs upstream's Meson tests and checks generated introspection metadata
for the affected byte arrays. The source archive is Fedora's existing payload,
with its digest recorded in `sources.sha256`.
