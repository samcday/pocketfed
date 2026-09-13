use std::fs;
use std::path::Path;

#[derive(Debug, Default, Clone)]
pub struct RunStats {
    pub source: String,
    pub capture_bytes: u64,
    pub capture_ns: u64,
    pub frames_due: u64,
    pub frames_rendered: u64,
    pub ticks_skipped: u64,
    pub updates_submitted: u64,
    pub updates_failed: u64,
    pub rects_submitted: u64,
    pub pixels_erased: u64,
    pub damage_bytes_submitted: u64,
    pub update_time_ns_total: u64,
    pub update_time_ns_max: u64,
    pub cpu_start_ns: u64,
    pub cpu_end_ns: u64,
    pub anim_start_ns: u64,
    pub anim_end_ns: u64,
    pub black_flushed: bool,
    pub closefb_ok: bool,
    pub closefb_probe: String,
    pub guard_exit: String,
}

impl RunStats {
    pub fn wall_ns(&self) -> u64 {
        self.anim_end_ns.saturating_sub(self.anim_start_ns)
    }

    pub fn cpu_ns(&self) -> u64 {
        self.cpu_end_ns.saturating_sub(self.cpu_start_ns)
    }

    pub fn summary(&self) -> String {
        let mut out = String::new();
        push_stat(&mut out, "source", &self.source);
        push_stat(&mut out, "capture_bytes", self.capture_bytes);
        push_stat(&mut out, "capture_ns", self.capture_ns);
        push_stat(&mut out, "frames_due", self.frames_due);
        push_stat(&mut out, "frames_rendered", self.frames_rendered);
        push_stat(&mut out, "ticks_skipped", self.ticks_skipped);
        push_stat(&mut out, "updates_submitted", self.updates_submitted);
        push_stat(&mut out, "updates_failed", self.updates_failed);
        push_stat(&mut out, "rects_submitted", self.rects_submitted);
        push_stat(&mut out, "pixels_erased", self.pixels_erased);
        push_stat(
            &mut out,
            "damage_bytes_submitted",
            self.damage_bytes_submitted,
        );
        push_stat(&mut out, "update_time_ns_total", self.update_time_ns_total);
        push_stat(&mut out, "update_time_ns_max", self.update_time_ns_max);
        push_stat(&mut out, "anim_start_ns", self.anim_start_ns);
        push_stat(&mut out, "anim_end_ns", self.anim_end_ns);
        push_stat(&mut out, "wall_ns", self.wall_ns());
        push_stat(&mut out, "cpu_ns", self.cpu_ns());
        push_stat(&mut out, "black_flushed", u8::from(self.black_flushed));
        push_stat(&mut out, "closefb_ok", u8::from(self.closefb_ok));
        push_stat(&mut out, "closefb_probe", &self.closefb_probe);
        push_stat(&mut out, "guard_exit", &self.guard_exit);
        out
    }

    pub fn write_to(&self, path: &Path) -> Result<(), String> {
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                fs::create_dir_all(parent)
                    .map_err(|e| format!("create {}: {e}", parent.display()))?;
            }
        }
        fs::write(path, self.summary()).map_err(|e| format!("write {}: {e}", path.display()))
    }
}

fn push_stat(out: &mut String, key: &str, value: impl std::fmt::Display) {
    out.push_str(key);
    out.push('=');
    out.push_str(&value.to_string());
    out.push('\n');
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn summary_contains_measured_fields() {
        let mut s = RunStats::default();
        s.frames_rendered = 300;
        s.ticks_skipped = 2;
        s.black_flushed = true;
        s.guard_exit = "replacement".to_string();
        let text = s.summary();
        assert!(text.contains("frames_rendered=300\n"));
        assert!(text.contains("ticks_skipped=2\n"));
        assert!(text.contains("black_flushed=1\n"));
        assert!(text.contains("guard_exit=replacement\n"));
        assert!(text.contains("cpu_ns=0\n"));
    }
}
