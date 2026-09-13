use std::fs::{self, OpenOptions};
use std::io;
use std::os::fd::AsRawFd;
use std::path::Path;
use std::ptr;

use crate::devicetree::CaptureGeometry;
use crate::image::{Frame, FrameOrigin};
use crate::pacing::monotonic_ns;

#[derive(Debug)]
pub struct CaptureReport {
    pub frame: Frame,
    pub provenance: String,
    pub copy_start_ns: u64,
    pub copy_end_ns: u64,
}

#[derive(Debug)]
pub enum CaptureFailure {
    YieldRequested { provenance: String },
    Failed { message: String, provenance: String },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct MappingPlan {
    pub map_offset: u64,
    pub map_len: usize,
    pub copy_delta: usize,
    pub visible_span: usize,
}

pub fn plan_mapping(base: u64, span: usize, page_size: usize) -> Result<MappingPlan, String> {
    if page_size == 0 || !page_size.is_power_of_two() {
        return Err(format!("invalid page size {page_size}"));
    }
    if span == 0 {
        return Err("zero visible span".to_string());
    }
    if base % 4 != 0 {
        return Err(format!("base {base:#x} is not 4-aligned for u32 loads"));
    }
    let page = page_size as u64;
    let delta = base % page;
    let map_offset = base - delta;
    let map_len_u64 = (span as u64)
        .checked_add(delta)
        .ok_or_else(|| "mapping length overflow".to_string())?;
    if map_len_u64 > i64::MAX as u64 {
        return Err("mapping length exceeds off_t".to_string());
    }
    if map_offset > i64::MAX as u64 {
        return Err("mapping offset exceeds off_t".to_string());
    }
    let map_len =
        usize::try_from(map_len_u64).map_err(|_| "mapping length exceeds usize".to_string())?;
    let copy_delta = usize::try_from(delta).map_err(|_| "copy delta exceeds usize".to_string())?;
    Ok(MappingPlan {
        map_offset,
        map_len,
        copy_delta,
        visible_span: span,
    })
}

#[derive(Default)]
pub struct Provenance {
    lines: Vec<(String, String)>,
}

impl Provenance {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn set(&mut self, key: &str, value: impl std::fmt::Display) {
        self.lines.push((key.to_string(), value.to_string()));
    }

    pub fn render(&self) -> String {
        let mut out = String::new();
        for (k, v) in &self.lines {
            out.push_str(k);
            out.push('=');
            out.push_str(v);
            out.push('\n');
        }
        out
    }
}

pub fn capture_readonly(
    geo: &CaptureGeometry,
    dt_description: &str,
    tick: &mut dyn FnMut() -> bool,
) -> Result<CaptureReport, CaptureFailure> {
    let mut prov = Provenance::new();
    prov.set("method", "readonly-mmap-volatile-u32");
    prov.set("device", "/dev/mem");
    prov.set("dt_description", dt_description);
    prov.set("dt_width", geo.width.to_string());
    prov.set("dt_height", geo.height.to_string());
    prov.set("dt_stride", geo.stride.to_string());
    prov.set("dt_format", geo.format.name());
    prov.set("reserved_base", format!("{:#x}", geo.base));
    prov.set("reserved_size", format!("{:#x}", geo.region_size));
    prov.set("boot_id", read_trim("/proc/sys/kernel/random/boot_id"));
    prov.set("kernel_release", read_trim("/proc/sys/kernel/osrelease"));
    prov.set("cmdline", read_trim("/proc/cmdline"));
    prov.set("lockdown", read_trim("/sys/kernel/security/lockdown"));
    prov.set(
        "dmesg_restrict",
        read_trim("/proc/sys/kernel/dmesg_restrict"),
    );

    if tick() {
        prov.set("result", "yield-requested-before-capture");
        return Err(CaptureFailure::YieldRequested {
            provenance: prov.render(),
        });
    }

    let page_size = page_size();
    prov.set("page_size", page_size.to_string());
    let plan = match plan_mapping(geo.base, geo.span, page_size) {
        Ok(plan) => plan,
        Err(e) => {
            return Err(fail(
                prov,
                "mapping-plan",
                io::Error::new(io::ErrorKind::InvalidInput, e),
            ))
        }
    };
    prov.set("visible_span", plan.visible_span.to_string());
    prov.set("map_offset", format!("{:#x}", plan.map_offset));
    prov.set("map_len", plan.map_len.to_string());
    prov.set("copy_delta", plan.copy_delta.to_string());

    let file = match OpenOptions::new().read(true).open("/dev/mem") {
        Ok(f) => f,
        Err(e) => return Err(fail(prov, "open-devmem", e)),
    };
    let fd = file.as_raw_fd();
    let map_ptr = unsafe {
        libc::mmap(
            ptr::null_mut(),
            plan.map_len,
            libc::PROT_READ,
            libc::MAP_SHARED,
            fd,
            plan.map_offset as libc::off_t,
        )
    };
    if map_ptr == libc::MAP_FAILED {
        return Err(fail(prov, "mmap-devmem", std::io::Error::last_os_error()));
    }
    let base = map_ptr as *const u8;
    let mut bytes = vec![0u8; geo.span];
    let copy_start = monotonic_ns();
    let stride = geo.stride;
    let words = stride / 4;
    let mut yielded = false;
    let mut rows_copied = 0u32;
    for y in 0..geo.height as usize {
        if y % 64 == 0 && tick() {
            yielded = true;
            break;
        }
        let src = unsafe { base.add(plan.copy_delta + y * stride) } as *const u32;
        let dst = &mut bytes[y * stride..(y + 1) * stride];
        for w in 0..words {
            let value = unsafe { ptr::read_volatile(src.add(w)) };
            dst[w * 4..w * 4 + 4].copy_from_slice(&value.to_ne_bytes());
        }
        rows_copied += 1;
    }
    let copy_end = monotonic_ns();
    let unmap_result = unsafe { libc::munmap(map_ptr, plan.map_len) };
    if unmap_result != 0 {
        prov.set("unmap_error", std::io::Error::last_os_error().to_string());
    }
    prov.set("copy_start_ns", copy_start.to_string());
    prov.set("copy_end_ns", copy_end.to_string());
    prov.set("rows_copied", rows_copied.to_string());
    if yielded {
        prov.set("result", "yield-requested-during-copy");
        return Err(CaptureFailure::YieldRequested {
            provenance: prov.render(),
        });
    }
    prov.set("content_fnv1a64", format!("{:016x}", fnv1a64(&bytes)));
    let frame = match Frame::new(
        geo.width,
        geo.height,
        geo.stride,
        geo.format,
        FrameOrigin::DevmemCapture,
        dt_description.to_string(),
        bytes,
    ) {
        Ok(f) => f,
        Err(e) => return Err(fail(prov, "validate-frame", io::Error::other(e))),
    };
    prov.set("result", "captured");
    Ok(CaptureReport {
        frame,
        provenance: prov.render(),
        copy_start_ns: copy_start,
        copy_end_ns: copy_end,
    })
}

fn page_size() -> usize {
    let v = unsafe { libc::sysconf(libc::_SC_PAGESIZE) };
    if v > 0 {
        v as usize
    } else {
        4096
    }
}

fn read_trim(path: &str) -> String {
    fs::read_to_string(path)
        .map(|s| s.trim().to_string())
        .unwrap_or_else(|_| "unavailable".to_string())
}

pub fn fnv1a64(data: &[u8]) -> u64 {
    let mut hash = 0xcbf2_9ce4_8422_2325u64;
    for b in data {
        hash ^= *b as u64;
        hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
    }
    hash
}

fn fail(prov: Provenance, stage: &str, err: std::io::Error) -> CaptureFailure {
    let message = format!("{stage}: {err}");
    let mut prov = prov;
    prov.set("result", "failed");
    prov.set("failure_stage", stage);
    prov.set("failure_message", err.to_string());
    CaptureFailure::Failed {
        message,
        provenance: prov.render(),
    }
}

pub fn write_provenance(path: &Path, provenance: &str) -> Result<(), String> {
    fs::write(path, provenance).map_err(|e| format!("write {}: {e}", path.display()))
}

pub fn save_probe_dir(dir: &Path, frame: &Frame, provenance: &str) -> Result<(), String> {
    fs::create_dir_all(dir).map_err(|e| format!("create {}: {e}", dir.display()))?;
    write_provenance(&dir.join("provenance.txt"), provenance)?;
    fs::write(dir.join("frame.raw"), frame.bytes()).map_err(|e| format!("write frame.raw: {e}"))?;
    let ppm = crate::image::encode_ppm(frame);
    fs::write(dir.join("frame.ppm"), ppm).map_err(|e| format!("write frame.ppm: {e}"))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    const SARGO_BASE: u64 = 0x9c00_0000;
    const SARGO_SPAN: usize = 4320 * 2220;

    #[test]
    fn fnv_hash_is_stable() {
        assert_eq!(fnv1a64(b""), 0xcbf2_9ce4_8422_2325);
        assert_eq!(fnv1a64(b"a"), 0xaf63_dc4c_8601_ec8c);
        assert_ne!(fnv1a64(b"premouth"), fnv1a64(b"premoutn"));
    }

    #[test]
    fn provenance_renders_key_values() {
        let mut p = Provenance::new();
        p.set("a", "1");
        p.set("b", 2);
        assert_eq!(p.render(), "a=1\nb=2\n");
    }

    #[test]
    fn mapping_plan_for_page_aligned_sargo_base() {
        let plan = plan_mapping(SARGO_BASE, SARGO_SPAN, 4096).unwrap();
        assert_eq!(plan.map_offset, SARGO_BASE);
        assert_eq!(plan.copy_delta, 0);
        assert_eq!(plan.map_len, SARGO_SPAN);
        assert_eq!(plan.visible_span, SARGO_SPAN);
        assert_eq!(plan.map_offset % 4096, 0);
    }

    #[test]
    fn mapping_plan_for_u32_aligned_but_unaligned_page_base() {
        let base = 0x9c00_0804u64;
        let plan = plan_mapping(base, SARGO_SPAN, 4096).unwrap();
        assert_eq!(plan.map_offset, 0x9c00_0000);
        assert_eq!(plan.copy_delta, 0x804);
        assert_eq!(plan.map_len, SARGO_SPAN + 0x804);
        assert_eq!(plan.map_offset % 4096, 0);
    }

    #[test]
    fn mapping_plan_rejects_overflow_and_invalid_pages() {
        assert!(plan_mapping(SARGO_BASE, usize::MAX, 4096).is_err());
        assert!(plan_mapping(0, usize::MAX, 4096).is_err());
        assert!(plan_mapping(5, usize::MAX, 4096).is_err());
        assert!(plan_mapping(u64::MAX - 3, 1 << 20, 4096).is_err());
        assert!(plan_mapping(SARGO_BASE, SARGO_SPAN, 0).is_err());
        assert!(plan_mapping(SARGO_BASE, SARGO_SPAN, 3000).is_err());
        assert!(plan_mapping(SARGO_BASE, 0, 4096).is_err());
        assert!(plan_mapping(0x9c00_0802, SARGO_SPAN, 4096).is_err());
    }
}
