use std::fmt;
use std::fs;
use std::io;
use std::os::fd::{AsFd, BorrowedFd};
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};

use drm::buffer::Buffer as _;
use drm::control::{connector, crtc, framebuffer, Device as ControlDevice};
use drm::Device as BasicDevice;

use crate::dissolve::{Dissolve, Rect, PROGRESS_ONE};
use crate::drm_uapi;
use crate::handoff::{HandoffServer, YieldStatus};
use crate::image::{fill_pitched_from_frame, Frame};
use crate::pacing::{
    monotonic_ns, progress_from_elapsed, sleep_ms, Clock, MonotonicClock, Schedule,
};
use crate::signals::Signals;
use crate::stats::RunStats;
use crate::systemd;

pub struct Card(fs::File);

impl AsFd for Card {
    fn as_fd(&self) -> BorrowedFd<'_> {
        self.0.as_fd()
    }
}

impl BasicDevice for Card {}
impl ControlDevice for Card {}

impl Card {
    pub fn open(path: &Path) -> io::Result<Self> {
        let file = fs::OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(libc::O_CLOEXEC)
            .open(path)?;
        Ok(Card(file))
    }
}

pub fn drm_driver_name(card: &Card) -> io::Result<String> {
    let driver = card.get_driver()?;
    Ok(driver.name().to_string_lossy().into_owned())
}

pub fn find_simpledrm_card() -> Option<PathBuf> {
    let index = select_simpledrm_card_index(Path::new("/sys/class/drm"))?;
    Some(PathBuf::from(format!("/dev/dri/card{index}")))
}

pub fn select_simpledrm_card_index(drm_class: &Path) -> Option<u32> {
    let entries = fs::read_dir(drm_class).ok()?;
    let mut best: Option<u32> = None;
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        let index = match name
            .strip_prefix("card")
            .and_then(|rest| rest.parse::<u32>().ok())
        {
            Some(index) => index,
            None => continue,
        };
        let device = entry.path().join("device");
        let matches = sysfs_device_driver(&device)
            .as_deref()
            .map(is_simplefb_platform_driver)
            .unwrap_or(false);
        if !matches {
            continue;
        }
        if best.map_or(true, |current| index < current) {
            best = Some(index);
        }
    }
    best
}

fn sysfs_device_driver(device: &Path) -> Option<String> {
    if let Some(name) = fs::read_link(device.join("driver"))
        .ok()
        .and_then(|p| p.file_name().map(|n| n.to_string_lossy().into_owned()))
    {
        return Some(name);
    }
    fs::read_to_string(device.join("uevent"))
        .ok()?
        .lines()
        .find_map(|line| line.trim().strip_prefix("DRIVER=").map(str::to_string))
}

fn is_simplefb_platform_driver(name: &str) -> bool {
    name == "simple-framebuffer" || name == "simpledrm"
}

pub fn select_mode_index(sizes: &[(u32, u32)], want: (u32, u32)) -> Option<usize> {
    sizes.iter().position(|size| *size == want)
}

#[derive(Debug, Clone, Copy)]
pub struct SessionParams {
    pub duration_ns: u64,
    pub fps: u32,
    pub band_px: u32,
    pub guard_timeout_ns: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum GuardExit {
    Replacement,
    Disabled,
    Removed,
    Timeout,
    TransientErrors,
    Skipped,
}

impl fmt::Display for GuardExit {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let text = match self {
            GuardExit::Replacement => "replacement",
            GuardExit::Disabled => "disabled",
            GuardExit::Removed => "removed",
            GuardExit::Timeout => "timeout",
            GuardExit::TransientErrors => "transient-errors",
            GuardExit::Skipped => "skipped",
        };
        f.write_str(text)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DisplayOutcome {
    NoDevice,
    Cancelled,
    Released {
        black_flushed: bool,
        closefb_ok: bool,
        guard: GuardExit,
    },
    ReleaseFailed {
        black_flushed: bool,
        closefb_ok: bool,
        reason: String,
    },
    Aborted(String),
}

pub fn release_ack(
    master_released: bool,
    black_flushed: bool,
    closefb_ok: bool,
) -> Option<YieldStatus> {
    master_released.then_some(YieldStatus::Released {
        black_flushed,
        closefb_ok,
    })
}

pub fn run_display(
    card: &Card,
    frame: &Frame,
    params: &SessionParams,
    stats: &mut RunStats,
    signals: &mut Signals,
    handoff: &mut HandoffServer,
) -> Result<DisplayOutcome, String> {
    stats.cpu_start_ns = crate::pacing::process_cpu_ns();

    match card.acquire_master_lock() {
        Ok(()) => {}
        Err(e) => {
            return Ok(DisplayOutcome::Aborted(format!(
                "cannot acquire DRM master (another master may own this device): {e}"
            )))
        }
    }

    handoff.tick();
    if handoff.request_pending() {
        return Ok(cancel_after_master(card, handoff));
    }

    let resources = card
        .resource_handles()
        .map_err(|e| format!("GETRESOURCES: {e}"))?;

    let mut chosen = None;
    for &handle in resources.connectors() {
        if let Ok(info) = card.get_connector(handle, true) {
            if matches!(info.state(), connector::State::Connected) {
                chosen = Some((handle, info));
                break;
            }
        }
    }
    let (connector_handle, connector_info) = match chosen {
        Some(value) => value,
        None => return Ok(DisplayOutcome::NoDevice),
    };

    let modes = connector_info.modes().to_vec();
    let sizes: Vec<(u32, u32)> = modes
        .iter()
        .map(|mode| {
            let (w, h) = mode.size();
            (w as u32, h as u32)
        })
        .collect();
    let mode_index =
        select_mode_index(&sizes, (frame.width(), frame.height())).ok_or_else(|| {
            format!(
                "connector modes {sizes:?} do not match captured image {}x{}",
                frame.width(),
                frame.height()
            )
        })?;
    let mode = modes[mode_index].clone();

    let mut crtc_handle = None;
    for &encoder_handle in connector_info.encoders() {
        if let Ok(encoder) = card.get_encoder(encoder_handle) {
            let possible = resources.filter_crtcs(encoder.possible_crtcs());
            if let Some(active) = encoder.crtc() {
                if possible.contains(&active) {
                    crtc_handle = Some(active);
                    break;
                }
            }
            if let Some(&first) = possible.first() {
                crtc_handle = Some(first);
                break;
            }
        }
    }
    let crtc_handle =
        crtc_handle.ok_or_else(|| "no CRTC compatible with the connected connector".to_string())?;

    match drm_uapi::closefb(card, 0, 0) {
        Err(e) if e.raw_os_error() == Some(libc::ENOENT) => {
            stats.closefb_probe = "enoent-implemented".to_string();
        }
        Err(e) => {
            return Ok(DisplayOutcome::Aborted(format!(
                "DRM_IOCTL_MODE_CLOSEFB not usable ({e}); refusing to modeset"
            )))
        }
        Ok(()) => {
            stats.closefb_probe = "unexpected-ok".to_string();
        }
    }

    handoff.tick();
    if handoff.request_pending() {
        return Ok(cancel_after_master(card, handoff));
    }

    // SimpleDRM normalizes ARGB8888 to XRGB8888 in its fourcc list, and
    // ADDFB2 rejects a format no plane advertises. Both PixelFormat values
    // are byte-compatible in RGB order, so scan out non-alpha XRGB8888
    // whatever alpha convention the captured frame carries.
    let scanout_format = drm::buffer::DrmFourcc::Xrgb8888;
    eprintln!(
        "premouth: capture {} scanout XRGB8888",
        frame.format().name()
    );
    let mut dumb =
        match card.create_dumb_buffer((frame.width(), frame.height()), scanout_format, 32) {
            Ok(dumb) => dumb,
            Err(e) => {
                return Ok(DisplayOutcome::Aborted(format!(
                    "CREATE_DUMB {}x{}: {e}",
                    frame.width(),
                    frame.height()
                )))
            }
        };
    let pitch = dumb.pitch() as usize;
    let buffer_handle = dumb.handle();
    if (pitch as u64) < frame.width() as u64 * 4 {
        let _ = card.destroy_dumb_buffer(dumb);
        return Ok(DisplayOutcome::Aborted(format!(
            "dumb buffer pitch {pitch} smaller than visible row"
        )));
    }

    let mut mapping = match card.map_dumb_buffer(&mut dumb) {
        Ok(mapping) => mapping,
        Err(e) => {
            return Ok(DisplayOutcome::Aborted(format!("MAP_DUMB: {e}")));
        }
    };
    if let Err(e) = fill_pitched_from_frame(mapping.as_mut(), pitch, frame) {
        drop(mapping);
        let _ = card.destroy_dumb_buffer(dumb);
        return Ok(DisplayOutcome::Aborted(format!("initial frame init: {e}")));
    }

    let mut cmd = drm_uapi::DrmModeFbCmd2::single(
        frame.width(),
        frame.height(),
        scanout_format as u32,
        pitch as u32,
        u32::from(buffer_handle),
    );
    let fb_id = match drm_uapi::add_fb2(card, &mut cmd) {
        Ok(fb_id) => fb_id,
        Err(e) => {
            drop(mapping);
            let _ = card.destroy_dumb_buffer(dumb);
            return Ok(DisplayOutcome::Aborted(format!("ADDFB2: {e}")));
        }
    };
    let fb_handle = match drm::control::from_u32::<framebuffer::Handle>(fb_id) {
        Some(handle) => handle,
        None => {
            let _ = drm_uapi::closefb(card, fb_id, 0);
            drop(mapping);
            let _ = card.destroy_dumb_buffer(dumb);
            return Ok(DisplayOutcome::Aborted(
                "ADDFB2 returned fb_id 0".to_string(),
            ));
        }
    };

    if let Err(e) = card.set_crtc(
        crtc_handle,
        Some(fb_handle),
        (0, 0),
        &[connector_handle],
        Some(mode),
    ) {
        let _ = card.destroy_framebuffer(fb_handle);
        drop(mapping);
        let _ = card.destroy_dumb_buffer(dumb);
        if !drop_master_with_retry(card) {
            eprintln!(
                "premouth: DROP_MASTER failed during SETCRTC abort; fd close releases master"
            );
        }
        return Ok(DisplayOutcome::Aborted(format!("SETCRTC: {e}")));
    }

    systemd::ready("initial framebuffer on scanout");

    let mut dissolve = Dissolve::new(
        frame.width(),
        frame.height(),
        params.band_px,
        frame.format(),
    );
    let start = monotonic_ns();
    let mut schedule = Schedule::new(start, params.fps);
    let clock = MonotonicClock;
    stats.anim_start_ns = start;

    loop {
        handoff.tick();
        if handoff.request_pending() {
            break;
        }
        if signals.pending() {
            eprintln!("premouth: signal received; dissolving and yielding");
            break;
        }
        let now = clock.now_ns();
        if let Some(tick) = schedule.advance(now) {
            stats.frames_due += 1;
            stats.ticks_skipped += tick.skipped;
            let progress = progress_from_elapsed(now.saturating_sub(start), params.duration_ns);
            let started = monotonic_ns();
            let erased = dissolve.erase_to(mapping.as_mut(), pitch, progress);
            let rects = dissolve.pending_rects();
            let submit_ok = if rects.is_empty() {
                true
            } else {
                submit_damage(card, fb_handle, &rects, stats)
            };
            let elapsed = monotonic_ns().saturating_sub(started);
            stats.update_time_ns_total = stats.update_time_ns_total.saturating_add(elapsed);
            stats.update_time_ns_max = stats.update_time_ns_max.max(elapsed);
            stats.pixels_erased = stats.pixels_erased.saturating_add(erased.pixels_erased);
            stats.frames_rendered += 1;
            if !submit_ok {
                stats.updates_failed += 1;
            }
            dissolve.commit(submit_ok);
            if progress >= PROGRESS_ONE {
                break;
            }
        }
        let timeout = schedule.timeout_ms(clock.now_ns());
        poll_wait(&[handoff.poll_fd(), signals.read_fd()], timeout);
    }

    stats.anim_end_ns = monotonic_ns();
    systemd::status("dissolving final black");
    ensure_final_black(
        card,
        &mut dissolve,
        mapping.as_mut(),
        pitch,
        fb_handle,
        stats,
    );

    let mut closefb_ok = false;
    match drm_uapi::closefb(card, fb_id, 0) {
        Ok(()) => closefb_ok = true,
        Err(e) if e.raw_os_error() == Some(libc::ENOENT) => closefb_ok = true,
        Err(e) => {
            eprintln!("premouth: CLOSEFB failed ({e}); retaining framebuffer ownership");
        }
    }
    stats.closefb_ok = closefb_ok;

    let master_released = drop_master_with_retry(card);
    if let Some(status) = release_ack(master_released, stats.black_flushed, closefb_ok) {
        handoff.set_final(status);
    } else {
        eprintln!("premouth: DROP_MASTER failed after bounded retries; not acknowledging release");
        handoff.set_final(YieldStatus::Error("DROP_MASTER failed".to_string()));
        stats.guard_exit = "drop-master-failed".to_string();
        drop(mapping);
        stats.cpu_end_ns = crate::pacing::process_cpu_ns();
        return Ok(DisplayOutcome::ReleaseFailed {
            black_flushed: stats.black_flushed,
            closefb_ok,
            reason: "DROP_MASTER failed".to_string(),
        });
    }

    drop(mapping);

    let guard = if params.guard_timeout_ns == 0 {
        GuardExit::Skipped
    } else {
        guard_loop(
            card,
            crtc_handle,
            fb_id,
            params.guard_timeout_ns,
            signals,
            handoff,
        )
    };
    stats.guard_exit = guard.to_string();

    if closefb_ok {
        let _ = card.destroy_dumb_buffer(dumb);
    }
    stats.cpu_end_ns = crate::pacing::process_cpu_ns();

    Ok(DisplayOutcome::Released {
        black_flushed: stats.black_flushed,
        closefb_ok,
        guard,
    })
}

fn cancel_after_master(card: &Card, handoff: &mut HandoffServer) -> DisplayOutcome {
    if drop_master_with_retry(card) {
        handoff.set_final(YieldStatus::Cancelled);
        DisplayOutcome::Cancelled
    } else {
        let reason = "DROP_MASTER failed during startup cancellation".to_string();
        handoff.set_final(YieldStatus::Error(reason.clone()));
        DisplayOutcome::ReleaseFailed {
            black_flushed: false,
            closefb_ok: true,
            reason,
        }
    }
}

fn drop_master_with_retry(card: &Card) -> bool {
    for attempt in 0..3u32 {
        match card.release_master_lock() {
            Ok(()) => return true,
            Err(e) => {
                eprintln!("premouth: DROP_MASTER attempt {} failed: {e}", attempt + 1);
                if attempt < 2 {
                    sleep_ms(20);
                }
            }
        }
    }
    false
}

fn ensure_final_black(
    card: &Card,
    dissolve: &mut Dissolve,
    buf: &mut [u8],
    pitch: usize,
    fb_handle: framebuffer::Handle,
    stats: &mut RunStats,
) {
    let (_, all_black) = dissolve.ensure_black(buf, pitch);
    let mut attempts = 0u32;
    loop {
        let rects = dissolve.pending_rects();
        if rects.is_empty() {
            stats.black_flushed = all_black;
            return;
        }
        let ok = submit_damage(card, fb_handle, &rects, stats);
        dissolve.commit(ok);
        if ok {
            stats.black_flushed = all_black;
            return;
        }
        stats.updates_failed += 1;
        attempts += 1;
        if attempts >= 3 {
            eprintln!(
                "premouth: final black damage was not flushed after {attempts} attempts; reporting failure"
            );
            stats.black_flushed = false;
            return;
        }
        sleep_ms(30);
    }
}

fn submit_damage(
    card: &Card,
    fb_handle: framebuffer::Handle,
    rects: &[Rect],
    stats: &mut RunStats,
) -> bool {
    let clips: Vec<drm::control::ClipRect> = rects
        .iter()
        .map(|r| drm::control::ClipRect::new(r.x1, r.y1, r.x2, r.y2))
        .collect();
    let bytes: u64 = rects.iter().map(|r| r.area() * 4).sum();
    match card.dirty_framebuffer(fb_handle, &clips) {
        Ok(()) => {
            stats.updates_submitted += 1;
            stats.rects_submitted += clips.len() as u64;
            stats.damage_bytes_submitted = stats.damage_bytes_submitted.saturating_add(bytes);
            true
        }
        Err(e) => {
            eprintln!("premouth: DIRTYFB failed: {e}");
            false
        }
    }
}

fn guard_loop(
    card: &Card,
    crtc_handle: crtc::Handle,
    our_fb_id: u32,
    timeout_ns: u64,
    signals: &mut Signals,
    handoff: &mut HandoffServer,
) -> GuardExit {
    let start = monotonic_ns();
    let mut transient = 0u64;
    loop {
        handoff.tick();
        let _ = signals.pending();
        match card.get_crtc(crtc_handle) {
            Ok(info) => match info.framebuffer() {
                Some(fb) if u32::from(fb) != our_fb_id => return GuardExit::Replacement,
                Some(_) => {}
                None => return GuardExit::Disabled,
            },
            Err(e) => {
                if e.raw_os_error() == Some(libc::ENODEV) {
                    return GuardExit::Removed;
                }
                transient += 1;
            }
        }
        if monotonic_ns().saturating_sub(start) >= timeout_ns {
            return if transient > 0 {
                GuardExit::TransientErrors
            } else {
                GuardExit::Timeout
            };
        }
        poll_wait(&[handoff.poll_fd(), signals.read_fd()], 250);
    }
}

fn poll_wait(fds: &[i32], timeout_ms: i32) {
    let mut pollfds: Vec<libc::pollfd> = fds
        .iter()
        .filter(|fd| **fd >= 0)
        .map(|fd| libc::pollfd {
            fd: *fd,
            events: libc::POLLIN,
            revents: 0,
        })
        .collect();
    unsafe {
        libc::poll(
            pollfds.as_mut_ptr(),
            pollfds.len() as libc::nfds_t,
            timeout_ms,
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::symlink;
    use std::sync::atomic::{AtomicU64, Ordering};

    static COUNTER: AtomicU64 = AtomicU64::new(0);

    fn temp_dir(name: &str) -> PathBuf {
        let n = COUNTER.fetch_add(1, Ordering::SeqCst);
        let dir = std::env::temp_dir().join(format!(
            "premouth-drm-{}-{}-{}-{}",
            std::process::id(),
            n,
            crate::pacing::monotonic_ns(),
            name
        ));
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn mode_selection_requires_exact_match() {
        let sizes = [(1080u32, 2220u32), (720, 1280)];
        assert_eq!(select_mode_index(&sizes, (1080, 2220)), Some(0));
        assert_eq!(select_mode_index(&sizes, (720, 1280)), Some(1));
        assert_eq!(select_mode_index(&sizes, (1080, 1920)), None);
        assert_eq!(select_mode_index(&[], (1, 1)), None);
    }

    #[test]
    fn release_ack_requires_verified_master_drop() {
        assert!(release_ack(false, true, true).is_none());
        assert_eq!(
            release_ack(true, true, false),
            Some(YieldStatus::Released {
                black_flushed: true,
                closefb_ok: false
            })
        );
        assert_eq!(
            release_ack(true, false, true),
            Some(YieldStatus::Released {
                black_flushed: false,
                closefb_ok: true
            })
        );
    }

    #[test]
    fn synthetic_sysfs_selects_lowest_simplefb_card() {
        let base = temp_dir("sysfs-lowest");
        let card0 = base.join("card0/device");
        fs::create_dir_all(&card0).unwrap();
        symlink("msm", card0.join("driver")).unwrap();
        let card1 = base.join("card1/device");
        fs::create_dir_all(&card1).unwrap();
        symlink("simple-framebuffer", card1.join("driver")).unwrap();
        fs::create_dir_all(base.join("card1-DP-1")).unwrap();
        let card2 = base.join("card2/device");
        fs::create_dir_all(&card2).unwrap();
        fs::write(card2.join("uevent"), "DRIVER=simple-framebuffer\n").unwrap();
        let card3 = base.join("card3/device");
        fs::create_dir_all(&card3).unwrap();
        symlink("simpledrm", card3.join("driver")).unwrap();
        assert_eq!(select_simpledrm_card_index(&base), Some(1));
        let _ = fs::remove_dir_all(&base);
    }

    #[test]
    fn synthetic_sysfs_uevent_fallback_and_no_match() {
        let base = temp_dir("sysfs-uevent");
        let card4 = base.join("card4/device");
        fs::create_dir_all(&card4).unwrap();
        fs::write(card4.join("uevent"), "DRIVER=simple-framebuffer\n").unwrap();
        assert_eq!(select_simpledrm_card_index(&base), Some(4));
        let _ = fs::remove_dir_all(&base);

        let other = temp_dir("sysfs-none");
        let card0 = other.join("card0/device");
        fs::create_dir_all(&card0).unwrap();
        fs::write(card0.join("uevent"), "DRIVER=msm\n").unwrap();
        assert_eq!(select_simpledrm_card_index(&other), None);
        let _ = fs::remove_dir_all(&other);
    }

    #[test]
    fn guard_exit_display_names_are_stable() {
        assert_eq!(GuardExit::Replacement.to_string(), "replacement");
        assert_eq!(GuardExit::Removed.to_string(), "removed");
        assert_eq!(GuardExit::Skipped.to_string(), "skipped");
    }
}
