use std::fs;
use std::path::{Path, PathBuf};

use crate::image::PixelFormat;

pub const MAX_DIM: u32 = 16384;
pub const MAX_STRIDE: u32 = 1 << 20;
pub const MAX_SPAN: u64 = 64 << 20;

#[derive(Debug, Clone)]
pub struct DtFramebuffer {
    pub node_path: PathBuf,
    pub width: u32,
    pub height: u32,
    pub stride: u32,
    pub format: PixelFormat,
    pub region_phandle: u32,
    pub status_ok: bool,
    pub compatible: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct ReservedRegion {
    pub node_path: PathBuf,
    pub base: u64,
    pub size: u64,
    pub no_map: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CaptureGeometry {
    pub base: u64,
    pub span: usize,
    pub width: u32,
    pub height: u32,
    pub stride: usize,
    pub format: PixelFormat,
    pub region_size: u64,
}

pub fn discover_base(explicit: Option<&Path>) -> Option<PathBuf> {
    if let Some(p) = explicit {
        return p.is_dir().then(|| p.to_path_buf());
    }
    for candidate in ["/sys/firmware/devicetree/base", "/proc/device-tree"] {
        let p = PathBuf::from(candidate);
        if p.is_dir() {
            return Some(p);
        }
    }
    None
}

fn read_prop(node: &Path, name: &str) -> Result<Vec<u8>, String> {
    fs::read(node.join(name)).map_err(|e| format!("{}/{}: {e}", node.display(), name))
}

fn read_prop_opt(node: &Path, name: &str) -> Option<Vec<u8>> {
    fs::read(node.join(name)).ok()
}

fn read_string_prop(node: &Path, name: &str) -> Result<String, String> {
    let raw = read_prop(node, name)?;
    let strings = parse_strings(&raw);
    strings
        .into_iter()
        .next()
        .ok_or_else(|| format!("{}/{}: empty string property", node.display(), name))
}

fn read_u32_prop(node: &Path, name: &str) -> Result<u32, String> {
    let raw = read_prop(node, name)?;
    let cells = parse_be_u32s(&raw)?;
    match cells.as_slice() {
        [value] => Ok(*value),
        _ => Err(format!(
            "{}/{}: expected exactly one cell, found {}",
            node.display(),
            name,
            cells.len()
        )),
    }
}

fn read_cells_prop(node: &Path, name: &str) -> Result<usize, String> {
    let raw = read_prop(node, name)?;
    let cells = parse_be_u32s(&raw)?;
    match cells.as_slice() {
        [1] => Ok(1),
        [2] => Ok(2),
        [value] => Err(format!(
            "{}/{}: unsupported cell width {value} (supported: 1 or 2)",
            node.display(),
            name
        )),
        _ => Err(format!(
            "{}/{}: expected exactly one cell",
            node.display(),
            name
        )),
    }
}

fn single_phandle(node: &Path) -> Result<Option<u32>, String> {
    match read_prop_opt(node, "phandle") {
        None => Ok(None),
        Some(raw) => {
            let cells = parse_be_u32s(&raw)?;
            match cells.as_slice() {
                [value] => Ok(Some(*value)),
                _ => Err(format!(
                    "{}/phandle: expected exactly one cell",
                    node.display()
                )),
            }
        }
    }
}

fn check_identity_ranges(node: &Path) -> Result<(), String> {
    if let Some(raw) = read_prop_opt(node, "ranges") {
        if !raw.is_empty() {
            return Err(format!(
                "{}/ranges: non-empty ranges are not supported for reserved-memory",
                node.display()
            ));
        }
    }
    Ok(())
}

pub fn parse_be_u32s(bytes: &[u8]) -> Result<Vec<u32>, String> {
    if bytes.len() % 4 != 0 {
        return Err(format!(
            "device tree property length {} is not a multiple of 4",
            bytes.len()
        ));
    }
    Ok(bytes
        .chunks_exact(4)
        .map(|c| u32::from_be_bytes([c[0], c[1], c[2], c[3]]))
        .collect())
}

pub fn parse_strings(bytes: &[u8]) -> Vec<String> {
    bytes
        .split(|b| *b == 0)
        .filter(|s| !s.is_empty())
        .map(|s| String::from_utf8_lossy(s).into_owned())
        .collect()
}

pub fn combine_cells(
    cells: &[u32],
    addr_cells: usize,
    size_cells: usize,
) -> Result<(u64, u64), String> {
    if addr_cells == 0 || size_cells == 0 || addr_cells > 2 || size_cells > 2 {
        return Err(format!(
            "unsupported address/size cells {addr_cells}/{size_cells}"
        ));
    }
    let needed = addr_cells + size_cells;
    if cells.len() != needed {
        return Err(format!(
            "reg has {} cells, expected exactly {needed} for {} address and {} size cells",
            cells.len(),
            addr_cells,
            size_cells
        ));
    }
    let mut base = 0u64;
    for cell in &cells[..addr_cells] {
        base = (base << 32) | *cell as u64;
    }
    let mut size = 0u64;
    for cell in &cells[addr_cells..needed] {
        size = (size << 32) | *cell as u64;
    }
    Ok((base, size))
}

pub fn find_framebuffer(base: &Path) -> Result<Option<DtFramebuffer>, String> {
    let chosen = base.join("chosen");
    if !chosen.is_dir() {
        return Ok(None);
    }
    let mut candidates: Vec<PathBuf> = fs::read_dir(&chosen)
        .map_err(|e| format!("read {}: {e}", chosen.display()))?
        .flatten()
        .filter(|e| e.file_name().to_string_lossy().starts_with("framebuffer"))
        .map(|e| e.path())
        .collect();
    candidates.sort();
    let mut matched = Vec::new();
    for node in candidates {
        let compatible = read_prop_opt(&node, "compatible")
            .map(|b| parse_strings(&b))
            .unwrap_or_default();
        if compatible.iter().any(|c| c == "simple-framebuffer") {
            matched.push(node);
        }
    }
    if matched.len() > 1 {
        let names: Vec<String> = matched.iter().map(|p| p.display().to_string()).collect();
        return Err(format!(
            "ambiguous simple-framebuffer nodes: {}",
            names.join(", ")
        ));
    }
    let node = match matched.pop() {
        Some(node) => node,
        None => return Ok(None),
    };
    let width = read_u32_prop(&node, "width")?;
    let height = read_u32_prop(&node, "height")?;
    let stride = read_u32_prop(&node, "stride")?;
    let format = PixelFormat::from_dt(&read_string_prop(&node, "format")?)
        .ok_or_else(|| format!("{}: unsupported format", node.display()))?;
    let region_cells = parse_be_u32s(&read_prop(&node, "memory-region")?)?;
    let region_phandle = match region_cells.as_slice() {
        [value] => *value,
        _ => {
            return Err(format!(
                "{}: memory-region must contain exactly one phandle cell",
                node.display()
            ))
        }
    };
    let status_ok = match read_prop_opt(&node, "status") {
        Some(raw) => {
            let s = parse_strings(&raw).into_iter().next().unwrap_or_default();
            s == "okay" || s == "ok"
        }
        None => true,
    };
    Ok(Some(DtFramebuffer {
        node_path: node,
        width,
        height,
        stride,
        format,
        region_phandle,
        status_ok,
        compatible: vec!["simple-framebuffer".to_string()],
    }))
}

pub fn resolve_reserved_region(base: &Path, phandle: u32) -> Result<ReservedRegion, String> {
    let reserved = base.join("reserved-memory");
    if !reserved.is_dir() {
        return Err(format!("{}: no reserved-memory node", reserved.display()));
    }
    let addr_cells = read_cells_prop(&reserved, "#address-cells")?;
    let size_cells = read_cells_prop(&reserved, "#size-cells")?;
    check_identity_ranges(&reserved)?;

    let mut found: Option<ReservedRegion> = None;
    for entry in fs::read_dir(&reserved)
        .map_err(|e| format!("read {}: {e}", reserved.display()))?
        .flatten()
    {
        let node = entry.path();
        let this_phandle = match single_phandle(&node)? {
            Some(value) => value,
            None => continue,
        };
        if this_phandle != phandle {
            continue;
        }
        if found.is_some() {
            return Err(format!(
                "multiple reserved-memory children claim phandle {phandle:#x}"
            ));
        }
        let reg = parse_be_u32s(&read_prop(&node, "reg")?)?;
        let (address, size) = combine_cells(&reg, addr_cells, size_cells)?;
        found = Some(ReservedRegion {
            node_path: node.clone(),
            base: address,
            size,
            no_map: node.join("no-map").exists(),
        });
    }
    found.ok_or_else(|| format!("no reserved-memory child with phandle {phandle:#x}"))
}

pub fn validate_geometry(
    fb: &DtFramebuffer,
    region: &ReservedRegion,
) -> Result<CaptureGeometry, String> {
    if !fb.status_ok {
        return Err(format!(
            "{}: DT node status is disabled",
            fb.node_path.display()
        ));
    }
    if !region.no_map {
        return Err(format!(
            "{}: reservation is not marked no-map; refusing /dev/mem access",
            region.node_path.display()
        ));
    }
    if fb.width == 0 || fb.height == 0 {
        return Err(format!(
            "{}: zero framebuffer dimension {}x{}",
            fb.node_path.display(),
            fb.width,
            fb.height
        ));
    }
    if fb.width > MAX_DIM || fb.height > MAX_DIM {
        return Err(format!(
            "{}: implausible framebuffer {}x{}",
            fb.node_path.display(),
            fb.width,
            fb.height
        ));
    }
    if fb.stride % 4 != 0 {
        return Err(format!(
            "{}: stride {} is not 4-aligned",
            fb.node_path.display(),
            fb.stride
        ));
    }
    let min_stride = (fb.width as u64) * 4;
    if (fb.stride as u64) < min_stride || fb.stride > MAX_STRIDE {
        return Err(format!(
            "{}: stride {} outside [{min_stride}, {MAX_STRIDE}]",
            fb.node_path.display(),
            fb.stride
        ));
    }
    let span = (fb.stride as u64)
        .checked_mul(fb.height as u64)
        .ok_or_else(|| "framebuffer span overflow".to_string())?;
    if span == 0 || span > MAX_SPAN {
        return Err(format!("framebuffer span {span} out of range"));
    }
    if region.size == 0 {
        return Err(format!(
            "{}: zero reserved region size",
            region.node_path.display()
        ));
    }
    if span > region.size {
        return Err(format!(
            "framebuffer span {span} exceeds reserved region {}",
            region.size
        ));
    }
    if region.base % 4 != 0 {
        return Err(format!(
            "reserved region base {:#x} is not 4-aligned",
            region.base
        ));
    }
    region
        .base
        .checked_add(span)
        .ok_or_else(|| "reserved region address overflow".to_string())?;
    let span_usize = usize::try_from(span).map_err(|_| "span does not fit usize".to_string())?;
    Ok(CaptureGeometry {
        base: region.base,
        span: span_usize,
        width: fb.width,
        height: fb.height,
        stride: fb.stride as usize,
        format: fb.format,
        region_size: region.size,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicU64, Ordering};

    static COUNTER: AtomicU64 = AtomicU64::new(0);

    struct TempTree(PathBuf);

    impl TempTree {
        fn new(name: &str) -> Self {
            let n = COUNTER.fetch_add(1, Ordering::SeqCst);
            let dir = std::env::temp_dir().join(format!(
                "premouth-dt-{}-{}-{}-{}",
                std::process::id(),
                n,
                crate::pacing::monotonic_ns(),
                name
            ));
            fs::create_dir_all(&dir).unwrap();
            TempTree(dir)
        }

        fn path(&self) -> &Path {
            &self.0
        }
    }

    impl Drop for TempTree {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    struct TreeSpec<'a> {
        fb_memory_region: &'a [u32],
        reserved_phandle: &'a [u32],
        reserved_reg: &'a [u32],
        reserved_addr_cells: Option<&'a [u32]>,
        reserved_size_cells: Option<&'a [u32]>,
        root_addr_cells: &'a [u32],
        root_size_cells: &'a [u32],
        ranges: Option<&'a [u32]>,
        no_map: bool,
        framebuffer_count: usize,
        duplicate_phandle: bool,
    }

    fn sargo_spec<'a>() -> TreeSpec<'a> {
        TreeSpec {
            fb_memory_region: &[3],
            reserved_phandle: &[3],
            reserved_reg: &[0x0000_0000, 0x9c00_0000, 0x0000_0000, 0x0240_0000],
            reserved_addr_cells: Some(&[2]),
            reserved_size_cells: Some(&[2]),
            root_addr_cells: &[1],
            root_size_cells: &[1],
            ranges: Some(&[]),
            no_map: true,
            framebuffer_count: 1,
            duplicate_phandle: false,
        }
    }

    fn write_be(path: &Path, values: &[u32]) {
        let mut bytes = Vec::new();
        for value in values {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        fs::write(path, bytes).unwrap();
    }

    fn write_text(path: &Path, text: &str) {
        let mut bytes = text.as_bytes().to_vec();
        bytes.push(0);
        fs::write(path, bytes).unwrap();
    }

    fn build_tree(root: &Path, spec: &TreeSpec<'_>) {
        write_be(&root.join("#address-cells"), spec.root_addr_cells);
        write_be(&root.join("#size-cells"), spec.root_size_cells);
        let chosen = root.join("chosen");
        fs::create_dir_all(&chosen).unwrap();
        for index in 0..spec.framebuffer_count {
            let node = chosen.join(format!("framebuffer@{index}"));
            fs::create_dir_all(&node).unwrap();
            write_text(&node.join("compatible"), "simple-framebuffer");
            write_be(&node.join("width"), &[1080]);
            write_be(&node.join("height"), &[2220]);
            write_be(&node.join("stride"), &[4320]);
            write_text(&node.join("format"), "a8r8g8b8");
            write_be(&node.join("memory-region"), spec.fb_memory_region);
        }
        let reserved = root.join("reserved-memory");
        fs::create_dir_all(&reserved).unwrap();
        if let Some(cells) = spec.reserved_addr_cells {
            write_be(&reserved.join("#address-cells"), cells);
        }
        if let Some(cells) = spec.reserved_size_cells {
            write_be(&reserved.join("#size-cells"), cells);
        }
        if let Some(ranges) = spec.ranges {
            write_be(&reserved.join("ranges"), ranges);
        }
        let child = reserved.join("framebuffer@9c000000");
        fs::create_dir_all(&child).unwrap();
        write_be(&child.join("phandle"), spec.reserved_phandle);
        write_be(&child.join("reg"), spec.reserved_reg);
        if spec.no_map {
            fs::write(child.join("no-map"), b"").unwrap();
        }
        if spec.duplicate_phandle {
            let duplicate = reserved.join("framebuffer@9c000000-dup");
            fs::create_dir_all(&duplicate).unwrap();
            write_be(&duplicate.join("phandle"), spec.reserved_phandle);
            write_be(&duplicate.join("reg"), spec.reserved_reg);
        }
    }

    fn fb(width: u32, height: u32, stride: u32) -> DtFramebuffer {
        DtFramebuffer {
            node_path: PathBuf::from("/chosen/framebuffer@9c000000"),
            width,
            height,
            stride,
            format: PixelFormat::Argb8888,
            region_phandle: 3,
            status_ok: true,
            compatible: vec!["simple-framebuffer".to_string()],
        }
    }

    fn region(base: u64, size: u64) -> ReservedRegion {
        ReservedRegion {
            node_path: PathBuf::from("/reserved-memory/framebuffer@9c000000"),
            base,
            size,
            no_map: true,
        }
    }

    #[test]
    fn parses_big_endian_cells() {
        assert_eq!(
            parse_be_u32s(&[0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x02]).unwrap(),
            vec![1, 2]
        );
        assert!(parse_be_u32s(&[0, 1, 2]).is_err());
    }

    #[test]
    fn combines_cells_requires_exact_tuple() {
        assert_eq!(
            combine_cells(&[0x0000_0009, 0xc000_0000, 0x0000_0000, 0x0240_0000], 2, 2).unwrap(),
            (0x0000_0009_c000_0000, 0x0240_0000)
        );
        assert_eq!(
            combine_cells(&[0x9c00_0000, 0x0240_0000], 1, 1).unwrap(),
            (0x9c00_0000, 0x0240_0000)
        );
        assert!(combine_cells(&[0x9c00_0000], 2, 2).is_err());
        assert!(combine_cells(&[0, 0, 0, 0, 0, 0], 2, 2).is_err());
        assert!(combine_cells(&[0, 0, 0, 0], 3, 3).is_err());
    }

    #[test]
    fn validates_sargo_geometry() {
        let geo = validate_geometry(&fb(1080, 2220, 4320), &region(0x9c00_0000, 36 << 20)).unwrap();
        assert_eq!(geo.span, 4320 * 2220);
        assert_eq!(geo.stride, 4320);
        assert_eq!(geo.format, PixelFormat::Argb8888);
    }

    #[test]
    fn rejects_bad_geometry() {
        assert!(validate_geometry(&fb(0, 10, 40), &region(0x1000, 1 << 20)).is_err());
        assert!(validate_geometry(&fb(1080, 2220, 4000), &region(0x1000, 36 << 20)).is_err());
        assert!(validate_geometry(&fb(1080, 2220, 4321), &region(0x1000, 36 << 20)).is_err());
        assert!(validate_geometry(&fb(1080, 2220, 4320), &region(0x1000, 1000)).is_err());
        assert!(validate_geometry(&fb(1080, 2220, 4320), &region(0x1001, 36 << 20)).is_err());
        let mut disabled = fb(1080, 2220, 4320);
        disabled.status_ok = false;
        assert!(validate_geometry(&disabled, &region(0x1000, 36 << 20)).is_err());
        let mut not_no_map = region(0x1000, 36 << 20);
        not_no_map.no_map = false;
        assert!(validate_geometry(&fb(1080, 2220, 4320), &not_no_map).is_err());
    }

    #[test]
    fn rejects_implausible_span() {
        let huge = fb(16000, 16000, 4 * 16000);
        assert!(validate_geometry(&huge, &region(0, 1 << 30)).is_err());
    }

    #[test]
    fn parses_string_lists() {
        let strings = parse_strings(b"simple-framebuffer\0simplefb\0");
        assert_eq!(strings, vec!["simple-framebuffer", "simplefb"]);
    }

    #[test]
    fn synthetic_tree_resolves_sargo_region_using_reserved_cells() {
        let tree = TempTree::new("sargo");
        build_tree(tree.path(), &sargo_spec());
        let framebuffer = find_framebuffer(tree.path()).unwrap().unwrap();
        assert_eq!(framebuffer.width, 1080);
        assert_eq!(framebuffer.height, 2220);
        assert_eq!(framebuffer.region_phandle, 3);
        let region = resolve_reserved_region(tree.path(), 3).unwrap();
        assert_eq!(region.base, 0x9c00_0000);
        assert_eq!(region.size, 0x0240_0000);
        assert!(region.no_map);
        let geo = validate_geometry(&framebuffer, &region).unwrap();
        assert_eq!(geo.span, 4320 * 2220);
    }

    #[test]
    fn synthetic_tree_uses_one_cell_reg_when_reserved_declares_one_cell() {
        let tree = TempTree::new("onecell");
        let root_addr = [2u32];
        let root_size = [2u32];
        let reserved_addr = [1u32];
        let reserved_size = [1u32];
        let reserved_reg = [0x9c00_0000u32, 0x0240_0000];
        let mut spec = sargo_spec();
        spec.root_addr_cells = &root_addr;
        spec.root_size_cells = &root_size;
        spec.reserved_addr_cells = Some(&reserved_addr);
        spec.reserved_size_cells = Some(&reserved_size);
        spec.reserved_reg = &reserved_reg;
        build_tree(tree.path(), &spec);
        let region = resolve_reserved_region(tree.path(), 3).unwrap();
        assert_eq!(region.base, 0x9c00_0000);
        assert_eq!(region.size, 0x0240_0000);
    }

    #[test]
    fn synthetic_tree_rejects_missing_no_map() {
        let tree = TempTree::new("nomap");
        let mut spec = sargo_spec();
        spec.no_map = false;
        build_tree(tree.path(), &spec);
        let framebuffer = find_framebuffer(tree.path()).unwrap().unwrap();
        let region = resolve_reserved_region(tree.path(), 3).unwrap();
        assert!(!region.no_map);
        assert!(validate_geometry(&framebuffer, &region).is_err());
    }

    #[test]
    fn synthetic_tree_rejects_malformed_properties() {
        let bad_reg = [0x9c00_0000u32, 0x0240_0000, 0];
        let tree = TempTree::new("malformed-reg");
        let mut spec = sargo_spec();
        spec.reserved_reg = &bad_reg;
        build_tree(tree.path(), &spec);
        assert!(resolve_reserved_region(tree.path(), 3).is_err());

        let bad_phandle = [0u32, 3];
        let tree = TempTree::new("malformed-phandle");
        let mut spec = sargo_spec();
        spec.reserved_phandle = &bad_phandle;
        build_tree(tree.path(), &spec);
        assert!(resolve_reserved_region(tree.path(), 3).is_err());

        let bad_region = [0u32, 3];
        let tree = TempTree::new("malformed-memory-region");
        let mut spec = sargo_spec();
        spec.fb_memory_region = &bad_region;
        build_tree(tree.path(), &spec);
        assert!(find_framebuffer(tree.path()).is_err());

        let tree = TempTree::new("missing-cells");
        let mut spec = sargo_spec();
        spec.reserved_addr_cells = None;
        build_tree(tree.path(), &spec);
        assert!(resolve_reserved_region(tree.path(), 3).is_err());

        let bad_width = [3u32];
        let tree = TempTree::new("bad-cell-width");
        let mut spec = sargo_spec();
        spec.reserved_addr_cells = Some(&bad_width);
        build_tree(tree.path(), &spec);
        assert!(resolve_reserved_region(tree.path(), 3).is_err());
    }

    #[test]
    fn synthetic_tree_rejects_nonempty_ranges() {
        let tree = TempTree::new("ranges");
        let nonempty = [0u32, 0, 0, 1];
        let mut spec = sargo_spec();
        spec.ranges = Some(&nonempty);
        build_tree(tree.path(), &spec);
        assert!(resolve_reserved_region(tree.path(), 3).is_err());
    }

    #[test]
    fn synthetic_tree_rejects_ambiguous_or_duplicate_candidates() {
        let tree = TempTree::new("ambiguous");
        let mut spec = sargo_spec();
        spec.framebuffer_count = 2;
        build_tree(tree.path(), &spec);
        assert!(find_framebuffer(tree.path()).is_err());

        let tree = TempTree::new("duplicate");
        let mut spec = sargo_spec();
        spec.duplicate_phandle = true;
        build_tree(tree.path(), &spec);
        assert!(resolve_reserved_region(tree.path(), 3).is_err());
    }
}
