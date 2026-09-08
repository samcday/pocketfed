# US English Patricia dictionary provenance

Data repository: https://codeberg.org/Helium314/aosp-dictionaries
Pinned commit: 55e6d1c64ad72481d5615113b1c94f0716617016
Source: wordlists/main_en_US.combined
Upstream binary reference: dictionaries/main_en_us.dict
Dictionary revision: 54; source date: 2014-10-31; locale: en_US.

The repository's LICENSE contains GPL version 3. This package uses
GPL-3.0-only as the repository-wide terms; the English .source file lists no
separate license exception. That file identifies OpenBoard v1.4.5:
https://github.com/openboard-team/openboard/blob/v1.4.5/dictionaries/en_wordlist.combined.gz
The decompressed OpenBoard wordlist is byte-identical to this input (SHA-256
73308519ff089c73baa35e08f25087bb62ed4a6bf2f96af3efb402187f7c9edb).
OpenBoard v1.4.5 also supplies a GPL version 3 LICENSE. These are repository
license declarations, not an independently documented original corpus license.
No additional English-specific grant or notice was found in this source chain.
The source wordlist and full GPL text accompany the source RPM. This assessment
does not extend to other languages or the experimental dictionaries.

The build reproduces the published binary byte-for-byte (SHA-256
bd950ef4b57655120eee65cee62a5d216a63f721d9a8bb759ce2022437840443).
The source contains 160715 word entries, 481875 bigram records and 99 shortcut
records. It includes 1300 possibly_offensive markers. It is also identical to
the English fixture in patricia_dict commit cdab42d9b93a0b33070804b37098568c3a3227f8.

Build-only generator: Android Open Source Project LatinIME commit
a009d2c98da9749bf6ae4d92ef5fb3d3e945530f (android-4.3_r3.1):
https://android.googlesource.com/platform/packages/inputmethods/LatinIME/+/a009d2c98da9749bf6ae4d92ef5fb3d3e945530f/tools/dicttool/
Selected Java files carry Apache-2.0 headers. The full Apache license is
included with those sources. No precompiled JAR or native Android library is
used or installed. A small downstream patch carries possibly_offensive through
the static writer's bit-zero field without losing frequency. The wrapper
sets the v202 format header and verifies the entire output against the upstream
binary checksum. This generator is scoped to this pinned data, not installed
as a general conversion tool.

The Patricia Rust reader's author-confirmed GPL-3.0-only license is recorded
separately in packages/patricia/LICENSE-PROVENANCE.md. It was not used to infer
the dictionary data's terms.
