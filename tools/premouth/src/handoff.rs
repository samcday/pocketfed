use std::fs;
use std::io::{self, Read, Write};
use std::net::Shutdown;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::{DirBuilderExt, FileTypeExt, PermissionsExt};
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

pub const DEFAULT_SOCKET: &str = "/run/premouth/handoff.sock";
const MAX_CLIENTS: usize = 8;
const MAX_REQUEST_BYTES: usize = 128;
const MAX_RESPONSE_BYTES: usize = 256;
const LIVENESS_PROBE: Duration = Duration::from_millis(200);

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum YieldStatus {
    Released {
        black_flushed: bool,
        closefb_ok: bool,
    },
    AlreadyReleased {
        black_flushed: bool,
        closefb_ok: bool,
    },
    Cancelled,
    Busy,
    Error(String),
}

impl YieldStatus {
    pub fn encode(&self) -> String {
        match self {
            YieldStatus::Released {
                black_flushed,
                closefb_ok,
            } => format!(
                "ok released black={} closefb={}\n",
                u8::from(*black_flushed),
                u8::from(*closefb_ok)
            ),
            YieldStatus::AlreadyReleased {
                black_flushed,
                closefb_ok,
            } => format!(
                "ok already-released black={} closefb={}\n",
                u8::from(*black_flushed),
                u8::from(*closefb_ok)
            ),
            YieldStatus::Cancelled => "ok cancelled\n".to_string(),
            YieldStatus::Busy => "ok busy\n".to_string(),
            YieldStatus::Error(message) => format!("error {message}\n"),
        }
    }

    pub fn parse(line: &str) -> Result<Self, String> {
        let line = line.trim();
        let mut parts = line.split_whitespace();
        match parts.next() {
            Some("ok") => match parts.next() {
                Some("released") => Ok(YieldStatus::Released {
                    black_flushed: flag(&mut parts, "black="),
                    closefb_ok: flag(&mut parts, "closefb="),
                }),
                Some("already-released") => Ok(YieldStatus::AlreadyReleased {
                    black_flushed: flag(&mut parts, "black="),
                    closefb_ok: flag(&mut parts, "closefb="),
                }),
                Some("cancelled") => Ok(YieldStatus::Cancelled),
                Some("busy") => Ok(YieldStatus::Busy),
                other => Err(format!("unknown ok response {other:?}")),
            },
            Some("error") => {
                let rest = line.strip_prefix("error").unwrap_or("").trim();
                Ok(YieldStatus::Error(rest.to_string()))
            }
            _ => Err(format!("unrecognized handoff response {line:?}")),
        }
    }

    pub fn exit_code(&self) -> u8 {
        match self {
            YieldStatus::Released {
                black_flushed,
                closefb_ok,
            }
            | YieldStatus::AlreadyReleased {
                black_flushed,
                closefb_ok,
            } => {
                if *black_flushed && *closefb_ok {
                    0
                } else {
                    3
                }
            }
            YieldStatus::Cancelled => 0,
            YieldStatus::Busy => 4,
            YieldStatus::Error(_) => 1,
        }
    }

    pub fn describe(&self) -> String {
        match self {
            YieldStatus::Released {
                black_flushed,
                closefb_ok,
            } => format!("released (black_flushed={black_flushed}, closefb_ok={closefb_ok})"),
            YieldStatus::AlreadyReleased {
                black_flushed,
                closefb_ok,
            } => {
                format!("already released (black_flushed={black_flushed}, closefb_ok={closefb_ok})")
            }
            YieldStatus::Cancelled => "cancelled before display ownership".to_string(),
            YieldStatus::Busy => "another yield request is already pending".to_string(),
            YieldStatus::Error(message) => format!("error: {message}"),
        }
    }
}

fn flag(parts: &mut std::str::SplitWhitespace<'_>, prefix: &str) -> bool {
    parts
        .next()
        .and_then(|token| token.strip_prefix(prefix))
        .map(|value| value == "1")
        .unwrap_or(false)
}

struct Incoming {
    stream: UnixStream,
    buf: Vec<u8>,
}

pub struct HandoffServer {
    listener: Option<UnixListener>,
    path: Option<PathBuf>,
    incoming: Vec<Incoming>,
    waiters: Vec<UnixStream>,
    request_pending: bool,
    final_status: Option<YieldStatus>,
}

impl HandoffServer {
    pub fn bind(path: &Path) -> io::Result<Self> {
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                // Restrict newly created directories, but never chmod an
                // existing parent such as /run supplied through --socket.
                fs::DirBuilder::new()
                    .recursive(true)
                    .mode(0o700)
                    .create(parent)?;
            }
        }
        if let Ok(meta) = fs::symlink_metadata(path) {
            if !meta.file_type().is_socket() {
                return Err(io::Error::new(
                    io::ErrorKind::AlreadyExists,
                    format!("{} exists and is not a socket", path.display()),
                ));
            }
            match connect_with_deadline(path, Instant::now() + LIVENESS_PROBE) {
                Ok(_) => {
                    return Err(io::Error::new(
                        io::ErrorKind::AlreadyExists,
                        format!("another premouth daemon is listening on {}", path.display()),
                    ))
                }
                Err(e)
                    if e.kind() == io::ErrorKind::ConnectionRefused
                        || e.kind() == io::ErrorKind::NotFound =>
                {
                    fs::remove_file(path)?;
                }
                Err(e) => {
                    return Err(io::Error::new(
                        io::ErrorKind::AlreadyExists,
                        format!("cannot verify whether {} is stale: {e}", path.display()),
                    ))
                }
            }
        }
        let listener = UnixListener::bind(path)?;
        listener.set_nonblocking(true)?;
        let _ = fs::set_permissions(path, fs::Permissions::from_mode(0o600));
        Ok(HandoffServer {
            listener: Some(listener),
            path: Some(path.to_path_buf()),
            incoming: Vec::new(),
            waiters: Vec::new(),
            request_pending: false,
            final_status: None,
        })
    }

    pub fn poll_fd(&self) -> i32 {
        use std::os::fd::AsRawFd;
        self.listener.as_ref().map(|l| l.as_raw_fd()).unwrap_or(-1)
    }

    pub fn request_pending(&self) -> bool {
        self.request_pending
    }

    pub fn tick(&mut self) {
        self.accept_new();
        self.read_incoming();
        if let Some(status) = self.final_status.clone() {
            let status = match status {
                YieldStatus::Released {
                    black_flushed,
                    closefb_ok,
                } => YieldStatus::AlreadyReleased {
                    black_flushed,
                    closefb_ok,
                },
                other => other,
            };
            for mut waiter in self.waiters.drain(..) {
                respond(&mut waiter, &status);
            }
            self.request_pending = false;
        }
    }

    pub fn set_final(&mut self, status: YieldStatus) {
        self.request_pending = false;
        self.final_status = Some(status.clone());
        for mut waiter in self.waiters.drain(..) {
            respond(&mut waiter, &status);
        }
    }

    fn accept_new(&mut self) {
        loop {
            let listener = match &self.listener {
                Some(l) => l,
                None => return,
            };
            match listener.accept() {
                Ok((stream, _)) => {
                    let _ = stream.set_nonblocking(true);
                    let backlog = self.incoming.len() + self.waiters.len();
                    if backlog >= MAX_CLIENTS {
                        let mut stream = stream;
                        respond(&mut stream, &YieldStatus::Busy);
                    } else {
                        self.incoming.push(Incoming {
                            stream,
                            buf: Vec::new(),
                        });
                    }
                }
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => return,
                Err(_) => return,
            }
        }
    }

    fn read_incoming(&mut self) {
        let mut i = 0;
        while i < self.incoming.len() {
            let parsed = pump_request(&mut self.incoming[i]);
            match parsed {
                Ok(Some(line)) => {
                    let mut incoming = self.incoming.swap_remove(i);
                    if line == "yield" {
                        self.waiters.push(incoming.stream);
                        self.request_pending = true;
                    } else {
                        respond(
                            &mut incoming.stream,
                            &YieldStatus::Error(format!("unsupported request {line:?}")),
                        );
                    }
                }
                Ok(None) => i += 1,
                Err(_) => {
                    self.incoming.swap_remove(i);
                }
            }
        }
    }
}

impl Drop for HandoffServer {
    fn drop(&mut self) {
        if let Some(path) = &self.path {
            let _ = fs::remove_file(path);
        }
    }
}

fn pump_request(incoming: &mut Incoming) -> io::Result<Option<String>> {
    let mut chunk = [0u8; 64];
    loop {
        match incoming.stream.read(&mut chunk) {
            Ok(0) => {
                return Err(io::Error::new(
                    io::ErrorKind::UnexpectedEof,
                    "client closed without request",
                ))
            }
            Ok(n) => {
                incoming.buf.extend_from_slice(&chunk[..n]);
                if incoming.buf.len() > MAX_REQUEST_BYTES {
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidData,
                        "request too large",
                    ));
                }
                if incoming.buf.contains(&b'\n') {
                    break;
                }
            }
            Err(e) if e.kind() == io::ErrorKind::WouldBlock => break,
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        }
    }
    match incoming.buf.iter().position(|b| *b == b'\n') {
        Some(pos) => Ok(Some(
            String::from_utf8_lossy(&incoming.buf[..pos])
                .trim()
                .to_string(),
        )),
        None => Ok(None),
    }
}

fn respond(stream: &mut UnixStream, status: &YieldStatus) {
    let _ = stream.write_all(status.encode().as_bytes());
    let _ = stream.flush();
    let _ = stream.shutdown(Shutdown::Write);
}

pub fn client_yield(path: &Path, timeout: Duration) -> YieldStatus {
    let deadline = Instant::now() + timeout;
    let mut stream = match connect_with_deadline(path, deadline) {
        Ok(stream) => stream,
        Err(e) => return YieldStatus::Error(format!("connect {}: {e}", path.display())),
    };
    if let Err(e) = write_all_deadline(&mut stream, b"yield\n", deadline) {
        return YieldStatus::Error(format!("send yield: {e}"));
    }
    let _ = stream.shutdown(Shutdown::Write);
    match read_line_deadline(&mut stream, deadline, MAX_RESPONSE_BYTES) {
        Ok(line) => match YieldStatus::parse(&line) {
            Ok(status) => status,
            Err(e) => YieldStatus::Error(e),
        },
        Err(e) => YieldStatus::Error(format!("read response: {e}")),
    }
}

fn connect_with_deadline(path: &Path, deadline: Instant) -> io::Result<UnixStream> {
    use std::os::fd::{FromRawFd, OwnedFd};

    let bytes = path.as_os_str().as_bytes();
    if bytes.is_empty() || bytes.len() > 107 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "invalid unix socket path length",
        ));
    }
    let fd = unsafe {
        libc::socket(
            libc::AF_UNIX,
            libc::SOCK_STREAM | libc::SOCK_CLOEXEC | libc::SOCK_NONBLOCK,
            0,
        )
    };
    if fd < 0 {
        return Err(io::Error::last_os_error());
    }
    let mut addr: libc::sockaddr_un = unsafe { std::mem::zeroed() };
    addr.sun_family = libc::AF_UNIX as libc::sa_family_t;
    unsafe {
        std::ptr::copy_nonoverlapping(
            bytes.as_ptr(),
            addr.sun_path.as_mut_ptr() as *mut u8,
            bytes.len(),
        );
    }
    let addr_len = (std::mem::size_of::<libc::sa_family_t>() + bytes.len() + 1) as libc::socklen_t;
    let rc = unsafe { libc::connect(fd, &addr as *const _ as *const libc::sockaddr, addr_len) };
    if rc != 0 {
        let err = io::Error::last_os_error();
        let in_progress = matches!(
            err.raw_os_error(),
            Some(libc::EINPROGRESS) | Some(libc::EAGAIN) | Some(libc::EINTR)
        );
        if !in_progress {
            unsafe {
                libc::close(fd);
            }
            return Err(err);
        }
        let mut pfd = libc::pollfd {
            fd,
            events: libc::POLLOUT,
            revents: 0,
        };
        let rc = unsafe { libc::poll(&mut pfd, 1, remaining_ms(deadline)) };
        if rc == 0 {
            unsafe {
                libc::close(fd);
            }
            return Err(io::Error::new(io::ErrorKind::TimedOut, "connect timed out"));
        }
        if rc < 0 {
            let err = io::Error::last_os_error();
            unsafe {
                libc::close(fd);
            }
            return Err(err);
        }
        let mut socket_error: libc::c_int = 0;
        let mut len = std::mem::size_of::<libc::c_int>() as libc::socklen_t;
        let rc = unsafe {
            libc::getsockopt(
                fd,
                libc::SOL_SOCKET,
                libc::SO_ERROR,
                &mut socket_error as *mut _ as *mut libc::c_void,
                &mut len,
            )
        };
        if rc != 0 {
            let err = io::Error::last_os_error();
            unsafe {
                libc::close(fd);
            }
            return Err(err);
        }
        if socket_error != 0 {
            unsafe {
                libc::close(fd);
            }
            return Err(io::Error::from_raw_os_error(socket_error));
        }
    }
    let owned = unsafe { OwnedFd::from_raw_fd(fd) };
    Ok(UnixStream::from(owned))
}

fn remaining_ms(deadline: Instant) -> i32 {
    let now = Instant::now();
    if now >= deadline {
        return 0;
    }
    deadline
        .duration_since(now)
        .as_millis()
        .min(i32::MAX as u128) as i32
}

fn write_all_deadline(stream: &mut UnixStream, bytes: &[u8], deadline: Instant) -> io::Result<()> {
    stream.set_nonblocking(false)?;
    let remaining = deadline.saturating_duration_since(Instant::now());
    if remaining.is_zero() {
        return Err(io::Error::new(
            io::ErrorKind::TimedOut,
            "write deadline elapsed",
        ));
    }
    stream.set_write_timeout(Some(remaining))?;
    stream.write_all(bytes)
}

fn read_line_deadline(
    stream: &mut UnixStream,
    deadline: Instant,
    max_bytes: usize,
) -> io::Result<String> {
    let mut buf: Vec<u8> = Vec::new();
    let mut chunk = [0u8; 64];
    loop {
        if let Some(pos) = buf.iter().position(|b| *b == b'\n') {
            return Ok(String::from_utf8_lossy(&buf[..pos]).trim().to_string());
        }
        if buf.len() >= max_bytes {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "response too large",
            ));
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "response deadline elapsed",
            ));
        }
        stream.set_read_timeout(Some(remaining))?;
        match stream.read(&mut chunk) {
            Ok(0) => {
                return Err(io::Error::new(
                    io::ErrorKind::UnexpectedEof,
                    "daemon closed without response",
                ))
            }
            Ok(n) => buf.extend_from_slice(&chunk[..n]),
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return Err(e),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::os::unix::fs::FileTypeExt;
    use std::sync::atomic::{AtomicU64, Ordering};

    static COUNTER: AtomicU64 = AtomicU64::new(0);

    fn temp_socket_path() -> PathBuf {
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        let dir = std::env::temp_dir().join(format!(
            "premouth-test-{}-{}-{}",
            std::process::id(),
            n,
            crate::pacing::monotonic_ns()
        ));
        dir.join("handoff.sock")
    }

    #[test]
    fn status_roundtrip() {
        for status in [
            YieldStatus::Released {
                black_flushed: true,
                closefb_ok: true,
            },
            YieldStatus::Released {
                black_flushed: false,
                closefb_ok: true,
            },
            YieldStatus::AlreadyReleased {
                black_flushed: true,
                closefb_ok: false,
            },
            YieldStatus::Cancelled,
            YieldStatus::Busy,
            YieldStatus::Error("boom happened".to_string()),
        ] {
            let encoded = status.encode();
            let parsed = YieldStatus::parse(&encoded).unwrap();
            assert_eq!(parsed, status);
        }
    }

    #[test]
    fn exit_codes_distinguish_failure() {
        assert_eq!(
            YieldStatus::Released {
                black_flushed: true,
                closefb_ok: true
            }
            .exit_code(),
            0
        );
        assert_eq!(
            YieldStatus::Released {
                black_flushed: false,
                closefb_ok: true
            }
            .exit_code(),
            3
        );
        assert_eq!(YieldStatus::Cancelled.exit_code(), 0);
    }

    #[test]
    fn bind_creates_root_only_socket() {
        let path = temp_socket_path();
        let server = HandoffServer::bind(&path).unwrap();
        let meta = fs::symlink_metadata(&path).unwrap();
        assert!(meta.file_type().is_socket());
        use std::os::unix::fs::MetadataExt;
        assert_eq!(meta.mode() & 0o777, 0o600);
        drop(server);
        assert!(!path.exists());
    }

    #[test]
    fn bind_refuses_live_daemon_socket_and_recovers_after_close() {
        let path = temp_socket_path();
        let server = HandoffServer::bind(&path).unwrap();
        let second = HandoffServer::bind(&path);
        assert!(second.is_err());
        drop(server);
        let third = HandoffServer::bind(&path).unwrap();
        drop(third);
        let _ = fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn bind_preserves_existing_parent_permissions() {
        let path = temp_socket_path();
        let parent = path.parent().unwrap();
        fs::create_dir_all(parent).unwrap();
        fs::set_permissions(parent, fs::Permissions::from_mode(0o751)).unwrap();
        let server = HandoffServer::bind(&path).unwrap();
        assert_eq!(
            fs::metadata(parent).unwrap().permissions().mode() & 0o777,
            0o751
        );
        drop(server);
        let _ = fs::remove_dir_all(parent);
    }

    #[test]
    fn yield_client_receives_final_release_status() {
        let path = temp_socket_path();
        let mut server = HandoffServer::bind(&path).unwrap();
        let client_path = path.clone();
        let handle = std::thread::spawn(move || client_yield(&client_path, Duration::from_secs(5)));
        let deadline = std::time::Instant::now() + Duration::from_secs(5);
        while !server.request_pending() && std::time::Instant::now() < deadline {
            server.tick();
            std::thread::sleep(Duration::from_millis(2));
        }
        assert!(server.request_pending(), "yield request should arrive");
        server.set_final(YieldStatus::Released {
            black_flushed: true,
            closefb_ok: true,
        });
        let status = handle.join().unwrap();
        assert_eq!(
            status,
            YieldStatus::Released {
                black_flushed: true,
                closefb_ok: true
            }
        );
        server.tick();
        let second_path = path.clone();
        let second_handle =
            std::thread::spawn(move || client_yield(&second_path, Duration::from_secs(5)));
        while !second_handle.is_finished() {
            server.tick();
            std::thread::sleep(Duration::from_millis(2));
        }
        let second = second_handle.join().unwrap();
        assert_eq!(
            second,
            YieldStatus::AlreadyReleased {
                black_flushed: true,
                closefb_ok: true
            }
        );
        let _ = fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn partial_request_is_buffered_until_newline() {
        let path = temp_socket_path();
        let mut server = HandoffServer::bind(&path).unwrap();
        let mut client = UnixStream::connect(&path).unwrap();
        client.write_all(b"yi").unwrap();
        client.flush().unwrap();
        server.tick();
        assert!(!server.request_pending(), "partial request must not count");
        client.write_all(b"eld\n").unwrap();
        client.flush().unwrap();
        client.shutdown(Shutdown::Write).unwrap();
        server.tick();
        assert!(server.request_pending(), "completed request must count");
        server.set_final(YieldStatus::Released {
            black_flushed: true,
            closefb_ok: true,
        });
        let _ = client.set_read_timeout(Some(Duration::from_secs(2)));
        let mut response = String::new();
        client.read_to_string(&mut response).unwrap();
        assert_eq!(
            YieldStatus::parse(&response).unwrap(),
            YieldStatus::Released {
                black_flushed: true,
                closefb_ok: true
            }
        );
        let _ = fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn yield_client_times_out_without_response() {
        let path = temp_socket_path();
        let _server = HandoffServer::bind(&path).unwrap();
        let started = Instant::now();
        let status = client_yield(&path, Duration::from_millis(200));
        assert!(
            matches!(status, YieldStatus::Error(_)),
            "expected bounded error"
        );
        assert!(started.elapsed() < Duration::from_secs(2));
        let _ = fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn yield_client_fails_fast_without_daemon() {
        let path = temp_socket_path();
        let started = Instant::now();
        let status = client_yield(&path, Duration::from_millis(200));
        assert!(matches!(status, YieldStatus::Error(_)));
        assert!(started.elapsed() < Duration::from_secs(1));
    }
}
