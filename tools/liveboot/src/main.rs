//! Build a PocketFed liveboot image from a device image's own Android boot image.
//!
//! Liveboot v2 does not generate a kernel or an initrd. It takes the `aboot.img`
//! the image builder already produced — the image's own kernel and its own dracut
//! initramfs, with the abl-exorcist shim already in place — and rewrites only the
//! kernel command line, so the phone runs exactly the kernel and initrd it would
//! have run from eMMC, with its root served over USB instead.

use std::{
    env,
    ffi::OsString,
    fs,
    io::Write,
    path::{Path, PathBuf},
    process::ExitCode,
    time::{SystemTime, UNIX_EPOCH},
};

use abl_exorcist_assembler::{bootimg, parse_ramdisk, rebuild_ramdisk};

mod cmdline;
mod cpio;
mod export_id;

use cmdline::LivebootCmdline;

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(err) => {
            eprintln!("pocketfed-liveboot: {err}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<(), String> {
    let mut args = env::args_os().skip(1);
    let command = args.next().ok_or_else(|| usage("missing command"))?;
    match command.to_str() {
        Some("boot") => run_boot(args),
        Some("-h") | Some("--help") => {
            println!("{}", usage_text());
            Ok(())
        }
        Some(other) => Err(usage(&format!("unknown command: {other}"))),
        None => Err(usage("command is not valid UTF-8")),
    }
}

struct BootArgs {
    aboot: PathBuf,
    output: PathBuf,
    export_id: u32,
    run_token: Option<String>,
    console: Option<String>,
    cow_size: Option<String>,
    extra: Vec<String>,
    inject_tree: Option<PathBuf>,
}

fn run_boot(mut args: impl Iterator<Item = OsString>) -> Result<(), String> {
    let mut aboot = None;
    let mut output = None;
    let mut export_id = None;
    let mut run_token = None;
    let mut console = None;
    let mut cow_size = None;
    let mut extra = Vec::new();
    let mut inject_tree = None;

    while let Some(arg) = args.next() {
        match arg.to_str() {
            Some("--aboot") => aboot = Some(PathBuf::from(take(&mut args, "--aboot")?)),
            Some("--output") => output = Some(PathBuf::from(take(&mut args, "--output")?)),
            Some("--export-id") => {
                export_id = Some(parse_export_id(&take(&mut args, "--export-id")?)?)
            }
            Some("--root-image") => {
                let path = PathBuf::from(take(&mut args, "--root-image")?);
                export_id = Some(
                    export_id::for_file(&path)
                        .map_err(|err| format!("--root-image {}: {err}", path.display()))?,
                );
            }
            Some("--run-token") => run_token = Some(string(take(&mut args, "--run-token")?)?),
            Some("--console") => console = Some(string(take(&mut args, "--console")?)?),
            Some("--cow-size") => cow_size = Some(string(take(&mut args, "--cow-size")?)?),
            Some("--append") => extra.push(string(take(&mut args, "--append")?)?),
            Some("--inject-tree") => {
                inject_tree = Some(PathBuf::from(take(&mut args, "--inject-tree")?))
            }
            Some(other) => return Err(usage(&format!("unexpected argument: {other}"))),
            None => return Err(usage("argument is not valid UTF-8")),
        }
    }

    let args = BootArgs {
        aboot: aboot.ok_or_else(|| usage("--aboot is required"))?,
        output: output.ok_or_else(|| usage("--output is required"))?,
        export_id: export_id.ok_or_else(|| usage("--root-image or --export-id is required"))?,
        run_token,
        console,
        cow_size,
        extra,
        inject_tree,
    };
    build(&args)
}

fn build(args: &BootArgs) -> Result<(), String> {
    // Writing over the template destroys the image builder's output, and it is
    // the one input a liveboot run cannot regenerate without rebuilding the
    // whole device image.
    if same_file(&args.aboot, &args.output) {
        return Err(format!(
            "--output would overwrite the boot image it reads: {}",
            args.aboot.display()
        ));
    }

    let template = read(&args.aboot)?;

    // Verify before touching it: a template that already fails its own integrity
    // checks would produce a liveboot image that fails on the device for reasons
    // that have nothing to do with liveboot.
    let parsed = bootimg::verify(&template)
        .map_err(|err| format!("{} is not a usable boot image: {err}", args.aboot.display()))?;

    let run_token = match &args.run_token {
        Some(token) => token.clone(),
        None => default_run_token(),
    };
    let mut opts = LivebootCmdline::new(args.export_id, run_token.clone());
    if let Some(console) = &args.console {
        opts.console = console.clone();
    }
    opts.cow_size = args.cow_size.clone();
    opts.extra = args.extra.clone();

    let cmdline = cmdline::apply(&parsed.cmdline, &opts);

    let injected = match &args.inject_tree {
        Some(tree) => Some(inject(&template, &parsed, tree)?),
        None => None,
    };

    let image = bootimg::repack(
        &template,
        &bootimg::Repack {
            kernel: None,
            ramdisk: injected.as_deref(),
            cmdline: Some(&cmdline),
            wrap_markers: true,
        },
    )
    .map_err(|err| format!("repack {}: {err}", args.aboot.display()))?;

    bootimg::verify(&image).map_err(|err| format!("the repacked image did not verify: {err}"))?;

    if let Some(parent) = args.output.parent() {
        fs::create_dir_all(parent).map_err(|err| format!("create {}: {err}", parent.display()))?;
    }
    write_output(&args.output, &image)?;

    println!("image: {}", args.output.display());
    println!("bytes: {}", image.len());
    println!("export_id: {}", args.export_id);
    println!("run_token: {run_token}");
    if let Some(tree) = &args.inject_tree {
        println!("injected: {}", tree.display());
    }
    println!("cmdline: {cmdline}");
    Ok(())
}

/// Append a directory tree to the boot image's initramfs as a second cpio
/// archive, and return the rebuilt ABLX ramdisk section.
///
/// The image's own initramfs is kept byte for byte: the kernel unpacks
/// concatenated archives in order and later entries win, so the injected files
/// land on top without the image's initrd being rebuilt or recompressed. That
/// matters because the whole point of liveboot is to run the image's own initrd
/// — rebuilding it would make the run evidence about the rebuild instead.
fn inject(template: &[u8], parsed: &bootimg::BootImage, tree: &Path) -> Result<Vec<u8>, String> {
    if !tree.is_dir() {
        return Err(format!(
            "--inject-tree is not a directory: {}",
            tree.display()
        ));
    }

    let container = &template[parsed.ramdisk.offset..parsed.ramdisk.offset + parsed.ramdisk.len];
    let ramdisk = parse_ramdisk(container).map_err(|err| {
        format!("the boot image's ramdisk is not an ABLX container, so there is nothing to inject into: {err}")
    })?;

    let entries = cpio::from_tree(tree).map_err(|err| format!("read {}: {err}", tree.display()))?;
    if entries.is_empty() {
        return Err(format!("--inject-tree is empty: {}", tree.display()));
    }

    let mut initrd = ramdisk.initrd.to_vec();
    append_archive(&mut initrd, &cpio::write(&entries));

    println!(
        "inject: {} entries, initrd {} -> {} bytes",
        entries.len(),
        ramdisk.initrd.len(),
        initrd.len()
    );
    rebuild_ramdisk(&ramdisk, &initrd).map_err(|err| format!("rebuild ABLX ramdisk: {err}"))
}

/// Append a cpio archive to an initrd image.
///
/// The kernel walks concatenated archives and only recognises an uncompressed
/// one that starts on a 4-byte boundary: after a compressed archive it skips
/// NUL bytes, then expects the `070701` magic at an aligned offset, and fails
/// the whole unpack with "invalid magic at start of compressed archive"
/// otherwise. A compressed initrd's length is arbitrary, so pad first.
fn append_archive(initrd: &mut Vec<u8>, archive: &[u8]) {
    let padding = initrd.len().next_multiple_of(4) - initrd.len();
    initrd.resize(initrd.len() + padding, 0);
    initrd.extend_from_slice(archive);
}

/// Whether two paths name the same existing file.
///
/// Compared after canonicalisation so `./boot.img` and an absolute path to it
/// are recognised as the same file. An output that does not exist yet cannot
/// collide, so a failure to canonicalise it means "different".
/// Write the image to `--output`, which must be a new path or a regular file.
///
/// The image is only ever handed to `fastboot boot`, so a block device here
/// is a slip (`/dev/sda` would be a disk wipe). The check is made on the open
/// handle rather than the path, and symlinks are not followed, so the file
/// cannot be swapped between the check and the write.
fn write_output(path: &Path, image: &[u8]) -> Result<(), String> {
    use std::os::unix::fs::{MetadataExt, OpenOptionsExt};

    let mut file = fs::OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(false)
        .custom_flags(O_NOFOLLOW)
        .open(path)
        .map_err(|err| format!("open {}: {err}", path.display()))?;
    let metadata = file
        .metadata()
        .map_err(|err| format!("stat {}: {err}", path.display()))?;
    if !metadata.is_file() {
        return Err(format!(
            "--output {} is not a regular file; refusing to write to it",
            path.display()
        ));
    }
    // Belt and braces for O_NOFOLLOW: the path itself must be that same
    // regular file, not a link to it.
    let on_disk =
        fs::symlink_metadata(path).map_err(|err| format!("stat {}: {err}", path.display()))?;
    if !on_disk.is_file() || (on_disk.dev(), on_disk.ino()) != (metadata.dev(), metadata.ino()) {
        return Err(format!(
            "--output {} is a link, not a file; refusing to write through it",
            path.display()
        ));
    }
    file.set_len(0)
        .and_then(|()| file.write_all(image))
        .and_then(|()| file.sync_all())
        .map_err(|err| format!("write {}: {err}", path.display()))
}

/// `O_NOFOLLOW` from asm-generic/fcntl.h, which every Linux architecture this
/// tool runs on shares; spelled out to avoid a libc dependency.
const O_NOFOLLOW: i32 = 0o400000;

fn same_file(left: &Path, right: &Path) -> bool {
    match (fs::canonicalize(left), fs::canonicalize(right)) {
        (Ok(left), Ok(right)) => left == right,
        _ => false,
    }
}

/// A token unique to this run, used to tell this boot's console output apart
/// from a stale capture of an earlier one.
fn default_run_token() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_nanos())
        .unwrap_or(0);
    format!("lb{nanos:x}")
}

fn parse_export_id(value: &OsString) -> Result<u32, String> {
    let value = string(value.clone())?;
    let parsed = match value
        .strip_prefix("0x")
        .or_else(|| value.strip_prefix("0X"))
    {
        Some(hex) => u32::from_str_radix(hex, 16),
        None => value.parse(),
    };
    parsed.map_err(|_| usage(&format!("--export-id must be a u32: {value}")))
}

fn take(args: &mut impl Iterator<Item = OsString>, flag: &str) -> Result<OsString, String> {
    args.next()
        .ok_or_else(|| usage(&format!("{flag} needs a value")))
}

fn string(value: OsString) -> Result<String, String> {
    value
        .into_string()
        .map_err(|_| usage("argument is not valid UTF-8"))
}

fn read(path: &Path) -> Result<Vec<u8>, String> {
    fs::read(path).map_err(|err| format!("read {}: {err}", path.display()))
}

fn usage(error: &str) -> String {
    format!("{error}\n{}", usage_text())
}

fn usage_text() -> &'static str {
    "usage: pocketfed-liveboot boot --aboot PATH --root-image PATH|--export-id ID --output PATH\n\
     \x20                          [--run-token TOKEN] [--console ttyMSM0,115200n8]\n\
     \x20                          [--cow-size 1G] [--append ARG]...\n\
     \x20                          [--inject-tree DIR]"
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn appended_archives_start_on_a_four_byte_boundary() {
        // The real sargo initrd is 25_779_059 bytes: 3 mod 4. That is exactly
        // the case the first hardware run failed on.
        for initrd_len in [0usize, 1, 2, 3, 4, 25_779_059 % 64] {
            let mut initrd = vec![0xffu8; initrd_len];
            append_archive(&mut initrd, b"070701rest");
            let magic = initrd.windows(6).position(|w| w == b"070701").unwrap();
            assert_eq!(magic % 4, 0, "initrd of {initrd_len} bytes");
            assert!(
                initrd[initrd_len..magic].iter().all(|b| *b == 0),
                "padding is NUL"
            );
            assert_eq!(&initrd[..initrd_len], vec![0xffu8; initrd_len].as_slice());
        }
    }

    #[test]
    fn output_may_be_new_or_a_regular_file_but_not_a_device_or_symlink() {
        let dir = std::env::temp_dir().join(format!("liveboot-out-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();

        write_output(&dir.join("new.img"), b"new").unwrap();
        assert_eq!(fs::read(dir.join("new.img")).unwrap(), b"new");

        fs::write(dir.join("old.img"), b"longer old contents").unwrap();
        write_output(&dir.join("old.img"), b"x").unwrap();
        assert_eq!(fs::read(dir.join("old.img")).unwrap(), b"x", "truncated");

        assert!(write_output(&dir, b"x").is_err(), "a directory");
        assert!(
            write_output(Path::new("/dev/null"), b"x").is_err(),
            "a device"
        );

        std::os::unix::fs::symlink(dir.join("old.img"), dir.join("link.img")).unwrap();
        assert!(
            write_output(&dir.join("link.img"), b"y").is_err(),
            "a symlink"
        );
        assert_eq!(
            fs::read(dir.join("old.img")).unwrap(),
            b"x",
            "target untouched"
        );

        fs::remove_dir_all(&dir).unwrap();
    }
}
