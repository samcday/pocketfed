//! Run the actual consumer against ext4 fixtures without USB, mounts or root.
use std::{
    fs,
    io::{Read, Write},
    os::unix::fs::symlink,
    path::PathBuf,
    process::{Command, Output, Stdio},
    time::{Duration, Instant},
};

use flate2::{Compression, read::GzDecoder, write::GzEncoder};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use tempfile::TempDir;

fn execute(mut command: Command, success: bool) -> Output {
    // Files keep a noisy child from blocking on a full pipe before the timeout.
    let stdout = tempfile::tempfile().unwrap();
    let stderr = tempfile::tempfile().unwrap();
    let mut child = command
        .stdin(Stdio::null())
        .stdout(stdout.try_clone().unwrap())
        .stderr(stderr.try_clone().unwrap())
        .spawn()
        .unwrap();
    let deadline = Instant::now() + Duration::from_secs(60);
    let status = loop {
        if let Some(status) = child.try_wait().unwrap() {
            break Some(status);
        }
        if Instant::now() >= deadline {
            break None;
        }
        std::thread::sleep(Duration::from_millis(20));
    };
    if status.is_none() {
        child.kill().unwrap();
        child.wait().unwrap();
    }
    fn read(mut file: fs::File) -> Vec<u8> {
        use std::io::{Seek, SeekFrom};
        file.seek(SeekFrom::Start(0)).unwrap();
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes).unwrap();
        bytes
    }
    let stdout = read(stdout);
    let stderr = read(stderr);
    assert!(status.is_some(), "command timed out: {command:?}");
    let output = Output {
        status: status.unwrap(),
        stdout,
        stderr,
    };
    assert_eq!(
        output.status.success(),
        success,
        "{command:?}\nstdout: {}\nstderr: {}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    output
}

struct Fixture {
    dir: TempDir,
    kernel: Vec<u8>,
    initrd: Vec<u8>,
    root_hash: Vec<u8>,
    profile: Value,
}

impl Fixture {
    fn new() -> Self {
        let dir = tempfile::tempdir().unwrap();
        let mut mkfs = Command::new("mkfs.ext4");
        mkfs.args(["-q", "-F", "-b", "4096"])
            .arg(dir.path().join("root.ext4"))
            .arg("4096");
        execute(mkfs, true);
        let root_hash = Sha256::digest(fs::read(dir.path().join("root.ext4")).unwrap()).to_vec();
        let mut kernel = b"synthetic arm64 kernel\0".repeat(4000);
        let size = kernel.len() as u64;
        kernel[..2].copy_from_slice(b"MZ");
        kernel[16..24].copy_from_slice(&size.to_le_bytes());
        kernel[56..60].copy_from_slice(b"ARM\x64");
        let mut gzip = GzEncoder::new(Vec::new(), Compression::default());
        gzip.write_all(b"opaque supplied initrd; never execute stage0")
            .unwrap();
        let initrd = gzip.finish().unwrap();
        fs::write(dir.path().join("Image"), &kernel).unwrap();
        fs::write(dir.path().join("initrd"), &initrd).unwrap();
        fs::write(
            dir.path().join("board.dts"),
            b"/dts-v1/; / { compatible = \"pocketfed,test\"; };",
        )
        .unwrap();
        let mut dtc = Command::new("dtc");
        dtc.args(["-I", "dts", "-O", "dtb", "-o"])
            .arg(dir.path().join("board.dtb"))
            .arg(dir.path().join("board.dts"));
        execute(dtc, true);
        let profile = json!({
            "id": "test-board", "display_name": "Synthetic test board",
            "devicetree_name": "test/board",
            "match": [{"fastboot": {"vid": 0x18d1, "pid": 0xd00d}}],
            "probe": [{"fastboot.getvar": "product", "equals": "test-board"}],
            "boot": {"fastboot_boot": {"android_bootimg": {
                "header_version": 2, "page_size": 4096, "base": 0x80000000u32,
                "kernel_offset": 0x80000, "ramdisk_offset": 0x1000000,
                "second_offset": 0, "tags_offset": 0x100, "dtb_offset": 0x2000000,
                "kernel": {"encoding": "image.gz"}, "cmdline_append": "console=ttyTEST0"
            }}}
        });
        let fixture = Self {
            dir,
            kernel,
            initrd,
            root_hash,
            profile,
        };
        fixture.save_profile();
        fs::write(
            fixture.path("cmdline"),
            "ostree=/ostree/boot.1/test/0 rootfstype=ext4 rd.smoo.cow.size=512M",
        )
        .unwrap();
        fixture
    }

    fn path(&self, name: &str) -> PathBuf {
        self.dir.path().join(name)
    }

    fn save_profile(&self) {
        fs::write(
            self.path("device.yaml"),
            serde_json::to_vec(&self.profile).unwrap(),
        )
        .unwrap();
    }

    fn cli(&self, args: &[&str], success: bool) -> Output {
        let mut command = Command::new(env!("CARGO_BIN_EXE_pocketfed-liveboot"));
        command
            .current_dir(self.dir.path())
            .args(args)
            .env("FASTBOOP_STAGE0_PATH", "/nonexistent-stage0")
            .env("FASTBOOP_SCHEMA_PATH", self.path("devpro"))
            .env("XDG_CONFIG_HOME", self.path("config"))
            .env("XDG_CACHE_HOME", self.path("cache"))
            .env("RUST_LOG", "warn");
        execute(command, success)
    }

    fn bundle(&self, extra: &[&str], success: bool) -> Output {
        let mut args = vec![
            "bundle",
            "--root-image",
            "root.ext4",
            "--kernel",
            "Image",
            "--initrd",
            "initrd",
            "--dtb",
            "board.dtb",
            "--device-profile",
            "device.yaml",
            "--serial",
            "TEST-SERIAL",
            "--cmdline-file",
            "cmdline",
            "--out",
            "bundle",
        ];
        args.extend_from_slice(extra);
        self.cli(&args, success)
    }

    fn image(&self) -> Vec<u8> {
        self.cli(&["image", "bundle", "--output", "boot.img"], true);
        fs::read(self.path("boot.img")).unwrap()
    }

    fn assert_root_unchanged(&self) {
        assert_eq!(
            Sha256::digest(fs::read(self.path("root.ext4")).unwrap()).as_slice(),
            self.root_hash
        );
    }
}

fn u32_at(bytes: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes(bytes[offset..offset + 4].try_into().unwrap())
}

fn u64_at(bytes: &[u8], offset: usize) -> u64 {
    u64::from_le_bytes(bytes[offset..offset + 8].try_into().unwrap())
}

fn gunzip(bytes: &[u8]) -> Vec<u8> {
    let mut decoded = Vec::new();
    GzDecoder::new(bytes).read_to_end(&mut decoded).unwrap();
    decoded
}

fn cmdline(image: &[u8]) -> String {
    let bytes: Vec<_> = [&image[64..576], &image[608..1632]]
        .into_iter()
        .flat_map(|field| field.iter().copied().take_while(|&byte| byte != 0))
        .collect();
    String::from_utf8(bytes).unwrap()
}

fn assert_error(output: Output, message: &str) {
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(stderr.contains(message), "{stderr}");
}

#[test]
fn separate_inputs_reach_fastboop_payload() {
    let fixture = Fixture::new();
    fixture.bundle(&[], true);
    let image = fixture.image();
    assert_eq!(&image[..8], b"ANDROID!");
    assert_eq!(u32_at(&image, 40), 2);
    assert_eq!(u32_at(&image, 36), 4096);
    assert_eq!(u32_at(&image, 12), 0x80080000);
    assert_eq!(u32_at(&image, 20), 0x81000000);
    assert_eq!(u64_at(&image, 1652), 0x82000000);
    let kernel_len = u32_at(&image, 8) as usize;
    let initrd_len = u32_at(&image, 16) as usize;
    let dtb_len = u32_at(&image, 1648) as usize;
    assert_eq!(gunzip(&image[4096..4096 + kernel_len]), fixture.kernel);
    let initrd_start = 4096 + kernel_len.div_ceil(4096) * 4096;
    assert_eq!(
        &image[initrd_start..initrd_start + initrd_len],
        fixture.initrd
    );
    let dtb_start = initrd_start + initrd_len.div_ceil(4096) * 4096;
    assert_eq!(
        &image[dtb_start..dtb_start + dtb_len],
        fs::read(fixture.path("board.dtb")).unwrap()
    );
    let cmdline = cmdline(&image);
    let args: Vec<_> = cmdline.split_whitespace().collect();
    for arg in [
        "console=ttyTEST0",
        "root=/dev/smoo-root",
        "rd.smoo=1",
        "rd.smoo.cow=1",
        "rd.smoo.force_root=1",
        "rd.smoo.mimic_fastboot=0",
        "rd.smoo.cow.size=512M",
        "ostree=/ostree/boot.1/test/0",
    ] {
        assert_eq!(
            args.iter().filter(|&&value| value == arg).count(),
            1,
            "{cmdline}"
        );
    }
    let exports: Vec<_> = args
        .iter()
        .filter_map(|arg| arg.strip_prefix("rd.smoo.root="))
        .collect();
    assert_eq!(exports.len(), 1);
    exports[0].parse::<u32>().unwrap();
    fixture.assert_root_unchanged();
    let device = fs::read_to_string(fixture.path("bundle/device.yaml")).unwrap();
    assert!(device.contains("fastboot.getvar: serialno"));
    assert!(device.contains("equals: TEST-SERIAL"));
}

#[test]
fn existing_outputs_are_not_overwritten() {
    let fixture = Fixture::new();
    fixture.bundle(&[], true);
    fixture.bundle(&[], false);
    fixture.cli(&["image", "bundle", "--output", "root.ext4"], false);
    symlink(fixture.path("root.ext4"), fixture.path("link.img")).unwrap();
    fixture.cli(&["image", "bundle", "--output", "link.img"], false);
    fixture.assert_root_unchanged();
}

#[test]
fn conflicting_contract_is_rejected_before_creating_bundle() {
    let fixture = Fixture::new();
    for arg in ["root=LABEL=pfroot", "rd.smoo.cow=0", "rd.smoo.root=7"] {
        fs::write(fixture.path("cmdline"), arg).unwrap();
        assert_error(fixture.bundle(&[], false), "invalid image command line");
        assert!(!fixture.path("bundle").exists());
    }
}

#[test]
fn shim_targets_stop_before_image_or_usb() {
    let mut fixture = Fixture::new();
    fixture.profile["devicetree_name"] = json!("qcom/sdm670-google-sargo");
    fixture.save_profile();
    fixture.bundle(&[], true);
    for args in [
        ["image", "bundle", "--output", "boot.img"],
        ["boot", "bundle", "--wait", "0"],
    ] {
        assert_error(fixture.cli(&args, false), "requires shim composition");
    }
    assert!(!fixture.path("boot.img").exists());
}

#[test]
fn profile_traversal_is_rejected() {
    let mut fixture = Fixture::new();
    fixture.profile["devicetree_name"] = json!("../escaped");
    fixture.save_profile();
    assert_error(fixture.bundle(&[], false), "relative path");
    assert!(!fixture.path("bundle").exists());
}

#[test]
fn supplied_shim_reaches_fastboop_ablx_composition() {
    let mut fixture = Fixture::new();
    let mut shim = vec![0x5a; 128];
    shim[16..24].copy_from_slice(&128u64.to_le_bytes());
    shim[56..60].copy_from_slice(b"ARM\x64");
    fs::write(fixture.path("shim"), &shim).unwrap();
    fixture.profile["devicetree_name"] = json!("qcom/sdm670-google-sargo");
    let geometry = &mut fixture.profile["boot"]["fastboot_boot"]["android_bootimg"];
    geometry["base"] = json!(0);
    geometry["ramdisk_offset"] = json!(0x04000000);
    fixture.save_profile();
    fixture.bundle(&["--shim", "shim"], true);
    assert_eq!(fs::read(fixture.path("bundle/shim.bin")).unwrap(), shim);
    let image = fixture.image();
    assert_eq!(u32_at(&image, 20), 0x04000000);
    let kernel_len = u32_at(&image, 8) as usize;
    assert_eq!(gunzip(&image[4096..4096 + kernel_len]), shim);
    let start = 4096 + kernel_len.div_ceil(4096) * 4096;
    let ramdisk = &image[start..start + u32_at(&image, 16) as usize];
    assert_eq!(&ramdisk[..8], b"ABLXRD1\0");
    assert_eq!(u32_at(ramdisk, 8), 72);
    assert_eq!(u32_at(ramdisk, 12), 2);
    let field = |offset| usize::try_from(u64_at(ramdisk, offset)).unwrap();
    assert_eq!(field(32), fixture.kernel.len());
    assert_eq!(field(56), fixture.initrd.len());
    assert_eq!(&ramdisk[field(48)..field(48) + field(56)], fixture.initrd);
    // The C liblz4 decoder is independent of fastboop's lz4_flex encoder.
    let compressed = &ramdisk[field(16)..field(16) + field(24)];
    let decoded = lz4::block::decompress(compressed, Some(field(32).try_into().unwrap())).unwrap();
    assert_eq!(decoded, fixture.kernel);
    let cmdline = cmdline(&image);
    assert!(cmdline.starts_with("<S> console=ttyTEST0 "), "{cmdline}");
    assert!(cmdline.ends_with(" <E>"), "{cmdline}");
    assert_eq!(cmdline.matches("<S>").count(), 1);
    assert_eq!(cmdline.matches("<E>").count(), 1);
    assert!(cmdline.contains("root=/dev/smoo-root"));
    assert!(cmdline.contains("rd.smoo.cow=1"));
    fixture.assert_root_unchanged();
}

#[test]
fn invalid_shim_does_not_produce_an_image() {
    let fixture = Fixture::new();
    fs::write(fixture.path("shim"), b"not a raw ARM64 shim").unwrap();
    fixture.bundle(&["--requires-shim", "--shim", "shim"], true);
    assert_error(
        fixture.cli(&["image", "bundle", "--output", "boot.img"], false),
        "prepare supplied initrd",
    );
    assert!(!fixture.path("boot.img").exists());
}

#[test]
fn local_profile_cannot_override_serial_probe() {
    let mut fixture = Fixture::new();
    fixture.bundle(&[], true);
    fs::create_dir(fixture.path("devpro")).unwrap();
    let metadata: Value =
        serde_json::from_slice(&fs::read(fixture.path("bundle/bundle.json")).unwrap()).unwrap();
    fixture.profile["id"] = metadata["device_profile"].clone();
    fs::write(
        fixture.path("devpro/override.yaml"),
        serde_json::to_vec(&fixture.profile).unwrap(),
    )
    .unwrap();
    assert_error(
        fixture.cli(&["image", "bundle", "--output", "boot.img"], false),
        "shadows this bundle",
    );
}

#[test]
fn failed_preparation_leaves_no_output() {
    let fixture = Fixture::new();
    fixture.bundle(&[], true);
    fs::remove_file(fixture.path("bundle/boot-artifacts.ext4")).unwrap();
    fixture.cli(&["image", "bundle", "--output", "boot.img"], false);
    assert!(!fixture.path("boot.img").exists());
    assert!(!fs::read_dir(fixture.dir.path()).unwrap().any(|entry| {
        entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .starts_with(".tmp")
    }));
}
