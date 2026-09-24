use std::{
    fs,
    io::Write,
    os::unix::fs::PermissionsExt,
    path::{Component, Path, PathBuf},
    process::Command,
    time::Duration,
};

use anyhow::{Context, Result, anyhow, bail};
use clap::{Args, Parser, Subcommand};
use fastboop_core::{DeviceProfile, FastbootBoot, FastbootGetvarEq, ProbeStep};
use fastboop_environment_std::{
    NativeBootConfig, NativeBootEnvironment, NativeBootStage0Config, load_local_device_profiles,
    resolve_devpro_dirs,
};
use serde::{Deserialize, Serialize};
use serde_json::json;
use tokio_util::sync::CancellationToken;

const FASTBOOP_REV: &str = "1e6d64b3c375d46f2029122902f4564d36f5498b";

/// Kernel arguments that make the supplied initrd run Ignition on this boot.
const IGNITION_ARGS: &str = "ignition.firstboot ignition.platform.id=metal";

/// U-Boot and Pocketboot read only the Android header's first command-line
/// field; fastboop spills anything past 512 bytes into the second one.
const SAFE_CMDLINE_LEN: usize = 511;

#[derive(Parser)]
#[command(about = "PocketFed image preparation and native fastboop liveboot")]
struct Cli {
    #[command(subcommand)]
    command: Action,
}

#[derive(Subcommand)]
enum Action {
    /// Package separate boot inputs into a local, inspectable fastboop bundle. No USB access.
    Bundle(BundleArgs),
    /// Construct an Android payload through fastboop, without accessing USB.
    Image {
        bundle: PathBuf,
        #[arg(long)]
        output: PathBuf,
    },
    /// RAM-boot the selected device and keep serving its root through fastboop.
    Boot {
        bundle: PathBuf,
        #[arg(long, default_value_t = 30)]
        wait: u64,
    },
}

#[derive(Args)]
struct BundleArgs {
    /// Existing ext4 root image. Referenced read-only, never copied or modified.
    #[arg(long)]
    root_image: PathBuf,
    #[arg(long)]
    kernel: PathBuf,
    /// Prepared smoo-aware dracut initramfs, with matching device modules and COW support.
    #[arg(long)]
    initrd: PathBuf,
    #[arg(long)]
    dtb: PathBuf,
    /// fastboop DevPro YAML describing this device's boot geometry and probes.
    #[arg(long)]
    device_profile: PathBuf,
    /// Exact fastboot serial; added to the profile's read-only probes.
    #[arg(long)]
    serial: String,
    /// Image arguments, including OSTree deployment, filesystem type and COW size.
    /// fastboop owns root/export selection, COW enablement and USB interface arguments.
    #[arg(long)]
    cmdline_file: PathBuf,
    /// New output directory; existing directories are never overwritten.
    #[arg(long)]
    out: PathBuf,
    /// Raw device ABLX shim; composed by fastboop with the supplied kernel and initrd.
    #[arg(long)]
    shim: Option<PathBuf>,
    /// Mark an additional target as requiring --shim (Sargo is recognized automatically).
    #[arg(long)]
    requires_shim: bool,
    /// Match a supplied gadget that uses fastboot-style interface descriptors.
    #[arg(long, default_value_t = false, action = clap::ArgAction::Set)]
    impersonate_fastboot: bool,
    /// Ignition config to provision the guest with on this boot, embedded in the
    /// initrd as /etc/ignition/user.ign. The initrd must contain PocketFed's
    /// pocketfed-ignition dracut module. The bundle and its images then carry the
    /// config: treat them as secrets.
    #[arg(long)]
    ignition: Option<PathBuf>,
    /// Accept a kernel command line longer than 511 bytes, which only bootloaders
    /// reading the Android header's second command-line field will see whole.
    #[arg(long)]
    allow_long_cmdline: bool,
}

#[derive(Serialize, Deserialize)]
struct Bundle {
    fastboop_rev: String,
    device_profile: String,
    serial: String,
    requires_shim: bool,
    has_shim: bool,
    impersonate_fastboot: bool,
    #[serde(default)]
    ignition: bool,
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()),
        )
        .with_writer(std::io::stderr)
        .init();
    match Cli::parse().command {
        Action::Bundle(args) => bundle(args),
        Action::Image { bundle, output } => run(bundle, Some(output), 0).await,
        Action::Boot { bundle, wait } => run(bundle, None, wait).await,
    }
}

fn regular_file(path: &Path) -> Result<PathBuf> {
    let path = fs::canonicalize(path).with_context(|| format!("resolve {}", path.display()))?;
    if !fs::metadata(&path)?.is_file() {
        bail!("{} must be a regular file", path.display());
    }
    Ok(path)
}

fn bundle(args: BundleArgs) -> Result<()> {
    let root = regular_file(&args.root_image)?;
    let kernel = regular_file(&args.kernel)?;
    let initrd = regular_file(&args.initrd)?;
    let dtb = regular_file(&args.dtb)?;
    let shim = args.shim.as_deref().map(regular_file).transpose()?;
    let mut device: DeviceProfile = serde_yaml::from_slice(&fs::read(&args.device_profile)?)
        .context("parse fastboop device profile")?;
    if args.serial.trim().is_empty() {
        bail!("--serial must not be empty");
    }
    let dtb_name = PathBuf::from(format!("{}.dtb", device.devicetree_name));
    if device.devicetree_name.is_empty()
        || dtb_name
            .components()
            .any(|c| !matches!(c, Component::Normal(_)))
    {
        bail!("devicetree_name must be a relative path without '..'");
    }
    let cmdline_file = fs::read_to_string(&args.cmdline_file)?;
    let mut cmdline = cmdline_file.split_whitespace().collect::<Vec<_>>();
    let ignition = args.ignition.as_deref().map(ignition_config).transpose()?;
    if ignition.is_some() {
        if cmdline.iter().any(|arg| arg.starts_with("ignition.")) {
            bail!(
                "--ignition supplies the ignition.* arguments; remove them from the command line file"
            );
        }
        cmdline.push(IGNITION_ARGS);
    }
    let cmdline = cmdline.join(" ");
    let device_cmdline = device
        .boot
        .fastboot_boot
        .android_bootimg
        .cmdline_append
        .as_deref();
    // Validate the runtime contract before copying files or hashing the root. The
    // real export ID is computed by fastboop during preparation, never by us; the
    // largest one bounds the command-line length.
    let extra = fastboop_core::build_initrd_extra_cmdline(fastboop_core::InitrdCmdline {
        device: device_cmdline,
        profile: Some(&cmdline),
        requested: None,
        export_id: u32::MAX,
        mimic_fastboot: args.impersonate_fastboot,
    })
    .map_err(|e| anyhow!("invalid image command line: {e}"))?;
    let requires_shim = args.requires_shim || device.devicetree_name == "qcom/sdm670-google-sargo";
    let longest = [device_cmdline.unwrap_or_default(), &extra]
        .iter()
        .filter(|part| !part.is_empty())
        .map(|part| part.len() + 1)
        .sum::<usize>()
        .saturating_sub(1)
        + if requires_shim { "<S>  <E>".len() } else { 0 };
    if longest > SAFE_CMDLINE_LEN && !args.allow_long_cmdline {
        bail!(
            "the kernel command line can reach {longest} bytes; bootloaders reading only the first Android header field keep {SAFE_CMDLINE_LEN} (override with --allow-long-cmdline)"
        );
    }
    if let Some(parent) = args.out.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::create_dir(&args.out).context("--out must be a new directory")?;
    let out = fs::canonicalize(&args.out)?;
    if ignition.is_some() {
        fs::set_permissions(&out, fs::Permissions::from_mode(0o700))?;
    }
    if let Some(shim) = &shim {
        fs::copy(shim, out.join("shim.bin"))?;
    }
    let staging = tempfile::tempdir_in(&out)?;
    let staged_kernel = staging.path().join("kernel");
    let staged_initrd = staging.path().join("initrd");
    let staged_dtb = staging.path().join("dtbs").join(dtb_name);
    fs::copy(&kernel, &staged_kernel)?;
    fs::copy(&initrd, &staged_initrd)?;
    if let Some(config) = &ignition {
        append_ignition(&staged_initrd, config)?;
    }
    fs::create_dir_all(staged_dtb.parent().unwrap())?;
    fs::copy(&dtb, &staged_dtb)?;
    let bytes = [staged_kernel, staged_initrd, staged_dtb].iter().try_fold(
        32 * 1024 * 1024u64,
        |total, path| -> Result<u64> {
            total
                .checked_add(fs::metadata(path)?.len())
                .context("artifact size overflow")
        },
    )?;
    let artifacts = out.join("boot-artifacts.ext4");
    let status = Command::new("mkfs.ext4")
        .args(["-q", "-F", "-b", "4096", "-d"])
        .arg(staging.path())
        .arg(&artifacts)
        .arg(bytes.div_ceil(4096).to_string())
        .status()
        .context("run mkfs.ext4 (install e2fsprogs)")?;
    if !status.success() {
        bail!(
            "mkfs.ext4 failed: {status}; incomplete bundle at {}",
            out.display()
        );
    }
    // Namespace the bundled profile; run() rejects local overrides so they cannot
    // replace the exact-serial probe while fastboop handles USB selection.
    device.id = format!("pocketfed-{}", out.file_name().unwrap().to_string_lossy());
    device
        .probe
        .push(ProbeStep::FastbootGetvarEq(FastbootGetvarEq {
            name: "serialno".into(),
            equals: args.serial.clone(),
        }));
    let manifest = json!({
        "id": "pocketfed-liveboot", "boot": "initrd",
        "rootfs": {"ext4": {"file": root}},
        "kernel": {"path": "/kernel", "ext4": {"file": artifacts}},
        "initrd": {"path": "/initrd", "ext4": {"file": artifacts}},
        "dtbs": {"path": "/dtbs", "ext4": {"file": artifacts}},
        "extra_cmdline": cmdline,
    });
    let yaml = serde_yaml::to_string(&manifest)?;
    let compiled = fastboop_bootpro::compile_manifest_yaml(yaml.as_bytes())
        .context("compile supplied-initrd BootProfile")?;
    // Channels accept concatenated DevPro and BootPro records. Use their binary
    // codecs rather than serializing the human-readable YAML schema ourselves.
    let mut channel =
        fastboop_core::encode_dev_profile(&device).context("encode exact-serial DevPro")?;
    channel.extend_from_slice(&compiled.bytes);
    fs::write(out.join("profile.yaml"), yaml)?;
    fs::write(out.join("device.yaml"), serde_yaml::to_string(&device)?)?;
    fs::write(out.join("channel.fb"), channel)?;
    fs::write(
        out.join("bundle.json"),
        serde_json::to_vec_pretty(&Bundle {
            fastboop_rev: FASTBOOP_REV.into(),
            device_profile: device.id,
            serial: args.serial,
            requires_shim,
            has_shim: shim.is_some(),
            impersonate_fastboot: args.impersonate_fastboot,
            ignition: ignition.is_some(),
        })?,
    )?;
    println!("bundle: {}", out.display());
    if ignition.is_some() {
        println!(
            "the bundle, images made from it and fastboop's cache now contain the Ignition config"
        );
    }
    if requires_shim && shim.is_none() {
        println!("inputs prepared; supply --shim in a new bundle before image/boot");
    }
    Ok(())
}

/// Read an Ignition config and refuse what PocketFed's initrd would reject at
/// boot anyway: remote resources, kernel arguments and storage layout.
fn ignition_config(path: &Path) -> Result<Vec<u8>> {
    let bytes = fs::read(path).with_context(|| format!("read {}", path.display()))?;
    let config: serde_json::Value = serde_json::from_slice(&bytes)
        .context("--ignition must be an Ignition JSON config (render Butane first)")?;
    if !config["ignition"]["version"].is_string() {
        bail!("--ignition config has no ignition.version");
    }
    let mut remote = Vec::new();
    remote_sources(&config, &mut remote);
    if !remote.is_empty() {
        bail!(
            "--ignition config fetches remote resources, which PocketFed initrds cannot reach: {}",
            remote.join(", ")
        );
    }
    let mut unsupported = Vec::new();
    for field in ["shouldExist", "shouldNotExist"] {
        if !config["kernelArguments"][field]
            .as_array()
            .is_none_or(Vec::is_empty)
        {
            unsupported.push("kernelArguments".to_string());
            break;
        }
    }
    for section in ["disks", "filesystems", "luks", "raid"] {
        if !config["storage"][section]
            .as_array()
            .is_none_or(Vec::is_empty)
        {
            unsupported.push(format!("storage.{section}"));
        }
    }
    if !unsupported.is_empty() {
        bail!(
            "--ignition config uses sections PocketFed does not support: {}",
            unsupported.join(", ")
        );
    }
    Ok(bytes)
}

fn remote_sources(value: &serde_json::Value, found: &mut Vec<String>) {
    match value {
        serde_json::Value::Object(map) => {
            for (key, value) in map {
                match (key.as_str(), value.as_str()) {
                    ("source", Some(source))
                        if !source.is_empty() && !source.starts_with("data:") =>
                    {
                        found.push(
                            source
                                .split(['?', '#'])
                                .next()
                                .unwrap_or(source)
                                .to_string(),
                        )
                    }
                    _ => remote_sources(value, found),
                }
            }
        }
        serde_json::Value::Array(values) => values.iter().for_each(|v| remote_sources(v, found)),
        _ => {}
    }
}

/// Append the config as a second, uncompressed newc archive. The kernel unpacks
/// concatenated initramfs archives in order; an uncompressed one must start on a
/// 4-byte boundary, and a file is skipped unless its directory already exists.
fn append_ignition(initrd: &Path, config: &[u8]) -> Result<()> {
    fn entry(archive: &mut Vec<u8>, ino: u32, mode: u32, name: &str, data: &[u8]) {
        let fields = [
            ino,
            mode,
            0, // uid
            0, // gid
            1, // nlink
            0, // mtime
            data.len() as u32,
            0, // devmajor
            0, // devminor
            0, // rdevmajor
            0, // rdevminor
            name.len() as u32 + 1,
            0, // check
        ];
        archive.extend_from_slice(b"070701");
        for field in fields {
            archive.extend_from_slice(format!("{field:08X}").as_bytes());
        }
        archive.extend_from_slice(name.as_bytes());
        archive.push(0);
        archive.resize(archive.len().next_multiple_of(4), 0);
        archive.extend_from_slice(data);
        archive.resize(archive.len().next_multiple_of(4), 0);
    }
    u32::try_from(config.len()).context("Ignition config is too large for newc")?;
    let mut archive = Vec::new();
    // No etc entry: it would replace the initrd's own /etc mode.
    entry(&mut archive, 1, 0o040700, "etc/ignition", &[]);
    entry(&mut archive, 2, 0o100600, "etc/ignition/user.ign", config);
    entry(&mut archive, 0, 0, "TRAILER!!!", &[]);

    let mut file = fs::OpenOptions::new().append(true).open(initrd)?;
    let len = file.metadata()?.len();
    let padding = len.next_multiple_of(4) - len;
    file.write_all(&vec![0; padding as usize])?;
    file.write_all(&archive)?;
    Ok(())
}

async fn run(path: PathBuf, output: Option<PathBuf>, wait: u64) -> Result<()> {
    let path = fs::canonicalize(path)?;
    let bundle: Bundle = serde_json::from_slice(&fs::read(path.join("bundle.json"))?)?;
    if bundle.fastboop_rev != FASTBOOP_REV {
        bail!("bundle was made with another fastboop revision; regenerate it");
    }
    if bundle.requires_shim && !bundle.has_shim {
        bail!(
            "this target requires shim composition; regenerate the bundle with --shim pointing to its raw ABLX device shim"
        );
    }
    if load_local_device_profiles(&resolve_devpro_dirs()?)?.contains_key(&bundle.device_profile) {
        bail!(
            "a local fastboop DevPro shadows this bundle's device profile; remove the override before continuing"
        );
    }
    let mut stage0 = NativeBootStage0Config::from_raw_ostree(path.join("channel.fb"), None)?;
    stage0.device_profile = Some(bundle.device_profile);
    stage0.impersonate_fastboot = bundle.impersonate_fastboot;
    stage0.abl_exorcist = bundle.has_shim.then(|| path.join("shim.bin"));
    // Keep incomplete images private. The final publish is atomic and refuses
    // replacement even if another process creates the destination during preparation.
    let mut destination = output
        .as_ref()
        .map(|p| -> Result<tempfile::NamedTempFile> {
            match fs::symlink_metadata(p) {
                Ok(_) => bail!("output must be a new file: {}", p.display()),
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                Err(e) => return Err(e).context("inspect output path"),
            }
            let parent = p
                .parent()
                .filter(|p| !p.as_os_str().is_empty())
                .unwrap_or(Path::new("."));
            tempfile::NamedTempFile::new_in(parent).context("create temporary output")
        })
        .transpose()?;
    let shutdown = CancellationToken::new();
    let signal = shutdown.clone();
    let interrupt = tokio::spawn(async move {
        let _ = tokio::signal::ctrl_c().await;
        signal.cancel();
    });
    let mut env = NativeBootEnvironment::new(
        NativeBootConfig {
            stage0,
            boot_device: output.is_none(),
            system_time: false,
            systemd_firstboot: false,
            wait: Duration::from_secs(wait),
            smoo_metrics_port: 0,
        },
        shutdown.clone(),
    );
    let preparation = tokio::select! {
        result = env.prepare_boot() => result,
        _ = shutdown.cancelled() => Err(anyhow!("interrupted before boot")),
    };
    let result = async {
        let prepared = preparation?;
        if let Some(file) = destination.as_mut() {
            file.write_all(&prepared.boot_image)?;
            file.as_file().sync_all()?;
            destination
                .take()
                .unwrap()
                .persist_noclobber(output.as_ref().unwrap())
                .context("publish output without replacing an existing file")?;
            println!(
                "image: {} ({} bytes)",
                output.as_ref().unwrap().display(),
                prepared.boot_image.len()
            );
            return Ok(());
        }
        if shutdown.is_cancelled() {
            bail!("interrupted before boot");
        }
        let mut transport = env.connect_fastboot().await?;
        FastbootBoot::new(&prepared.boot_image)
            .run(&mut transport)
            .await
            .map_err(|e| anyhow!("fastboot RAM boot: {e}"))?;
        eprintln!(
            "Serving root for {}. Keep this process running until the guest is shut down.",
            bundle.serial
        );
        env.serve_runtime(prepared.export).await
    }
    .await;
    interrupt.abort();
    result
}
