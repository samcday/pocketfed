use std::io;
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd, RawFd};
use std::sync::atomic::{AtomicI32, Ordering};

static WRITE_FD: AtomicI32 = AtomicI32::new(-1);

pub struct Signals {
    read: OwnedFd,
    write: OwnedFd,
}

impl Signals {
    pub fn install() -> io::Result<Self> {
        let mut fds = [0i32; 2];
        let rc = unsafe { libc::pipe2(fds.as_mut_ptr(), libc::O_CLOEXEC | libc::O_NONBLOCK) };
        if rc != 0 {
            return Err(io::Error::last_os_error());
        }
        let read = unsafe { OwnedFd::from_raw_fd(fds[0]) };
        let write = unsafe { OwnedFd::from_raw_fd(fds[1]) };
        WRITE_FD.store(write.as_raw_fd(), Ordering::SeqCst);
        let mut action: libc::sigaction = unsafe { std::mem::zeroed() };
        action.sa_sigaction = handler as *const () as libc::sighandler_t;
        action.sa_flags = libc::SA_RESTART;
        for sig in [libc::SIGTERM, libc::SIGINT, libc::SIGHUP] {
            let rc = unsafe { libc::sigaction(sig, &action, std::ptr::null_mut()) };
            if rc != 0 {
                WRITE_FD.store(-1, Ordering::SeqCst);
                return Err(io::Error::last_os_error());
            }
        }
        unsafe {
            libc::signal(libc::SIGPIPE, libc::SIG_IGN);
        }
        Ok(Signals { read, write })
    }

    pub fn read_fd(&self) -> RawFd {
        self.read.as_raw_fd()
    }

    pub fn pending(&mut self) -> bool {
        let mut buf = [0u8; 64];
        let mut seen = false;
        loop {
            let n = unsafe {
                libc::read(
                    self.read.as_raw_fd(),
                    buf.as_mut_ptr() as *mut libc::c_void,
                    buf.len(),
                )
            };
            if n > 0 {
                seen = true;
                continue;
            }
            break;
        }
        seen
    }
}

impl Drop for Signals {
    fn drop(&mut self) {
        WRITE_FD.store(-1, Ordering::SeqCst);
        let _ = &self.write;
    }
}

extern "C" fn handler(_sig: libc::c_int) {
    let fd = WRITE_FD.load(Ordering::Relaxed);
    if fd >= 0 {
        let byte = [1u8];
        unsafe {
            libc::write(fd, byte.as_ptr() as *const libc::c_void, 1);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn installs_and_drains() {
        let mut signals = Signals::install().unwrap();
        assert!(!signals.pending());
        unsafe {
            libc::raise(libc::SIGTERM);
        }
        std::thread::sleep(std::time::Duration::from_millis(20));
        assert!(signals.pending());
        assert!(!signals.pending());
    }
}
