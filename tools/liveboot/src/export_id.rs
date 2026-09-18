//! smoo export ids for files served by `smoo-host --file`.
//!
//! `smoo-host` derives the id of an export from what it serves, and the phone
//! selects its root by that id (`rd.smoo.root=`). For a file the identity is
//! `file:<canonical path>` and the geometry is 512-byte blocks, hashed with
//! FNV-1a as `smoo_host_core::derive_export_id` does. Reproducing it here
//! keeps the tool free of a git dependency on an unreleased smoo; the vector
//! in the tests was cross-checked against a real `smoo-host` on 2026-09-18.

use std::{fs, io, path::Path};

const FNV_OFFSET_BASIS: u32 = 0x811c_9dc5;
const FNV_PRIME: u32 = 0x0100_0193;
const BLOCK_SIZE: u32 = 512;

/// The export id `smoo-host --file <path>` will announce.
pub fn for_file(path: &Path) -> io::Result<u32> {
    let canonical = fs::canonicalize(path)?;
    let len = fs::metadata(&canonical)?.len();
    let identity = format!("file:{}", canonical.display());
    Ok(derive(&identity, BLOCK_SIZE, len / u64::from(BLOCK_SIZE)))
}

/// `derive_export_id(source_id, block_size, block_count)` from smoo-host-core:
/// the geometry in native (little-endian) byte order, then the identity.
pub fn derive(source_id: &str, block_size: u32, block_count: u64) -> u32 {
    let mut state = FNV_OFFSET_BASIS;
    let mut feed = |bytes: &[u8]| {
        for byte in bytes {
            state ^= u32::from(*byte);
            state = state.wrapping_mul(FNV_PRIME);
        }
    };
    feed(&block_size.to_le_bytes());
    feed(&block_count.to_le_bytes());
    feed(source_id.as_bytes());
    if state == 0 {
        1
    } else {
        state
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matches_smoo_host_core() {
        // smoo-host-core's own test inputs, with the values its implementation
        // produces.
        assert_eq!(derive("file:/dev/null", 512, 1024), 4_135_154_927);
        assert_ne!(derive("file:/dev/null", 4096, 1024), 4_135_154_927);
        assert_ne!(derive("file:/dev/null", 512, 2048), 4_135_154_927);
    }

    #[test]
    fn a_file_is_identified_by_its_canonical_path_and_size() {
        let dir = std::env::temp_dir().join(format!("liveboot-export-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let file = dir.join("root.img");
        fs::write(&file, vec![0u8; 4096]).unwrap();

        let expected = derive(
            &format!("file:{}", fs::canonicalize(&file).unwrap().display()),
            512,
            8,
        );
        assert_eq!(for_file(&file).unwrap(), expected);

        let relative = dir.join("./root.img");
        assert_eq!(
            for_file(&relative).unwrap(),
            expected,
            "the path is canonicalised first"
        );

        fs::remove_dir_all(&dir).unwrap();
    }
}
