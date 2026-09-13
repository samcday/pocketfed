use crate::image::PixelFormat;

pub const PROGRESS_ONE: u64 = 1 << 32;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Rect {
    pub x1: u16,
    pub y1: u16,
    pub x2: u16,
    pub y2: u16,
}

impl Rect {
    pub fn full_width_rows(y1: u32, y2: u32, width: u32) -> Self {
        Rect {
            x1: 0,
            y1: y1 as u16,
            x2: width as u16,
            y2: y2 as u16,
        }
    }

    pub fn area(&self) -> u64 {
        (self.x2.saturating_sub(self.x1)) as u64 * (self.y2.saturating_sub(self.y1)) as u64
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Run {
    y1: u32,
    y2: u32,
}

#[derive(Debug, Default, Clone)]
pub struct DamageAccumulator {
    runs: Vec<Run>,
}

impl DamageAccumulator {
    pub fn add_rows(&mut self, y1: u32, y2: u32) {
        if y1 >= y2 {
            return;
        }
        if let Some(last) = self.runs.last_mut() {
            if y1 <= last.y2 && y2 >= last.y1 {
                last.y1 = last.y1.min(y1);
                last.y2 = last.y2.max(y2);
                return;
            }
        }
        self.runs.push(Run { y1, y2 });
    }

    pub fn clear(&mut self) {
        self.runs.clear();
    }

    pub fn rects(&self, width: u32) -> Vec<Rect> {
        self.runs
            .iter()
            .map(|r| Rect::full_width_rows(r.y1, r.y2, width))
            .collect()
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct EraseStats {
    pub pixels_erased: u64,
}

pub struct Dissolve {
    width: u32,
    height: u32,
    band_fp: u64,
    row_min: Vec<u64>,
    row_max: Vec<u64>,
    floor_u: usize,
    black: u32,
    damage: DamageAccumulator,
}

impl Dissolve {
    pub fn new(width: u32, height: u32, band_px: u32, format: PixelFormat) -> Self {
        let band_fp = if height <= 1 {
            0
        } else {
            ((band_px.min(height) as u64) << 32) / height as u64
        }
        .min(PROGRESS_ONE);
        let mut row_min = Vec::with_capacity(height as usize);
        let mut row_max = Vec::with_capacity(height as usize);
        for u in 0..height {
            let base = base_fp(u as u64, height);
            let low = ((base as u128 * (PROGRESS_ONE - band_fp) as u128) >> 32) as u64;
            let high = (((base as u128 * (PROGRESS_ONE - band_fp) as u128)
                + ((PROGRESS_ONE - 1) as u128 * band_fp as u128))
                >> 32) as u64;
            row_min.push(low);
            row_max.push(high);
        }
        Dissolve {
            width,
            height,
            band_fp,
            row_min,
            row_max,
            floor_u: 0,
            black: format.black(),
            damage: DamageAccumulator::default(),
        }
    }

    pub fn row_bounds(&self, u: usize) -> (u64, u64) {
        (self.row_min[u], self.row_max[u])
    }

    pub fn threshold_of(&self, x: u32, y: u32) -> u64 {
        let u = (self.height - 1 - y) as u64;
        let base = base_fp(u, self.height);
        let jitter = pixel_jitter(x, y) as u64;
        let value = ((base as u128 * (PROGRESS_ONE - self.band_fp) as u128)
            + (jitter as u128 * self.band_fp as u128))
            >> 32;
        value as u64
    }

    pub fn pending_rects(&self) -> Vec<Rect> {
        self.damage.rects(self.width)
    }

    pub fn commit(&mut self, success: bool) {
        if success {
            self.damage.clear();
        }
    }

    pub fn erase_to(&mut self, buf: &mut [u8], pitch: usize, progress: u64) -> EraseStats {
        let progress = progress.min(PROGRESS_ONE);
        let mut stats = EraseStats::default();
        let end_u = self.row_min.partition_point(|&m| m <= progress);
        if end_u > self.floor_u {
            let mut run_open: Option<(u32, u32)> = None;
            for u in self.floor_u..end_u {
                let y = self.height - 1 - u as u32;
                let row_start = y as usize * pitch;
                let mut changed = false;
                for x in 0..self.width {
                    if self.threshold_of(x, y) <= progress {
                        let off = row_start + x as usize * 4;
                        let current = u32::from_ne_bytes(buf[off..off + 4].try_into().unwrap());
                        if current != self.black {
                            buf[off..off + 4].copy_from_slice(&self.black.to_ne_bytes());
                            changed = true;
                            stats.pixels_erased += 1;
                        }
                    }
                }
                if changed {
                    match run_open {
                        Some((start, end)) if end == y => run_open = Some((start, y + 1)),
                        Some(run) => {
                            self.damage.add_rows(run.0, run.1);
                            run_open = Some((y, y + 1));
                        }
                        None => run_open = Some((y, y + 1)),
                    }
                } else if let Some(run) = run_open.take() {
                    self.damage.add_rows(run.0, run.1);
                }
            }
            if let Some(run) = run_open.take() {
                self.damage.add_rows(run.0, run.1);
            }
        }
        let new_floor = self.row_max.partition_point(|&m| m < progress);
        if new_floor > self.floor_u {
            self.floor_u = new_floor;
        }
        stats
    }

    pub fn ensure_black(&mut self, buf: &mut [u8], pitch: usize) -> (EraseStats, bool) {
        let stats = self.erase_to(buf, pitch, PROGRESS_ONE);
        let mut all_black = true;
        'scan: for y in 0..self.height {
            let row_start = y as usize * pitch;
            for x in 0..self.width {
                let off = row_start + x as usize * 4;
                if u32::from_ne_bytes(buf[off..off + 4].try_into().unwrap()) != self.black {
                    all_black = false;
                    break 'scan;
                }
            }
        }
        (stats, all_black)
    }
}

fn base_fp(u: u64, height: u32) -> u64 {
    if height <= 1 {
        0
    } else {
        u * PROGRESS_ONE / (height as u64 - 1)
    }
}

fn pixel_jitter(x: u32, y: u32) -> u32 {
    let mut z = (x as u64) | ((y as u64) << 32);
    z = z.wrapping_add(0x9E37_79B9_7F4A_7C15);
    z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
    z ^= z >> 31;
    (z >> 32) as u32
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_buffer(width: u32, height: u32, pitch: usize) -> Vec<u8> {
        let mut buf = vec![0xABu8; pitch * height as usize];
        for y in 0..height {
            for x in 0..width {
                let off = y as usize * pitch + x as usize * 4;
                let v = 0xff22_3344u32 ^ (y << 8) ^ x;
                buf[off..off + 4].copy_from_slice(&v.to_ne_bytes());
            }
        }
        buf
    }

    fn is_black(buf: &[u8], pitch: usize, x: u32, y: u32) -> bool {
        let off = y as usize * pitch + x as usize * 4;
        u32::from_ne_bytes(buf[off..off + 4].try_into().unwrap()) == PixelFormat::OPAQUE_BLACK
    }

    #[test]
    fn row_bounds_are_monotonic_and_direction_is_bottom_up() {
        let d = Dissolve::new(64, 200, 16, PixelFormat::Argb8888);
        let mut prev = (0u64, 0u64);
        for u in 0..200 {
            let bounds = d.row_bounds(u);
            assert!(bounds.0 <= bounds.1);
            assert!(bounds.0 >= prev.0);
            assert!(bounds.1 >= prev.1);
            prev = bounds;
        }
        let (bottom_min, _) = d.row_bounds(0);
        let (top_min, _) = d.row_bounds(199);
        assert!(bottom_min < top_min);
    }

    #[test]
    fn erase_respects_thresholds_exactly_and_only_once() {
        let (w, h) = (32u32, 48u32);
        let pitch = w as usize * 4;
        let mut buf = test_buffer(w, h, pitch);
        let mut d = Dissolve::new(w, h, 8, PixelFormat::Argb8888);
        let progress = PROGRESS_ONE / 2;
        let stats = d.erase_to(&mut buf, pitch, progress);
        for y in 0..h {
            for x in 0..w {
                let t = d.threshold_of(x, y);
                if t <= progress {
                    assert!(
                        is_black(&buf, pitch, x, y),
                        "pixel ({x},{y}) t={t} should be black"
                    );
                } else {
                    assert!(
                        !is_black(&buf, pitch, x, y),
                        "pixel ({x},{y}) t={t} should remain"
                    );
                }
            }
        }
        assert!(stats.pixels_erased > 0);
        let second = d.erase_to(&mut buf, pitch, progress);
        assert_eq!(second.pixels_erased, 0, "erasing twice must be a no-op");
    }

    #[test]
    fn fully_dissolved_rows_are_a_bottom_prefix() {
        let (w, h) = (16u32, 64u32);
        let pitch = w as usize * 4;
        let mut buf = test_buffer(w, h, pitch);
        let mut d = Dissolve::new(w, h, 6, PixelFormat::Argb8888);
        let progress = PROGRESS_ONE * 3 / 5;
        d.erase_to(&mut buf, pitch, progress);
        for u in 0..h {
            let y = h - 1 - u;
            let full = (0..w).all(|x| is_black(&buf, pitch, x, y));
            let (rmin, rmax) = d.row_bounds(u as usize);
            if rmax <= progress {
                assert!(
                    full,
                    "row u={u} (y={y}) has rmax={rmax} <= p and must be fully black"
                );
            }
            if rmin > progress {
                for x in 0..w {
                    assert!(!is_black(&buf, pitch, x, y), "row u={u} not yet reached");
                }
            }
        }
        let mut prefix = 0usize;
        for u in 0..h as usize {
            let y = h - 1 - u as u32;
            if (0..w).all(|x| is_black(&buf, pitch, x, y)) {
                prefix = u + 1;
            } else {
                break;
            }
        }
        assert!(prefix > 0, "some bottom rows must be fully dissolved");
    }

    #[test]
    fn skipped_progress_jump_still_erases_every_eligible_pixel() {
        let (w, h) = (24u32, 40u32);
        let pitch = w as usize * 4;
        let mut buf = test_buffer(w, h, pitch);
        let mut d = Dissolve::new(w, h, 4, PixelFormat::Argb8888);
        d.erase_to(&mut buf, pitch, PROGRESS_ONE / 10);
        let progress = PROGRESS_ONE * 9 / 10;
        d.erase_to(&mut buf, pitch, progress);
        for y in 0..h {
            for x in 0..w {
                if d.threshold_of(x, y) <= progress {
                    assert!(is_black(&buf, pitch, x, y));
                }
            }
        }
    }

    #[test]
    fn exact_black_endpoint_touches_only_pixels_not_padding() {
        let (w, h) = (20u32, 30u32);
        let pitch = w as usize * 4 + 16;
        let mut buf = test_buffer(w, h, pitch);
        let mut d = Dissolve::new(w, h, 8, PixelFormat::Argb8888);
        let (_, all_black) = d.ensure_black(&mut buf, pitch);
        assert!(all_black);
        for y in 0..h {
            for x in 0..w {
                assert!(is_black(&buf, pitch, x, y));
            }
            let pad_start = y as usize * pitch + w as usize * 4;
            assert!(buf[pad_start..(y as usize + 1) * pitch]
                .iter()
                .all(|b| *b == 0xAB));
        }
    }

    #[test]
    fn damage_is_retained_until_a_successful_commit() {
        let (w, h) = (12u32, 32u32);
        let pitch = w as usize * 4;
        let mut buf = test_buffer(w, h, pitch);
        let mut d = Dissolve::new(w, h, 4, PixelFormat::Argb8888);
        d.erase_to(&mut buf, pitch, PROGRESS_ONE / 8);
        let first = d.pending_rects();
        assert!(!first.is_empty());
        d.commit(false);
        assert_eq!(d.pending_rects(), first, "failed update must retain damage");
        d.erase_to(&mut buf, pitch, PROGRESS_ONE / 2);
        let combined = d.pending_rects();
        let covered: u64 = combined.iter().map(|r| r.area()).sum();
        let first_area: u64 = first.iter().map(|r| r.area()).sum();
        assert!(covered >= first_area);
        d.commit(true);
        assert!(d.pending_rects().is_empty());
    }

    #[test]
    fn damage_covers_every_changed_pixel_between_updates() {
        let (w, h) = (21u32, 37u32);
        let pitch = w as usize * 4 + 8;
        let mut buf = test_buffer(w, h, pitch);
        let mut d = Dissolve::new(w, h, 5, PixelFormat::Argb8888);
        let mut steps = Vec::new();
        for i in 1..=10u32 {
            let progress = PROGRESS_ONE * i as u64 / 10;
            let before = buf.clone();
            d.erase_to(&mut buf, pitch, progress);
            let rects = d.pending_rects();
            for y in 0..h {
                for x in 0..w {
                    let off = y as usize * pitch + x as usize * 4;
                    if before[off..off + 4] != buf[off..off + 4] {
                        let inside = rects.iter().any(|r| {
                            x >= r.x1 as u32
                                && x < r.x2 as u32
                                && y >= r.y1 as u32
                                && y < r.y2 as u32
                        });
                        assert!(inside, "changed pixel ({x},{y}) not covered by damage");
                    }
                }
            }
            steps.push(rects);
            d.commit(true);
        }
        assert!(steps.iter().any(|r| !r.is_empty()));
    }

    #[test]
    fn one_by_one_and_zero_band_are_safe() {
        let mut buf = vec![0u8; 4];
        buf.copy_from_slice(&0xffaa_bbccu32.to_ne_bytes());
        let mut d = Dissolve::new(1, 1, 0, PixelFormat::Argb8888);
        let (_, all_black) = d.ensure_black(&mut buf, 4);
        assert!(all_black);
        assert_eq!(
            u32::from_ne_bytes(buf.try_into().unwrap()),
            PixelFormat::OPAQUE_BLACK
        );
    }

    #[test]
    fn accumulator_merges_adjacent_rows_and_keeps_gaps() {
        let mut acc = DamageAccumulator::default();
        acc.add_rows(10, 12);
        acc.add_rows(12, 14);
        acc.add_rows(20, 21);
        let rects = acc.rects(100);
        assert_eq!(rects.len(), 2);
        assert_eq!(rects[0], Rect::full_width_rows(10, 14, 100));
        assert_eq!(rects[1], Rect::full_width_rows(20, 21, 100));
        assert_eq!(rects[0].area() + rects[1].area(), 5 * 100);
    }

    #[test]
    fn pixel_jitter_is_stable_and_bounded() {
        let a = pixel_jitter(0, 0);
        let b = pixel_jitter(0, 0);
        assert_eq!(a, b);
        assert_ne!(pixel_jitter(0, 1), pixel_jitter(1, 0));
    }

    #[test]
    fn black_set_never_reverts_as_progress_advances() {
        let (w, h) = (17u32, 29u32);
        let pitch = w as usize * 4;
        let mut buf = test_buffer(w, h, pitch);
        let mut d = Dissolve::new(w, h, 4, PixelFormat::Argb8888);
        let mut black: Vec<Vec<bool>> = Vec::new();
        for step in 0..=20u64 {
            let progress = PROGRESS_ONE * step / 20;
            d.erase_to(&mut buf, pitch, progress);
            d.commit(true);
            let snapshot: Vec<bool> = (0..h)
                .flat_map(|y| (0..w).map(move |x| (x, y)))
                .map(|(x, y)| is_black(&buf, pitch, x, y))
                .collect();
            if let Some(previous) = black.last() {
                for (index, was_black) in previous.iter().enumerate() {
                    assert!(
                        !*was_black || snapshot[index],
                        "pixel {index} reverted to non-black at progress {progress}"
                    );
                }
            }
            black.push(snapshot);
        }
        assert!(black.last().unwrap().iter().all(|b| *b));
    }
}
