use std::io;
use std::os::fd::{AsFd, AsRawFd};

#[repr(C)]
#[derive(Debug, Clone, Copy, Default)]
pub struct DrmModeFbCmd2 {
    pub fb_id: u32,
    pub width: u32,
    pub height: u32,
    pub pixel_format: u32,
    pub flags: u32,
    pub handles: [u32; 4],
    pub pitches: [u32; 4],
    pub offsets: [u32; 4],
    pub modifier: [u64; 4],
}

impl DrmModeFbCmd2 {
    pub fn single(width: u32, height: u32, pixel_format: u32, pitch: u32, handle: u32) -> Self {
        DrmModeFbCmd2 {
            fb_id: 0,
            width,
            height,
            pixel_format,
            flags: 0,
            handles: [handle, 0, 0, 0],
            pitches: [pitch, 0, 0, 0],
            offsets: [0; 4],
            // Without FB_MODIFIERS, every modifier must be zero. The kernel
            // also rejects nonzero modifiers for unused planes.
            modifier: [0; 4],
        }
    }
}

#[repr(C)]
#[derive(Debug, Clone, Copy, Default)]
pub struct DrmModeClosefb {
    pub fb_id: u32,
    pub pad: u32,
}

const fn drm_iowr(nr: u32, size: u32) -> libc::c_ulong {
    ((3u32 << 30) | (size << 16) | ((b'd' as u32) << 8) | nr) as libc::c_ulong
}

pub const DRM_IOCTL_MODE_ADDFB2: libc::c_ulong =
    drm_iowr(0xB8, std::mem::size_of::<DrmModeFbCmd2>() as u32);
pub const DRM_IOCTL_MODE_CLOSEFB: libc::c_ulong =
    drm_iowr(0xD0, std::mem::size_of::<DrmModeClosefb>() as u32);

pub fn add_fb2<F: AsFd>(device: &F, cmd: &mut DrmModeFbCmd2) -> io::Result<u32> {
    ioctl(device, DRM_IOCTL_MODE_ADDFB2, cmd)?;
    Ok(cmd.fb_id)
}

pub fn closefb<F: AsFd>(device: &F, fb_id: u32, pad: u32) -> io::Result<()> {
    let mut req = DrmModeClosefb { fb_id, pad };
    ioctl(device, DRM_IOCTL_MODE_CLOSEFB, &mut req)
}

fn ioctl<T>(device: &impl AsFd, request: libc::c_ulong, arg: &mut T) -> io::Result<()> {
    // musl declares the request as int; glibc uses unsigned long. Preserve
    // the ioctl bits while letting libc choose the ABI argument type.
    let rc = unsafe { libc::ioctl(device.as_fd().as_raw_fd(), request as _, arg as *mut T) };
    if rc < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn closefb_encoding_matches_this_kernel_uapi() {
        assert_eq!(DRM_IOCTL_MODE_CLOSEFB, 0xC008_64D0);
        assert_eq!(std::mem::size_of::<DrmModeClosefb>(), 8);
        assert_eq!(std::mem::offset_of!(DrmModeClosefb, fb_id), 0);
        assert_eq!(std::mem::offset_of!(DrmModeClosefb, pad), 4);
    }

    #[test]
    fn addfb2_encoding_and_layout() {
        assert_eq!(DRM_IOCTL_MODE_ADDFB2, 0xC068_64B8);
        assert_eq!(std::mem::size_of::<DrmModeFbCmd2>(), 104);
        assert_eq!(std::mem::offset_of!(DrmModeFbCmd2, handles), 20);
        assert_eq!(std::mem::offset_of!(DrmModeFbCmd2, pitches), 36);
        assert_eq!(std::mem::offset_of!(DrmModeFbCmd2, offsets), 52);
        assert_eq!(std::mem::offset_of!(DrmModeFbCmd2, modifier), 72);
    }

    #[test]
    fn single_builds_argb_single_plane_framebuffer() {
        let cmd = DrmModeFbCmd2::single(1080, 2220, 0x34325241, 4320, 7);
        assert_eq!(cmd.handles[0], 7);
        assert_eq!(cmd.pitches[0], 4320);
        assert_eq!(cmd.flags, 0);
        assert_eq!(cmd.modifier, [0; 4]);
        assert_eq!(cmd.handles[1..], [0, 0, 0]);
    }
}
