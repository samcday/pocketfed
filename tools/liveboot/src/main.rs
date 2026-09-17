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
    path::{Path, PathBuf},
    process::ExitCode,
    time::{SystemTime, UNIX_EPOCH},
};

use abl_exorcist_assembler::bootimg;

mod cmdline;

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
}

fn run_boot(mut args: impl Iterator<Item = OsString>) -> Result<(), String> {
    let mut aboot = None;
    let mut output = None;
    let mut export_id = None;
    let mut run_token = None;
    let mut console = None;
    let mut cow_size = None;
    let mut extra = Vec::new();

    while let Some(arg) = args.next() {
        match arg.to_str() {
            Some("--aboot") => aboot = Some(PathBuf::from(take(&mut args, "--aboot")?)),
            Some("--output") => output = Some(PathBuf::from(take(&mut args, "--output")?)),
            Some("--export-id") => {
                export_id = Some(parse_export_id(&take(&mut args, "--export-id")?)?)
            }
            Some("--run-token") => run_token = Some(string(take(&mut args, "--run-token")?)?),
            Some("--console") => console = Some(string(take(&mut args, "--console")?)?),
            Some("--cow-size") => cow_size = Some(string(take(&mut args, "--cow-size")?)?),
            Some("--append") => extra.push(string(take(&mut args, "--append")?)?),
            Some(other) => return Err(usage(&format!("unexpected argument: {other}"))),
            None => return Err(usage("argument is not valid UTF-8")),
        }
    }

    let args = BootArgs {
        aboot: aboot.ok_or_else(|| usage("--aboot is required"))?,
        output: output.ok_or_else(|| usage("--output is required"))?,
        export_id: export_id.ok_or_else(|| usage("--export-id is required"))?,
        run_token,
        console,
        cow_size,
        extra,
    };
    build(&args)
}

fn build(args: &BootArgs) -> Result<(), String> {
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
    let image = bootimg::repack(
        &template,
        &bootimg::Repack {
            kernel: None,
            ramdisk: None,
            cmdline: Some(&cmdline),
            wrap_markers: true,
        },
    )
    .map_err(|err| format!("repack {}: {err}", args.aboot.display()))?;

    bootimg::verify(&image).map_err(|err| format!("the repacked image did not verify: {err}"))?;

    if let Some(parent) = args.output.parent() {
        fs::create_dir_all(parent).map_err(|err| format!("create {}: {err}", parent.display()))?;
    }
    fs::write(&args.output, &image)
        .map_err(|err| format!("write {}: {err}", args.output.display()))?;

    println!("image: {}", args.output.display());
    println!("bytes: {}", image.len());
    println!("export_id: {}", args.export_id);
    println!("run_token: {run_token}");
    println!("cmdline: {cmdline}");
    Ok(())
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
    "usage: pocketfed-liveboot boot --aboot PATH --export-id ID --output PATH\n\
     \x20                          [--run-token TOKEN] [--console ttyMSM0,115200n8]\n\
     \x20                          [--cow-size 1G] [--append ARG]..."
}
