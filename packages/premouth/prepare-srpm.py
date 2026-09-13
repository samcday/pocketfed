#!/usr/bin/python3
"""Prepare deterministic SRPM inputs for the premouth RPM package.

Snapshot the allowlisted tools/premouth crate, vendor its locked
dependencies into a separate archive, and lay out an rpmbuild
SOURCES/SPECS tree with a SHA256 manifest and a source provenance
record. rpmbuild is never invoked; Cargo reaches the network only
when --offline is omitted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import tomllib

NAME = "premouth"
VERSION = "0.1.0"
RELEASE = "1.pocketfed"
PREFIX = f"{NAME}-{VERSION}"
SOURCE_ARCHIVE = f"{PREFIX}.tar.xz"
VENDOR_ARCHIVE = f"{PREFIX}-vendor.tar.xz"
CRATE_FILES = ("Cargo.toml", "Cargo.lock", "README.md", "DESIGN.md",
               "LICENSE-MIT", "LICENSE-APACHE")
CRATE_DIRS = ("src", "integration")
PACKAGE_FILES = ("premouth.spec", "collect-notices.py", "test-notify.py",
                 "README.md", "drm-fourcc-LICENSE", "prepare-srpm.py")
SCRIPT = Path(os.path.abspath(__file__))
PACKAGE = SCRIPT.parent
REPOSITORY = PACKAGE.parents[1]
CRATE = REPOSITORY / "tools" / NAME


def digest(path):
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def captured(*command, cwd=None, env=None):
    completed = subprocess.run(command, check=True, cwd=cwd, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True)
    return completed.stdout


def git(repository, *arguments):
    try:
        return captured("git", "-C", str(repository), *arguments)
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or f"exit {error.returncode}"
        raise SystemExit(f"error: git {arguments[0]} failed: {detail}") from error
    except OSError as error:
        raise SystemExit(f"error: unable to run git: {error}") from error


def within(path, directory):
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def require_regular(path, kind):
    if path.is_symlink():
        raise SystemExit(f"error: refusing symlink {path}")
    if not path.is_file():
        raise SystemExit(f"error: missing {kind} {path}")


def require_directory(path, kind):
    if path.is_symlink():
        raise SystemExit(f"error: refusing symlink {path}")
    if not path.is_dir():
        raise SystemExit(f"error: missing {kind} {path}")


def replicate(source, destination):
    if source.is_symlink():
        raise SystemExit(f"error: refusing symlink {source}")
    if source.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        for child in sorted(source.iterdir()):
            replicate(child, destination / child.name)
        return "0755"
    if not source.is_file():
        raise SystemExit(f"error: refusing special file {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    mode = 0o755 if source.stat().st_mode & 0o111 else 0o644
    destination.chmod(mode)
    return f"{mode:04o}"


def walk(root, relative=Path()):
    with os.scandir(root) as scanner:
        entries = sorted(scanner, key=lambda candidate: candidate.name)
    for entry in entries:
        path = Path(entry.path)
        current = relative / entry.name
        if entry.is_symlink():
            raise SystemExit(f"error: refusing symlink {path}")
        if entry.is_dir(follow_symlinks=False):
            yield current, True, path
            yield from walk(path, current)
        elif entry.is_file(follow_symlinks=False):
            yield current, False, path
        else:
            raise SystemExit(f"error: refusing special file {path}")


def snapshot_files(root, prefix, skip=()):
    hashes = {}
    modes = {}
    for relative, is_directory, path in walk(root):
        if is_directory or relative.parts[0] in skip:
            continue
        name = f"{prefix.rstrip('/')}/{relative}"
        status = path.stat()
        hashes[name] = digest(path)
        modes[name] = "0755" if status.st_mode & 0o111 else "0644"
    return hashes, modes


def archive_tree(root, destination, prefix):
    prefix = prefix.rstrip("/")
    if root.is_symlink() or not root.is_dir():
        raise SystemExit(f"error: refusing symlink or non-directory archive root {root}")
    with tarfile.open(destination, "w:xz", preset=3) as archive:
        root_info = tarfile.TarInfo(prefix + "/")
        root_info.type = tarfile.DIRTYPE
        root_info.mode = 0o755
        root_info.uid = root_info.gid = 0
        root_info.uname = root_info.gname = ""
        root_info.mtime = 0
        archive.addfile(root_info)
        for relative, is_directory, path in walk(root):
            name = f"{prefix}/{relative}"
            info = tarfile.TarInfo(name + "/" if is_directory else name)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            if is_directory:
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.size = 0
                archive.addfile(info)
            else:
                status = path.stat()
                info.type = tarfile.REGTYPE
                info.mode = 0o755 if status.st_mode & 0o111 else 0o644
                info.size = status.st_size
                with path.open("rb") as handle:
                    archive.addfile(info, handle)


def cargo_version(cargo, env):
    try:
        return captured(cargo, "--version", env=env).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path,
                        help="fresh directory to receive the SOURCES/ and SPECS/ tree")
    parser.add_argument("--offline", action="store_true",
                        help="pass --offline to cargo vendor and use only the local cache")
    parser.add_argument("--cargo", default="cargo",
                        help="cargo executable to run for vendoring (default: cargo)")
    parser.add_argument("--cargo-home", type=Path,
                        help="CARGO_HOME for vendoring; Cargo's default is kept when omitted")
    args = parser.parse_args()

    # Refuse any existing path, including a dangling symlink, before resolving
    # it so --output link-to-nonexistent-target cannot create the target.
    if args.output.is_symlink() or args.output.exists():
        raise SystemExit(f"error: refusing existing output {args.output}")
    output = args.output.resolve()
    if within(output, CRATE.resolve()):
        raise SystemExit(f"error: output {output} is inside the crate source {CRATE}")

    # A path-like --cargo is relative to the invocation directory; the vendor
    # step later runs from the temporary source copy.
    cargo = args.cargo
    if os.path.dirname(cargo) or cargo.startswith("~"):
        cargo = os.path.abspath(os.path.expanduser(cargo))
    cargo_home = args.cargo_home.resolve() if args.cargo_home else None

    require_directory(PACKAGE, "package directory")
    require_directory(CRATE, "crate directory")
    for name in CRATE_FILES:
        require_regular(CRATE / name, "crate file")
    for name in CRATE_DIRS:
        require_directory(CRATE / name, "crate directory")
    for name in PACKAGE_FILES:
        require_regular(PACKAGE / name, "package file")

    manifest_path = CRATE / "Cargo.toml"
    try:
        declared = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise SystemExit(f"error: cannot read {manifest_path}: {error}") from error
    declared_package = declared.get("package", {})
    if (declared_package.get("name") != NAME
            or declared_package.get("version") != VERSION):
        raise SystemExit(f"error: {manifest_path} declares "
                         f"{declared_package.get('name')} {declared_package.get('version')}, "
                         f"expected {NAME} {VERSION}")

    try:
        repository = REPOSITORY.resolve()
        crate_path = str(CRATE.resolve().relative_to(repository))
        package_path = str(PACKAGE.resolve().relative_to(repository))
    except ValueError as error:
        raise SystemExit(f"error: {PACKAGE} is not below {REPOSITORY}") from error
    head = git(REPOSITORY, "rev-parse", "HEAD").strip()
    # Scoped status only: unrelated repository state must not leak in.
    status = git(REPOSITORY, "status", "--porcelain=v1", "--untracked-files=all",
                 "--", crate_path, package_path)
    status_lines = status.splitlines()

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise SystemExit(f"error: cannot create {output.parent}: {error}") from error
    staging = Path(tempfile.mkdtemp(prefix=f".{PREFIX}-srpm-", dir=output.parent))
    os.chmod(staging, 0o755)
    try:
        sources = staging / "SOURCES"
        specs = staging / "SPECS"
        sources.mkdir()
        specs.mkdir()

        environment = os.environ.copy()
        if cargo_home is not None:
            environment["CARGO_HOME"] = str(cargo_home)

        with tempfile.TemporaryDirectory(prefix=f".{PREFIX}-work-", dir=staging) as work:
            # Vendor from a snapshot copy so the archives cannot silently
            # differ from the recorded hashes if the checkout is edited.
            snapshot = Path(work) / PREFIX
            snapshot.mkdir()
            for name in CRATE_FILES:
                replicate(CRATE / name, snapshot / name)
            for name in CRATE_DIRS:
                replicate(CRATE / name, snapshot / name)

            frozen_manifest = snapshot / "Cargo.toml"
            try:
                frozen = tomllib.loads(frozen_manifest.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
                raise SystemExit(f"error: cannot read frozen {frozen_manifest}: {error}") from error
            frozen_package = frozen.get("package", {})
            if (frozen_package.get("name") != NAME
                    or frozen_package.get("version") != VERSION):
                raise SystemExit(f"error: frozen Cargo.toml does not declare {NAME} {VERSION}")
            if not (snapshot / "Cargo.lock").is_file():
                raise SystemExit("error: frozen snapshot is missing Cargo.lock")

            source_files, source_modes = snapshot_files(snapshot, PREFIX)
            archive_tree(snapshot, sources / SOURCE_ARCHIVE, PREFIX + "/")
            recheck_files, recheck_modes = snapshot_files(snapshot, PREFIX)
            if recheck_files != source_files or recheck_modes != source_modes:
                raise SystemExit("error: crate source changed while archiving")

            vendor_command = [cargo, "vendor", "--locked", "--versioned-dirs"]
            if args.offline:
                vendor_command.append("--offline")
            vendor_command.append("vendor")
            lock_before = digest(snapshot / "Cargo.lock")
            try:
                subprocess.run(vendor_command, check=True, cwd=snapshot, env=environment,
                               stdout=subprocess.DEVNULL)
            except OSError as error:
                raise SystemExit(f"error: cannot run {cargo}: {error}") from error
            except subprocess.CalledProcessError as error:
                raise SystemExit(f"error: cargo vendor exited {error.returncode}") from error
            lock_after = digest(snapshot / "Cargo.lock")
            if lock_after != lock_before:
                raise SystemExit("error: cargo vendor modified Cargo.lock")
            vendor_root = snapshot / "vendor"
            if vendor_root.is_symlink() or not vendor_root.is_dir():
                raise SystemExit("error: cargo vendor produced an unusable vendor/ directory")
            vendored_files, vendored_modes = snapshot_files(snapshot, PREFIX, skip=("vendor",))
            if vendored_files != source_files or vendored_modes != source_modes:
                raise SystemExit("error: crate source changed while vendoring")
            archive_tree(vendor_root, sources / VENDOR_ARCHIVE, "vendor/")
            crates = sorted(path.parent.name for path in vendor_root.glob("*/Cargo.toml"))

            inputs = {}
            modes = {}
            for name in PACKAGE_FILES:
                location = (specs if name.endswith(".spec") else sources) / name
                mode = replicate(PACKAGE / name, location)
                relative = str(location.relative_to(staging))
                inputs[relative] = digest(location)
                modes[relative] = mode

            source_archive = digest(sources / SOURCE_ARCHIVE)
            vendor_archive = digest(sources / VENDOR_ARCHIVE)
            provenance = {
                "package": NAME,
                "version": VERSION,
                "release": RELEASE,
                "source": {
                    "path": crate_path,
                    "git_head": head,
                    "scoped_dirty": bool(status_lines),
                    "scoped_status": status_lines,
                },
                "source_files": source_files,
                "source_modes": source_modes,
                "package_inputs": inputs,
                "package_modes": modes,
                "archives": {
                    "source": {"name": SOURCE_ARCHIVE, "sha256": source_archive},
                    "vendor": {"name": VENDOR_ARCHIVE, "sha256": vendor_archive,
                               "crates": crates},
                },
                "vendor": {
                    "command": vendor_command,
                    "offline": bool(args.offline),
                    "cargo_version": cargo_version(cargo, environment),
                    "cargo_home": "explicit" if cargo_home else "default",
                    "cargo_lock_sha256_before": lock_before,
                    "cargo_lock_sha256_after": lock_after,
                },
            }
            provenance_path = sources / "provenance.json"
            provenance_path.write_text(
                json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            manifest = dict(inputs)
            manifest[f"SOURCES/{SOURCE_ARCHIVE}"] = source_archive
            manifest[f"SOURCES/{VENDOR_ARCHIVE}"] = vendor_archive
            manifest["SOURCES/provenance.json"] = digest(provenance_path)
            report = "".join(f"{manifest[path]}  {path}\n" for path in sorted(manifest))
            (sources / "sources.sha256").write_text(report, encoding="utf-8")

        if (args.output.is_symlink() or args.output.exists()
                or output.is_symlink() or output.exists()):
            raise SystemExit(f"error: refusing existing output {args.output}")
        try:
            os.rename(staging, output)
        except OSError as error:
            raise SystemExit(f"error: cannot move prepared tree to {output}: {error}") from error
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    print(f"Prepared rpmbuild tree in {output}")
    print((output / "SOURCES" / "sources.sha256").read_text(encoding="utf-8"), end="")


if __name__ == "__main__":
    main()
