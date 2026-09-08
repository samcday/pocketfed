# English Patricia dictionary package

`android-patricia-dictionaries-en-US` installs the normal US English dictionary
from the pinned Helium314/aosp-dictionaries collection at
`/usr/share/android-patricia-dictionaries/en_US.dict`. The data is reusable by
Verbisage or another Patricia reader. It does not enable a keyboard by itself.

The build compiles a small, pinned AOSP Java generator from source and
recreates the exact published dictionary. The downstream v202 patch preserves
all 1,300 possibly-offensive flags; the build verifies the complete binary
SHA-256 before installing it. The source archive contains the editable
wordlist, and the source RPM includes the generator source and patch. Neither
a precompiled JAR nor an Android SDK is required.

See [PROVENANCE.md](PROVENANCE.md) for the separate dictionary and generator
license evidence, source chain and scope. The repository-wide GPL3 license is
the data package's current basis. The English source file names OpenBoard
v1.4.5 but supplies no separate original-corpus license notice. That distinction
is recorded for Fedora review instead of treating an application license as
an independent corpus grant. Other languages require separate review.

## Reproduce

On Fedora install `rpm-build`, `java-latest-openjdk-devel`, `python3` and
`patch`. From the repository root:

```sh
packages/keyboard-dictionaries/prepare-sources \
  --cache-dir /tmp/keyboard-dictionary-inputs \
  --output-dir /tmp/keyboard-dictionary-sources
cp packages/keyboard-dictionaries/{PROVENANCE.md,build-dictionary,dicttool-v202-offensive.patch} \
  /tmp/keyboard-dictionary-sources/
rpmbuild -ba \
  --define '_topdir /tmp/keyboard-dictionary-rpmbuild' \
  --define '_sourcedir /tmp/keyboard-dictionary-sources' \
  packages/keyboard-dictionaries/android-patricia-dictionaries.spec
```

The preparation script checks every fetched input against `inputs.json`.
`--offline` uses the cache without network access. Repeating preparation into
a new output directory produces the hashes in `sources.sha256`.

The local Rawhide x86_64 builder produced the noarch RPM and source RPM, with
source/binary checks passing. Repeated source preparation produced identical
archives. `validation.json` summarizes build checks and local artifact hashes.
See [publication scope](../keyboard-trial/README.md) for the main COPR and image
selection boundaries.
