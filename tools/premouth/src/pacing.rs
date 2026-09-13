pub trait Clock {
    fn now_ns(&self) -> u64;
}

pub struct MonotonicClock;

impl Clock for MonotonicClock {
    fn now_ns(&self) -> u64 {
        monotonic_ns()
    }
}

pub fn monotonic_ns() -> u64 {
    clock_ns(libc::CLOCK_MONOTONIC)
}

pub fn process_cpu_ns() -> u64 {
    clock_ns(libc::CLOCK_PROCESS_CPUTIME_ID)
}

fn clock_ns(clock: libc::clockid_t) -> u64 {
    let mut ts = libc::timespec {
        tv_sec: 0,
        tv_nsec: 0,
    };
    let rc = unsafe { libc::clock_gettime(clock, &mut ts) };
    if rc == 0 {
        (ts.tv_sec as u64)
            .saturating_mul(1_000_000_000)
            .saturating_add(ts.tv_nsec as u64)
    } else {
        0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Tick {
    pub index: u64,
    pub skipped: u64,
    pub deadline_ns: u64,
    pub lateness_ns: u64,
}

#[derive(Debug, Clone)]
pub struct Schedule {
    start_ns: u64,
    period_ns: u64,
    next_index: u64,
}

impl Schedule {
    pub fn new(start_ns: u64, fps: u32) -> Self {
        let fps = fps.max(1) as u64;
        Schedule {
            start_ns,
            period_ns: 1_000_000_000 / fps,
            next_index: 0,
        }
    }

    pub fn period_ns(&self) -> u64 {
        self.period_ns
    }

    pub fn next_index(&self) -> u64 {
        self.next_index
    }

    pub fn next_deadline_ns(&self) -> u64 {
        self.start_ns
            .saturating_add(self.next_index.saturating_mul(self.period_ns))
    }

    /// Tick 0 is due at `start_ns` itself; subsequent ticks are at absolute
    /// multiples of the period. Skipped ticks are counted, never replayed.
    pub fn due(&self, now_ns: u64) -> Option<Tick> {
        let elapsed = now_ns.saturating_sub(self.start_ns);
        let index = elapsed / self.period_ns;
        if index < self.next_index {
            return None;
        }
        Some(Tick {
            index,
            skipped: index - self.next_index,
            deadline_ns: self
                .start_ns
                .saturating_add(index.saturating_mul(self.period_ns)),
            lateness_ns: now_ns.saturating_sub(
                self.start_ns
                    .saturating_add(index.saturating_mul(self.period_ns)),
            ),
        })
    }

    pub fn advance(&mut self, now_ns: u64) -> Option<Tick> {
        let tick = self.due(now_ns)?;
        self.next_index = tick.index + 1;
        Some(tick)
    }

    pub fn timeout_ms(&self, now_ns: u64) -> i32 {
        if self.due(now_ns).is_some() {
            return 0;
        }
        let remaining = self.next_deadline_ns().saturating_sub(now_ns);
        let ms = remaining / 1_000_000;
        ms.clamp(1, 1000) as i32
    }
}

pub fn progress_from_elapsed(elapsed_ns: u64, duration_ns: u64) -> u64 {
    const ONE: u64 = 1 << 32;
    if duration_ns == 0 {
        return ONE;
    }
    let clamped = elapsed_ns.min(duration_ns);
    ((clamped as u128 * ONE as u128) / duration_ns as u128).min(ONE as u128) as u64
}

pub fn sleep_ms(ms: u64) {
    std::thread::sleep(std::time::Duration::from_millis(ms));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn schedule_delivers_tick_zero_then_absolute_ticks() {
        let mut s = Schedule::new(1_000, 60);
        let t0 = s.advance(1_000).unwrap();
        assert_eq!((t0.index, t0.skipped, t0.deadline_ns), (0, 0, 1_000));
        assert_eq!(s.next_index(), 1);
        assert!(s.due(1_000).is_none());
        let t1 = s.advance(1_000 + 16_666_666).unwrap();
        assert_eq!(
            (t1.index, t1.skipped, t1.deadline_ns),
            (1, 0, 1_000 + 16_666_666)
        );
        let t6 = s.advance(1_000 + 100_000_000).unwrap();
        assert_eq!(t6.index, 6);
        assert_eq!(t6.skipped, 4);
        assert_eq!(t6.deadline_ns, 1_000 + 6 * 16_666_666);
        assert!(s.due(1_000 + 100_000_000).is_none());
    }

    #[test]
    fn schedule_tolerates_jitter_and_never_rewinds() {
        let mut s = Schedule::new(0, 60);
        let period = s.period_ns();
        let mut now = 0u64;
        let mut last_index = None;
        for i in 0..120 {
            now += period + (i % 7);
            if let Some(t) = s.advance(now) {
                if let Some(prev) = last_index {
                    assert!(t.index > prev);
                }
                last_index = Some(t.index);
            }
        }
        assert!(last_index.is_some());
    }

    #[test]
    fn timeout_is_bounded_and_nonzero_before_deadline() {
        let mut s = Schedule::new(0, 60);
        assert_eq!(s.timeout_ms(0), 0);
        let _ = s.advance(0);
        assert_eq!(s.timeout_ms(0), 16);
        assert!(s.timeout_ms(15_000_000) <= 2);
        assert!(s.timeout_ms(0) <= 1000);
    }

    #[test]
    fn progress_is_clamped_and_exact_at_end() {
        assert_eq!(progress_from_elapsed(0, 1_000_000), 0);
        assert_eq!(progress_from_elapsed(500_000, 1_000_000), 1 << 31);
        assert_eq!(progress_from_elapsed(1_000_000, 1_000_000), 1 << 32);
        assert_eq!(progress_from_elapsed(1_500_000, 1_000_000), 1 << 32);
        assert_eq!(progress_from_elapsed(u64::MAX, 1_000_000), 1 << 32);
        assert_eq!(progress_from_elapsed(10, 0), 1 << 32);
    }
}
