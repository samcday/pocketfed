# PocketFed Packages

Packaging for software that PocketFed needs before it exists in Fedora proper.

Image builds should consume packages from the `samcday/pocketfed` COPR instead
of building runtime components ad hoc during composition. Package sources should
stay as close as practical to Fedora-reviewable RPM packaging.

Kernel packaging is the exception that is not intended for Fedora review: it is
a temporary transport for the downstream PocketFed kernel branch until the image
can use Fedora's aarch64 kernel plus external modules and devicetrees.
