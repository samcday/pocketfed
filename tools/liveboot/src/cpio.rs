//! A minimal `newc` cpio writer, for appending files to an existing initramfs.
//!
//! The kernel accepts several cpio archives concatenated together and unpacks
//! them in order, later entries winning. That is how microcode is prepended to
//! a distribution initramfs, and it is how liveboot adds the smoo dracut module
//! to an image's own initrd without rebuilding it: the image's compressed
//! archive is kept byte for byte and a small uncompressed archive is appended.
//!
//! Only what that needs is implemented: directories, regular files and symlinks.

use std::{
    fs,
    io::{self},
    os::unix::fs::PermissionsExt,
    path::{Component, Path, PathBuf},
};

const MAGIC: &[u8; 6] = b"070701";
const TRAILER: &str = "TRAILER!!!";

const MODE_DIR: u32 = 0o040000;
const MODE_FILE: u32 = 0o100000;
const MODE_SYMLINK: u32 = 0o120000;

/// One archive member.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Entry {
    /// Path inside the initramfs, with no leading slash.
    pub name: String,
    /// Full st_mode: file type bits plus permissions.
    pub mode: u32,
    /// File contents, or the target for a symlink. Empty for a directory.
    pub data: Vec<u8>,
}

impl Entry {
    pub fn dir(name: impl Into<String>, perms: u32) -> Self {
        Self {
            name: name.into(),
            mode: MODE_DIR | (perms & 0o7777),
            data: Vec::new(),
        }
    }

    pub fn file(name: impl Into<String>, perms: u32, data: Vec<u8>) -> Self {
        Self {
            name: name.into(),
            mode: MODE_FILE | (perms & 0o7777),
            data,
        }
    }

    pub fn symlink(name: impl Into<String>, target: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            mode: MODE_SYMLINK | 0o777,
            data: target.into().into_bytes(),
        }
    }
}

/// Serialise entries as a `newc` archive, terminated by the standard trailer.
///
/// Inode numbers are assigned sequentially rather than taken from the host, so
/// the same input always produces the same bytes.
pub fn write(entries: &[Entry]) -> Vec<u8> {
    let mut out = Vec::new();
    for (index, entry) in entries.iter().enumerate() {
        push_member(
            &mut out,
            index as u32 + 1,
            entry.mode,
            &entry.name,
            &entry.data,
        );
    }
    push_member(&mut out, 0, 0, TRAILER, &[]);
    pad_to(&mut out, 512);
    out
}

fn push_member(out: &mut Vec<u8>, ino: u32, mode: u32, name: &str, data: &[u8]) {
    let namesize = name.len() as u32 + 1;
    out.extend_from_slice(MAGIC);
    for field in [
        ino,
        mode,
        0, // uid: everything in the initramfs belongs to root
        0, // gid
        1, // nlink
        0, // mtime: zero keeps the output reproducible
        data.len() as u32,
        0, // devmajor
        0, // devminor
        0, // rdevmajor
        0, // rdevminor
        namesize,
        0, // check: unused by the newc format
    ] {
        out.extend_from_slice(format!("{field:08X}").as_bytes());
    }
    out.extend_from_slice(name.as_bytes());
    out.push(0);
    pad_to(out, 4);
    out.extend_from_slice(data);
    pad_to(out, 4);
}

fn pad_to(out: &mut Vec<u8>, alignment: usize) {
    let padding = (alignment - out.len() % alignment) % alignment;
    out.resize(out.len() + padding, 0);
}

/// Collect a directory tree into archive entries, mirroring its layout.
///
/// `root` stands in for the initramfs root: `root/usr/bin/x` becomes
/// `usr/bin/x`. Permissions come from the filesystem, so an executable stays
/// executable. Entries are sorted so the archive is reproducible, and every
/// parent directory is emitted before its contents.
pub fn from_tree(root: &Path) -> io::Result<Vec<Entry>> {
    let mut paths = Vec::new();
    collect(root, &mut paths)?;
    paths.sort();

    let mut entries = Vec::with_capacity(paths.len());
    for path in paths {
        let name = relative_name(root, &path)?;
        let metadata = fs::symlink_metadata(&path)?;
        let perms = metadata.permissions().mode() & 0o7777;
        if metadata.is_dir() {
            entries.push(Entry::dir(name, perms));
        } else if metadata.is_symlink() {
            let target = fs::read_link(&path)?;
            entries.push(Entry::symlink(name, target.to_string_lossy().into_owned()));
        } else if metadata.is_file() {
            entries.push(Entry::file(name, perms, fs::read(&path)?));
        } else {
            // A FIFO would block the read forever and a device node has no
            // end; neither belongs in an initramfs anyway.
            return Err(io::Error::new(
                io::ErrorKind::Unsupported,
                format!("not a regular file: {}", path.display()),
            ));
        }
    }
    Ok(entries)
}

fn collect(dir: &Path, out: &mut Vec<PathBuf>) -> io::Result<()> {
    for entry in fs::read_dir(dir)? {
        let path = entry?.path();
        out.push(path.clone());
        if fs::symlink_metadata(&path)?.is_dir() {
            collect(&path, out)?;
        }
    }
    Ok(())
}

fn relative_name(root: &Path, path: &Path) -> io::Result<String> {
    let relative = path.strip_prefix(root).map_err(|_| {
        io::Error::new(
            io::ErrorKind::InvalidInput,
            format!("{} is not inside {}", path.display(), root.display()),
        )
    })?;
    if relative
        .components()
        .any(|component| !matches!(component, Component::Normal(_)))
    {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            format!(
                "refusing to archive path with traversal: {}",
                relative.display()
            ),
        ));
    }
    Ok(relative.to_string_lossy().into_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn field(archive: &[u8], member_start: usize, index: usize) -> u32 {
        let offset = member_start + 6 + index * 8;
        let text = std::str::from_utf8(&archive[offset..offset + 8]).unwrap();
        u32::from_str_radix(text, 16).unwrap()
    }

    #[test]
    fn a_file_member_has_the_newc_header_and_padded_data() {
        let archive = write(&[Entry::file("usr/bin/x", 0o755, b"hello".to_vec())]);

        assert_eq!(&archive[..6], MAGIC);
        assert_eq!(field(&archive, 0, 1), MODE_FILE | 0o755, "mode");
        assert_eq!(field(&archive, 0, 6), 5, "filesize");
        assert_eq!(
            field(&archive, 0, 11),
            "usr/bin/x".len() as u32 + 1,
            "namesize"
        );

        let name_start = 6 + 13 * 8;
        assert_eq!(&archive[name_start..name_start + 9], b"usr/bin/x");
        assert_eq!(archive[name_start + 9], 0, "name is NUL terminated");

        // Header is 110 bytes, the name is 10 with its NUL, so data starts at
        // the next multiple of four.
        let data_start = (110 + 10usize).div_ceil(4) * 4;
        assert_eq!(&archive[data_start..data_start + 5], b"hello");
    }

    #[test]
    fn the_archive_ends_with_a_trailer() {
        let archive = write(&[Entry::file("a", 0o644, b"x".to_vec())]);
        let text = String::from_utf8_lossy(&archive);
        assert!(text.contains(TRAILER), "no trailer in the archive");
    }

    #[test]
    fn output_is_512_byte_aligned_for_concatenation() {
        for entry in [
            Entry::file("a", 0o644, b"x".to_vec()),
            Entry::file("bb", 0o644, vec![0; 4097]),
        ] {
            let archive = write(&[entry]);
            assert_eq!(archive.len() % 512, 0, "archive is not padded");
        }
    }

    #[test]
    fn writing_is_deterministic() {
        let entries = vec![
            Entry::dir("usr", 0o755),
            Entry::file("usr/x", 0o755, b"data".to_vec()),
            Entry::symlink("link", "usr/x"),
        ];
        assert_eq!(write(&entries), write(&entries));
    }

    #[test]
    fn modes_carry_the_right_type_bits() {
        assert_eq!(Entry::dir("d", 0o755).mode, 0o040755);
        assert_eq!(Entry::file("f", 0o644, Vec::new()).mode, 0o100644);
        assert_eq!(Entry::symlink("l", "t").mode, 0o120777);
        assert_eq!(Entry::symlink("l", "target").data, b"target".to_vec());
    }

    #[test]
    fn a_tree_with_a_special_file_is_refused() {
        let dir = std::env::temp_dir().join(format!("liveboot-cpio-sock-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let socket = std::os::unix::net::UnixListener::bind(dir.join("sock")).unwrap();

        let err = from_tree(&dir).unwrap_err();
        assert_eq!(err.kind(), io::ErrorKind::Unsupported, "{err}");

        drop(socket);
        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn a_tree_becomes_sorted_relative_entries() {
        let dir = std::env::temp_dir().join(format!("liveboot-cpio-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(dir.join("usr/libexec/smoo")).unwrap();
        fs::write(dir.join("usr/libexec/smoo/smoo-lib"), b"lib").unwrap();
        fs::set_permissions(
            dir.join("usr/libexec/smoo/smoo-lib"),
            fs::Permissions::from_mode(0o755),
        )
        .unwrap();

        let entries = from_tree(&dir).unwrap();
        let names: Vec<&str> = entries.iter().map(|entry| entry.name.as_str()).collect();
        assert_eq!(
            names,
            vec![
                "usr",
                "usr/libexec",
                "usr/libexec/smoo",
                "usr/libexec/smoo/smoo-lib"
            ]
        );
        assert_eq!(entries[3].mode, MODE_FILE | 0o755, "executable bit is kept");
        assert_eq!(entries[0].mode, MODE_DIR | 0o755);

        fs::remove_dir_all(&dir).unwrap();
    }
}
