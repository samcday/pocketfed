use std::fs;
use std::path::Path;

use drm::buffer::DrmFourcc;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PixelFormat {
    Argb8888,
    Xrgb8888,
}

impl PixelFormat {
    pub const BYTES_PER_PIXEL: usize = 4;
    pub const OPAQUE_BLACK: u32 = 0xff00_0000;

    pub fn from_dt(name: &str) -> Option<Self> {
        match name.trim_end_matches('\0') {
            "a8r8g8b8" => Some(PixelFormat::Argb8888),
            "x8r8g8b8" => Some(PixelFormat::Xrgb8888),
            _ => None,
        }
    }

    pub fn drm_fourcc(self) -> DrmFourcc {
        match self {
            PixelFormat::Argb8888 => DrmFourcc::Argb8888,
            PixelFormat::Xrgb8888 => DrmFourcc::Xrgb8888,
        }
    }

    pub fn black(self) -> u32 {
        Self::OPAQUE_BLACK
    }

    pub fn name(self) -> &'static str {
        match self {
            PixelFormat::Argb8888 => "a8r8g8b8",
            PixelFormat::Xrgb8888 => "x8r8g8b8",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FrameOrigin {
    DevmemCapture,
    Fixture,
    Synthetic,
}

#[derive(Debug, Clone)]
pub struct Frame {
    width: u32,
    height: u32,
    stride: usize,
    format: PixelFormat,
    origin: FrameOrigin,
    detail: String,
    bytes: Vec<u8>,
}

impl Frame {
    pub fn new(
        width: u32,
        height: u32,
        stride: usize,
        format: PixelFormat,
        origin: FrameOrigin,
        detail: String,
        bytes: Vec<u8>,
    ) -> Result<Self, String> {
        let frame = Frame {
            width,
            height,
            stride,
            format,
            origin,
            detail,
            bytes,
        };
        frame.validate()?;
        Ok(frame)
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.width == 0 || self.height == 0 {
            return Err(format!("invalid frame size {}x{}", self.width, self.height));
        }
        let min_stride = (self.width as u64)
            .checked_mul(PixelFormat::BYTES_PER_PIXEL as u64)
            .ok_or_else(|| "frame width overflow".to_string())?;
        if self.stride as u64 % PixelFormat::BYTES_PER_PIXEL as u64 != 0 {
            return Err(format!("stride {} is not 4-byte aligned", self.stride));
        }
        if (self.stride as u64) < min_stride {
            return Err(format!(
                "stride {} smaller than visible width {}x4",
                self.stride, self.width
            ));
        }
        let want = (self.stride as u64)
            .checked_mul(self.height as u64)
            .ok_or_else(|| "frame span overflow".to_string())?;
        if self.bytes.len() as u64 != want {
            return Err(format!(
                "frame buffer is {} bytes, expected {} (stride*height)",
                self.bytes.len(),
                want
            ));
        }
        Ok(())
    }

    pub fn width(&self) -> u32 {
        self.width
    }

    pub fn height(&self) -> u32 {
        self.height
    }

    pub fn stride(&self) -> usize {
        self.stride
    }

    pub fn format(&self) -> PixelFormat {
        self.format
    }

    pub fn origin(&self) -> FrameOrigin {
        self.origin
    }

    pub fn detail(&self) -> &str {
        &self.detail
    }

    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub fn pixel(&self, x: u32, y: u32) -> u32 {
        let off = y as usize * self.stride + x as usize * 4;
        u32::from_ne_bytes(self.bytes[off..off + 4].try_into().unwrap())
    }
}

pub struct Framebuffer {
    width: u32,
    height: u32,
    pitch: usize,
    format: PixelFormat,
    bytes: Vec<u8>,
}

impl Framebuffer {
    pub fn zeroed(
        width: u32,
        height: u32,
        pitch: usize,
        format: PixelFormat,
    ) -> Result<Self, String> {
        if width == 0 || height == 0 {
            return Err(format!("invalid framebuffer size {}x{}", width, height));
        }
        let min_pitch = (width as u64)
            .checked_mul(4)
            .ok_or_else(|| "pitch width overflow".to_string())?;
        if pitch as u64 % 4 != 0 || (pitch as u64) < min_pitch {
            return Err(format!(
                "destination pitch {pitch} cannot hold width {width}"
            ));
        }
        let len = (pitch as u64)
            .checked_mul(height as u64)
            .ok_or_else(|| "pitch*height overflow".to_string())?;
        let len = usize::try_from(len).map_err(|_| "framebuffer too large".to_string())?;
        Ok(Framebuffer {
            width,
            height,
            pitch,
            format,
            bytes: vec![0u8; len],
        })
    }

    pub fn from_frame(frame: &Frame, pitch: usize) -> Result<Self, String> {
        let mut fb = Self::zeroed(frame.width(), frame.height(), pitch, frame.format())?;
        fill_pitched_from_frame(fb.as_mut_bytes(), pitch, frame)?;
        Ok(fb)
    }

    pub fn width(&self) -> u32 {
        self.width
    }

    pub fn height(&self) -> u32 {
        self.height
    }

    pub fn pitch(&self) -> usize {
        self.pitch
    }

    pub fn format(&self) -> PixelFormat {
        self.format
    }

    pub fn as_bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub fn as_mut_bytes(&mut self) -> &mut [u8] {
        &mut self.bytes
    }

    pub fn pixel(&self, x: u32, y: u32) -> u32 {
        let off = y as usize * self.pitch + x as usize * 4;
        u32::from_ne_bytes(self.bytes[off..off + 4].try_into().unwrap())
    }

    pub fn set_pixel(&mut self, x: u32, y: u32, value: u32) {
        let off = y as usize * self.pitch + x as usize * 4;
        self.bytes[off..off + 4].copy_from_slice(&value.to_ne_bytes());
    }
}

pub fn fill_pitched_from_frame(dst: &mut [u8], pitch: usize, frame: &Frame) -> Result<(), String> {
    if frame.width() == 0 || frame.height() == 0 {
        return Err("cannot fill from an empty frame".to_string());
    }
    let row_bytes = frame.width() as usize * 4;
    let required = (pitch as u64)
        .checked_mul(frame.height() as u64)
        .ok_or_else(|| "pitch*height overflow".to_string())?;
    if (dst.len() as u64) < required {
        return Err(format!(
            "destination is {} bytes, expected at least {} (pitch*height)",
            dst.len(),
            required
        ));
    }
    if pitch < row_bytes {
        return Err(format!(
            "destination pitch {pitch} smaller than {row_bytes}"
        ));
    }
    for y in 0..frame.height() as usize {
        let src = y * frame.stride();
        let dst_row = y * pitch;
        dst[dst_row..dst_row + row_bytes].copy_from_slice(&frame.bytes()[src..src + row_bytes]);
    }
    Ok(())
}

pub fn load_ppm(path: &Path) -> Result<Frame, String> {
    let data = fs::read(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let (width, height, rgb) = parse_ppm(&data)?;
    let stride = width as usize * 4;
    let mut bytes = vec![0u8; stride * height as usize];
    for i in 0..(width as usize * height as usize) {
        bytes[i * 4] = rgb[i * 3 + 2];
        bytes[i * 4 + 1] = rgb[i * 3 + 1];
        bytes[i * 4 + 2] = rgb[i * 3];
        bytes[i * 4 + 3] = 0xff;
    }
    Frame::new(
        width,
        height,
        stride,
        PixelFormat::Argb8888,
        FrameOrigin::Fixture,
        format!("ppm fixture {}", path.display()),
        bytes,
    )
}

fn parse_ppm(data: &[u8]) -> Result<(u32, u32, Vec<u8>), String> {
    let mut pos = 0usize;
    let magic = next_token(data, &mut pos).ok_or_else(|| "ppm: empty file".to_string())?;
    if magic != b"P6" {
        return Err(format!(
            "ppm: unsupported magic {:?} (only binary P6)",
            String::from_utf8_lossy(magic)
        ));
    }
    let width = parse_dec(next_token(data, &mut pos).ok_or("ppm: missing width")?)?;
    let height = parse_dec(next_token(data, &mut pos).ok_or("ppm: missing height")?)?;
    let maxval = parse_dec(next_token(data, &mut pos).ok_or("ppm: missing maxval")?)?;
    if width == 0 || height == 0 {
        return Err("ppm: zero dimension".to_string());
    }
    if maxval != 255 {
        return Err(format!("ppm: maxval {maxval} unsupported, need 255"));
    }
    if pos >= data.len() || !data[pos].is_ascii_whitespace() {
        return Err("ppm: missing separator before pixel data".to_string());
    }
    pos += 1;
    let need = (width as usize)
        .checked_mul(height as usize)
        .and_then(|p| p.checked_mul(3))
        .ok_or_else(|| "ppm: image too large".to_string())?;
    if data.len() - pos < need {
        return Err(format!(
            "ppm: truncated pixel data ({} bytes available, need {need})",
            data.len() - pos
        ));
    }
    Ok((width, height, data[pos..pos + need].to_vec()))
}

fn parse_dec(token: &[u8]) -> Result<u32, String> {
    let text = std::str::from_utf8(token).map_err(|_| "ppm: non-ascii integer".to_string())?;
    text.parse::<u32>()
        .map_err(|_| format!("ppm: bad integer {text:?}"))
}

fn next_token<'a>(data: &'a [u8], pos: &mut usize) -> Option<&'a [u8]> {
    loop {
        while *pos < data.len() && data[*pos].is_ascii_whitespace() {
            *pos += 1;
        }
        if *pos < data.len() && data[*pos] == b'#' {
            while *pos < data.len() && data[*pos] != b'\n' {
                *pos += 1;
            }
            continue;
        }
        break;
    }
    if *pos >= data.len() {
        return None;
    }
    let start = *pos;
    while *pos < data.len() && !data[*pos].is_ascii_whitespace() {
        *pos += 1;
    }
    Some(&data[start..*pos])
}

pub fn encode_ppm(frame: &Frame) -> Vec<u8> {
    let header = format!("P6\n{} {}\n255\n", frame.width(), frame.height());
    let mut out =
        Vec::with_capacity(header.len() + frame.width() as usize * frame.height() as usize * 3);
    out.extend_from_slice(header.as_bytes());
    for y in 0..frame.height() {
        for x in 0..frame.width() {
            let px = frame.pixel(x, y).to_ne_bytes();
            out.push(px[2]);
            out.push(px[1]);
            out.push(px[0]);
        }
    }
    out
}

pub fn write_ppm(path: &Path, frame: &Frame) -> Result<(), String> {
    fs::write(path, encode_ppm(frame)).map_err(|e| format!("write {}: {e}", path.display()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn sample_frame(stride: usize) -> Frame {
        let (w, h) = (3u32, 2u32);
        let mut bytes = vec![0u8; stride * h as usize];
        for y in 0..h as usize {
            for x in 0..w as usize {
                let v = (0xff00_0000u32) | ((y as u32) << 8) | x as u32;
                let off = y * stride + x * 4;
                bytes[off..off + 4].copy_from_slice(&v.to_ne_bytes());
            }
        }
        Frame::new(
            w,
            h,
            stride,
            PixelFormat::Argb8888,
            FrameOrigin::Synthetic,
            "test".to_string(),
            bytes,
        )
        .unwrap()
    }

    #[test]
    fn format_dt_names() {
        assert_eq!(
            PixelFormat::from_dt("a8r8g8b8"),
            Some(PixelFormat::Argb8888)
        );
        assert_eq!(
            PixelFormat::from_dt("x8r8g8b8"),
            Some(PixelFormat::Xrgb8888)
        );
        assert_eq!(
            PixelFormat::from_dt("a8r8g8b8\0"),
            Some(PixelFormat::Argb8888)
        );
        assert_eq!(PixelFormat::from_dt("r5g6b5"), None);
    }

    #[test]
    fn black_is_opaque_argb() {
        assert_eq!(PixelFormat::Argb8888.black().to_ne_bytes(), [0, 0, 0, 0xff]);
    }

    #[test]
    fn frame_validation_rejects_bad_geometry() {
        assert!(Frame::new(
            0,
            1,
            4,
            PixelFormat::Argb8888,
            FrameOrigin::Synthetic,
            String::new(),
            vec![]
        )
        .is_err());
        assert!(Frame::new(
            2,
            1,
            4,
            PixelFormat::Argb8888,
            FrameOrigin::Synthetic,
            String::new(),
            vec![0; 8]
        )
        .is_err());
        assert!(Frame::new(
            2,
            1,
            8,
            PixelFormat::Argb8888,
            FrameOrigin::Synthetic,
            String::new(),
            vec![0; 4]
        )
        .is_err());
    }

    #[test]
    fn fill_respects_destination_pitch_and_zeroes_padding() {
        let frame = sample_frame(16);
        let mut fb = Framebuffer::from_frame(&frame, 24).unwrap();
        for y in 0..2usize {
            for x in 0..3usize {
                assert_eq!(
                    fb.pixel(x as u32, y as u32),
                    frame.pixel(x as u32, y as u32)
                );
            }
            let row = &fb.as_bytes()[y * 24 + 12..y * 24 + 24];
            assert!(row.iter().all(|b| *b == 0), "padding must stay zeroed");
        }
        fb.set_pixel(1, 1, 0xff11_2233);
        assert_eq!(fb.pixel(1, 1), 0xff11_2233);
    }

    #[test]
    fn fill_accepts_page_rounded_sargo_mapping_and_preserves_tail() {
        let (width, height, stride) = (1080u32, 2220u32, 4320usize);
        let mut bytes = vec![0u8; stride * height as usize];
        for (i, px) in bytes.chunks_exact_mut(4).enumerate() {
            let v = 0xff00_0000u32 | (i as u32 & 0x00ff_ffff);
            px.copy_from_slice(&v.to_ne_bytes());
        }
        let frame = Frame::new(
            width,
            height,
            stride,
            PixelFormat::Argb8888,
            FrameOrigin::Synthetic,
            "sargo".to_string(),
            bytes,
        )
        .unwrap();
        let visible_len = stride * height as usize;
        assert_eq!(visible_len, 9_590_400);
        let mapped_len = (visible_len + 4095) & !4095;
        assert_eq!(mapped_len, 9_592_832);
        let sentinel = 0xa5u8;
        let mut dst = vec![sentinel; mapped_len];
        fill_pitched_from_frame(&mut dst, stride, &frame).unwrap();
        for y in [0usize, 1, height as usize / 2, height as usize - 1] {
            let row = y * stride;
            assert_eq!(
                &dst[row..row + width as usize * 4],
                &frame.bytes()[row..row + width as usize * 4]
            );
        }
        assert!(dst[visible_len..].iter().all(|b| *b == sentinel));
    }

    #[test]
    fn fill_rejects_short_padded_row_mapping_without_mutation() {
        let frame = sample_frame(16);
        let pitch = 24usize;
        let required = pitch * frame.height() as usize;
        assert!(required > frame.width() as usize * 4);
        let sentinel = 0x5au8;
        let mut dst = vec![sentinel; required - 1];
        let err = fill_pitched_from_frame(&mut dst, pitch, &frame).unwrap_err();
        assert!(err.contains("expected at least"), "unexpected error: {err}");
        assert!(dst.iter().all(|b| *b == sentinel));
    }

    #[test]
    fn ppm_parse_handles_comments_and_roundtrip() {
        let data = b"P6\n# a comment\n2 1\n255\n\x01\x02\x03\x04\x05\x06";
        let (w, h, rgb) = parse_ppm(data).unwrap();
        assert_eq!((w, h), (2, 1));
        assert_eq!(rgb, vec![1, 2, 3, 4, 5, 6]);

        let frame = Frame::new(
            2,
            1,
            8,
            PixelFormat::Argb8888,
            FrameOrigin::Synthetic,
            String::new(),
            vec![0x0a, 0x0b, 0x0c, 0xff, 0x1a, 0x1b, 0x1c, 0xff],
        )
        .unwrap();
        let encoded = encode_ppm(&frame);
        assert_eq!(
            &encoded[encoded.len() - 6..],
            &[0x0c, 0x0b, 0x0a, 0x1c, 0x1b, 0x1a]
        );
        let (w2, h2, rgb2) = parse_ppm(&encoded).unwrap();
        assert_eq!((w2, h2), (2, 1));
        assert_eq!(rgb2, vec![0x0c, 0x0b, 0x0a, 0x1c, 0x1b, 0x1a]);
    }

    #[test]
    fn ppm_rejects_malformed() {
        assert!(parse_ppm(b"P3\n2 1\n255\n").is_err());
        assert!(parse_ppm(b"P6\n2 1\n254\n").is_err());
        assert!(parse_ppm(b"P6\n2 1\n255\n\x00").is_err());
    }

    #[test]
    fn fixture_definition_is_not_devmem() {
        let dir = PathBuf::from("/tmp");
        let p = dir.join("premouth-nonexistent-fixture.ppm");
        assert!(load_ppm(&p).is_err());
    }
}
