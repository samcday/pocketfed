# Drift Type documentation dependency

Fedora source package for `embed-doc-image` 0.1.4, the documentation image
macro required by Drift Type's `doc-images` feature. The crate is MIT licensed;
the upstream archive includes its license and copyright notice. The package
uses Fedora's Rust crate dependencies without vendoring.

The spec was generated with rust2rpm 28. Its small downstream patch corrects a
Markdown example's code fence and marks an illustrative Rust example ignored
because the published crate does not contain the images it references. The
remaining doctest passes. Drift Type's default and all-feature builds and tests
pass using this packaged macro, including its real documentation images.

Local Fedora Rawhide RPM and SRPM builds succeeded. `rpmlint` reports zero
errors and warnings. See [validation.json](validation.json) for the existing local build summary. These are build dependencies; installing them on the phone is not
necessary for the initial completion trial.

To rebuild in a Fedora build environment, download the source URL recorded in
[upstream.json](upstream.json), verify [sources.sha256](sources.sha256), and put
the crate archive and `embed-doc-image-doctests.patch` in the RPM source
directory. Build with `rpmbuild -ba rust-embed-doc-image.spec`; a clean builder
must first install its generated dynamic build requirements with
`rpmbuild -br` followed by `dnf builddep` on the resulting `.buildreqs.nosrc.rpm`.
Fedora build logs record the resolved dependency versions for each rebuild.
