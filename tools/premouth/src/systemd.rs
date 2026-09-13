use std::env;
use std::ffi::OsStr;
use std::io;
use std::os::unix::ffi::OsStrExt;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum NotifyAddr {
    Abstract(Vec<u8>),
    Pathname(Vec<u8>),
}

pub fn parse_notify_socket(value: &OsStr) -> Result<NotifyAddr, String> {
    let bytes = value.as_bytes();
    if bytes.is_empty() {
        return Err("empty NOTIFY_SOCKET".to_string());
    }
    if bytes.len() > 107 {
        return Err("NOTIFY_SOCKET path too long".to_string());
    }
    if bytes[0] == b'@' {
        Ok(NotifyAddr::Abstract(bytes[1..].to_vec()))
    } else {
        Ok(NotifyAddr::Pathname(bytes.to_vec()))
    }
}

pub fn notify(message: &str) -> io::Result<()> {
    let value = match env::var_os("NOTIFY_SOCKET") {
        Some(v) => v,
        None => return Ok(()),
    };
    let addr =
        parse_notify_socket(&value).map_err(|e| io::Error::new(io::ErrorKind::InvalidInput, e))?;
    let fd = unsafe { libc::socket(libc::AF_UNIX, libc::SOCK_DGRAM | libc::SOCK_CLOEXEC, 0) };
    if fd < 0 {
        return Err(io::Error::last_os_error());
    }
    let mut sun: libc::sockaddr_un = unsafe { std::mem::zeroed() };
    sun.sun_family = libc::AF_UNIX as libc::sa_family_t;
    let len = match &addr {
        NotifyAddr::Abstract(name) => {
            sun.sun_path[0] = 0;
            copy_path(name, &mut sun.sun_path[1..]);
            (std::mem::size_of::<libc::sa_family_t>() + 1 + name.len()) as libc::socklen_t
        }
        NotifyAddr::Pathname(path) => {
            copy_path(path, &mut sun.sun_path[..]);
            (std::mem::size_of::<libc::sa_family_t>() + path.len() + 1) as libc::socklen_t
        }
    };
    let rc = unsafe {
        libc::sendto(
            fd,
            message.as_ptr() as *const libc::c_void,
            message.len(),
            libc::MSG_NOSIGNAL,
            &sun as *const libc::sockaddr_un as *const libc::sockaddr,
            len,
        )
    };
    unsafe {
        libc::close(fd);
    }
    if rc < 0 {
        return Err(io::Error::last_os_error());
    }
    unsafe {
        env::remove_var("NOTIFY_SOCKET");
    }
    Ok(())
}

fn copy_path(source: &[u8], dest: &mut [libc::c_char]) {
    let bytes = unsafe { std::slice::from_raw_parts_mut(dest.as_mut_ptr() as *mut u8, dest.len()) };
    let n = source.len().min(bytes.len());
    bytes[..n].copy_from_slice(&source[..n]);
}

pub fn ready(status: &str) {
    let _ = notify(&format!("READY=1\nSTATUS={status}\n"));
}

pub fn status(text: &str) {
    let _ = notify(&format!("STATUS={text}\n"));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_abstract_and_pathname() {
        assert_eq!(
            parse_notify_socket(OsStr::new("@premouth")).unwrap(),
            NotifyAddr::Abstract(b"premouth".to_vec())
        );
        assert_eq!(
            parse_notify_socket(OsStr::new("/run/systemd/notify")).unwrap(),
            NotifyAddr::Pathname(b"/run/systemd/notify".to_vec())
        );
        assert!(parse_notify_socket(OsStr::new("")).is_err());
    }

    #[test]
    fn notify_without_socket_is_noop() {
        env::remove_var("NOTIFY_SOCKET");
        assert!(notify("READY=1").is_ok());
    }
}
