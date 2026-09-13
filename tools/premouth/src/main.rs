mod capture;
mod cli;
mod devicetree;
mod display;
mod dissolve;
mod drm_uapi;
mod handoff;
mod image;
mod pacing;
mod signals;
mod stats;
mod systemd;

use std::path::PathBuf;
use std::process::ExitCode;
use std::time::Duration;

use cli::Command;
use handoff::YieldStatus;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match cli::parse(&args) {
        Ok(Command::Help) => {
            println!("{}", cli::usage());
            ExitCode::SUCCESS
        }
        Ok(Command::Version) => {
            println!("premouth {}", env!("CARGO_PKG_VERSION"));
            ExitCode::SUCCESS
        }
        Ok(command) => run(command),
        Err(e) => {
            eprintln!("premouth: {e}");
            eprintln!("{}", cli::usage());
            ExitCode::from(2)
        }
    }
}

fn run(command: Command) -> ExitCode {
    match command {
        Command::Yield(o) => {
            let status = handoff::client_yield(&o.socket, Duration::from_secs_f64(o.timeout_s));
            println!(
                "premouth: yield {}: {}",
                o.socket.display(),
                status.describe()
            );
            ExitCode::from(status.exit_code())
        }
        Command::Capture(o) => capture_only(o),
        Command::Preview(o) => preview(o),
        Command::Run(o) => {
            let code = run_session(o);
            systemd::ready("run session finished");
            code
        }
        Command::Help | Command::Version => ExitCode::SUCCESS,
    }
}

fn live_geometry(
    dt_base: Option<&std::path::Path>,
) -> Result<(devicetree::CaptureGeometry, String), String> {
    let base = devicetree::discover_base(dt_base).ok_or_else(|| {
        "no device tree sysfs base (expected /sys/firmware/devicetree/base)".to_string()
    })?;
    let framebuffer = devicetree::find_framebuffer(&base)?
        .ok_or_else(|| format!("no simple-framebuffer node under {}/chosen", base.display()))?;
    let region = devicetree::resolve_reserved_region(&base, framebuffer.region_phandle)?;
    let description = format!(
        "{} compatible={} memory-region={:#x} reserved-node={}",
        framebuffer.node_path.display(),
        framebuffer.compatible.join(","),
        framebuffer.region_phandle,
        region.node_path.display()
    );
    let geometry = devicetree::validate_geometry(&framebuffer, &region)?;
    Ok((geometry, description))
}

fn wait_for_simpledrm(
    timeout: Duration,
    handoff: &mut handoff::HandoffServer,
    signals: &mut signals::Signals,
) -> (Option<PathBuf>, bool) {
    let start = std::time::Instant::now();
    loop {
        if let Some(path) = display::find_simpledrm_card() {
            return (Some(path), false);
        }
        handoff.tick();
        if handoff.request_pending() {
            return (None, true);
        }
        if signals.pending() {
            return (None, true);
        }
        if start.elapsed() >= timeout {
            return (None, false);
        }
        std::thread::sleep(Duration::from_millis(50));
    }
}

fn capture_only(o: cli::CaptureOptions) -> ExitCode {
    let (geometry, description) = match live_geometry(o.dt_base.as_deref()) {
        Ok(value) => value,
        Err(e) => {
            eprintln!("premouth: capture probe failed: {e}");
            return ExitCode::from(1);
        }
    };
    match capture::capture_readonly(&geometry, &description, &mut || false) {
        Ok(report) => {
            if let Err(e) = capture::save_probe_dir(&o.out, &report.frame, &report.provenance) {
                eprintln!("premouth: probe save failed: {e}");
                return ExitCode::from(1);
            }
            println!(
                "premouth: captured {}x{} stride {} format {} ({} bytes) from {} into {}; inspect frame.raw/frame.ppm before trusting",
                report.frame.width(),
                report.frame.height(),
                report.frame.stride(),
                report.frame.format().name(),
                report.frame.bytes().len(),
                report.frame.detail(),
                o.out.display()
            );
            ExitCode::SUCCESS
        }
        Err(capture::CaptureFailure::Failed {
            message,
            provenance,
        }) => {
            let path = o.out.join("provenance.txt");
            let _ = capture::write_provenance(&path, &provenance);
            eprintln!(
                "premouth: capture probe failed: {message} (details in {})",
                path.display()
            );
            ExitCode::from(1)
        }
        Err(capture::CaptureFailure::YieldRequested { .. }) => {
            eprintln!("premouth: capture probe interrupted");
            ExitCode::from(1)
        }
    }
}

fn preview(o: cli::PreviewOptions) -> ExitCode {
    let frame = match image::load_ppm(&o.fixture) {
        Ok(frame) => frame,
        Err(e) => {
            eprintln!("premouth: preview fixture error: {e}");
            return ExitCode::from(1);
        }
    };
    if frame.origin() != image::FrameOrigin::Fixture {
        eprintln!("premouth: preview input is not marked as a fixture; refusing");
        return ExitCode::from(1);
    }
    let pitch = frame.stride();
    let mut fb = match image::Framebuffer::from_frame(&frame, pitch) {
        Ok(fb) => fb,
        Err(e) => {
            eprintln!("premouth: preview buffer error: {e}");
            return ExitCode::from(1);
        }
    };
    let mut dissolve =
        dissolve::Dissolve::new(frame.width(), frame.height(), o.band_px, frame.format());

    if let Some(out) = &o.out {
        if let Err(e) = write_preview_frame(out, "preview-initial.ppm", &fb) {
            eprintln!("premouth: {e}");
            return ExitCode::from(1);
        }
    }

    let duration_ns = (o.duration_s * 1_000_000_000.0) as u64;
    let total_frames = ((o.duration_s * o.fps as f64).round() as u64).max(1);
    let mut pixels_erased = 0u64;
    let mut damage_rects = 0u64;
    for index in 1..=total_frames {
        let elapsed = duration_ns.saturating_mul(index) / total_frames;
        let progress = pacing::progress_from_elapsed(elapsed, duration_ns);
        let stats = dissolve.erase_to(fb.as_mut_bytes(), pitch, progress);
        pixels_erased += stats.pixels_erased;
        damage_rects += dissolve.pending_rects().len() as u64;
        dissolve.commit(true);
    }
    let (_, all_black) = dissolve.ensure_black(fb.as_mut_bytes(), pitch);
    dissolve.commit(true);

    if let Some(out) = &o.out {
        if let Err(e) = write_preview_frame(out, "preview-final.ppm", &fb) {
            eprintln!("premouth: {e}");
            return ExitCode::from(1);
        }
    }

    println!(
        "premouth preview: fixture={} frames={} pixels_erased={} damage_rects={} all_black={}",
        o.fixture.display(),
        total_frames,
        pixels_erased,
        damage_rects,
        all_black
    );
    if all_black {
        ExitCode::SUCCESS
    } else {
        ExitCode::from(1)
    }
}

fn write_preview_frame(
    dir: &std::path::Path,
    name: &str,
    fb: &image::Framebuffer,
) -> Result<(), String> {
    std::fs::create_dir_all(dir).map_err(|e| format!("create {}: {e}", dir.display()))?;
    let frame = image::Frame::new(
        fb.width(),
        fb.height(),
        fb.pitch(),
        fb.format(),
        image::FrameOrigin::Synthetic,
        "preview".to_string(),
        fb.as_bytes().to_vec(),
    )?;
    image::write_ppm(&dir.join(name), &frame)
}

fn run_session(o: cli::RunOptions) -> ExitCode {
    let mut stats = stats::RunStats::default();
    stats.source = match &o.fixture {
        Some(path) => format!("fixture:{}", path.display()),
        None => "devmem-capture".to_string(),
    };
    let probe_dir = o
        .capture_out
        .clone()
        .unwrap_or_else(|| PathBuf::from("/run/premouth/capture"));

    let mut signals = match signals::Signals::install() {
        Ok(signals) => signals,
        Err(e) => {
            eprintln!("premouth: cannot install signal handlers: {e}");
            return ExitCode::from(1);
        }
    };

    let mut handoff = match handoff::HandoffServer::bind(&o.socket) {
        Ok(server) => server,
        Err(e) => {
            eprintln!(
                "premouth: handoff socket {} unavailable ({e}); leaving the display untouched",
                o.socket.display()
            );
            return ExitCode::from(1);
        }
    };

    let (frame, provenance) = match &o.fixture {
        Some(fixture) => {
            eprintln!(
                "premouth: FIXTURE MODE using {}; this is NOT an authentic ABL capture and cannot establish image survival",
                fixture.display()
            );
            match image::load_ppm(fixture) {
                Ok(frame) => (frame, format!("fixture={}\n", fixture.display())),
                Err(e) => {
                    eprintln!("premouth: fixture error: {e}");
                    handoff.set_final(YieldStatus::Error(e));
                    handoff.tick();
                    return ExitCode::from(1);
                }
            }
        }
        None => {
            let (geometry, description) = match live_geometry(o.dt_base.as_deref()) {
                Ok(value) => value,
                Err(e) => {
                    eprintln!("premouth: capture setup failed: {e}; no modeset performed");
                    handoff.set_final(YieldStatus::Error(e));
                    handoff.tick();
                    return ExitCode::from(1);
                }
            };
            let report = capture::capture_readonly(&geometry, &description, &mut || {
                handoff.tick();
                handoff.request_pending() || signals.pending()
            });
            match report {
                Ok(report) => {
                    stats.capture_bytes = report.frame.bytes().len() as u64;
                    stats.capture_ns = report.copy_end_ns.saturating_sub(report.copy_start_ns);
                    (report.frame, report.provenance)
                }
                Err(capture::CaptureFailure::YieldRequested { provenance }) => {
                    let path = probe_dir.join("provenance.txt");
                    let _ = capture::write_provenance(&path, &provenance);
                    eprintln!(
                        "premouth: yield arrived during capture; cancelling before modeset (partial capture details in {})",
                        path.display()
                    );
                    handoff.set_final(YieldStatus::Cancelled);
                    handoff.tick();
                    return ExitCode::SUCCESS;
                }
                Err(capture::CaptureFailure::Failed {
                    message,
                    provenance,
                }) => {
                    let path = probe_dir.join("provenance.txt");
                    let _ = capture::write_provenance(&path, &provenance);
                    eprintln!(
                        "premouth: authentic capture failed: {message}; no modeset performed (details in {})",
                        path.display()
                    );
                    handoff.set_final(YieldStatus::Error(message));
                    handoff.tick();
                    return ExitCode::from(1);
                }
            }
        }
    };

    if let Some(dir) = &o.capture_out {
        match capture::save_probe_dir(dir, &frame, &provenance) {
            Ok(()) => eprintln!("premouth: capture probe saved to {}", dir.display()),
            Err(e) => eprintln!("premouth: capture probe save failed: {e}"),
        }
    }

    let (card_path, cancelled) =
        wait_for_simpledrm(Duration::from_millis(1500), &mut handoff, &mut signals);
    if cancelled {
        eprintln!("premouth: yield or signal received while waiting for SimpleDRM");
        handoff.set_final(YieldStatus::Cancelled);
        handoff.tick();
        return ExitCode::SUCCESS;
    }
    let card_path = match card_path {
        Some(path) => path,
        None => {
            eprintln!("premouth: no SimpleDRM card found; leaving display untouched");
            systemd::ready("no simpledrm device");
            handoff.set_final(YieldStatus::Cancelled);
            handoff.tick();
            return ExitCode::SUCCESS;
        }
    };
    let card = match display::Card::open(&card_path) {
        Ok(card) => card,
        Err(e) => {
            eprintln!("premouth: open {} failed: {e}", card_path.display());
            systemd::ready("simpledrm open failed");
            handoff.set_final(YieldStatus::Error(e.to_string()));
            handoff.tick();
            return ExitCode::SUCCESS;
        }
    };
    match display::drm_driver_name(&card) {
        Ok(name) if name == "simpledrm" => {}
        Ok(name) => {
            eprintln!(
                "premouth: {} reports DRM driver {:?}, not simpledrm; refusing to touch it",
                card_path.display(),
                name
            );
            systemd::ready("unexpected DRM driver");
            handoff.set_final(YieldStatus::Error(format!("unexpected DRM driver {name}")));
            handoff.tick();
            return ExitCode::SUCCESS;
        }
        Err(e) => {
            eprintln!(
                "premouth: cannot query DRM driver on {}: {e}",
                card_path.display()
            );
            systemd::ready("drm driver query failed");
            handoff.set_final(YieldStatus::Error(e.to_string()));
            handoff.tick();
            return ExitCode::SUCCESS;
        }
    }

    let params = display::SessionParams {
        duration_ns: (o.duration_s * 1_000_000_000.0) as u64,
        fps: o.fps,
        band_px: o.band_px,
        guard_timeout_ns: o.guard_timeout_s.saturating_mul(1_000_000_000),
    };

    let outcome = display::run_display(
        &card,
        &frame,
        &params,
        &mut stats,
        &mut signals,
        &mut handoff,
    );
    // The passive guard, if used, has finished. Close before diagnostic I/O:
    // this also releases master immediately on every startup/error path.
    drop(card);

    if let Some(path) = &o.stats {
        if let Err(e) = stats.write_to(path) {
            eprintln!("premouth: stats write failed: {e}");
        }
    }
    eprintln!(
        "premouth: rendered={} due={} skipped={} updates={} failed={} pixels={} black={} closefb={} guard={} cpu_ms={}",
        stats.frames_rendered,
        stats.frames_due,
        stats.ticks_skipped,
        stats.updates_submitted,
        stats.updates_failed,
        stats.pixels_erased,
        u8::from(stats.black_flushed),
        u8::from(stats.closefb_ok),
        stats.guard_exit,
        stats.cpu_ns() / 1_000_000
    );
    if o.verbose {
        eprintln!("{}", stats.summary());
    }

    match outcome {
        Ok(display::DisplayOutcome::NoDevice) => {
            eprintln!("premouth: no connected SimpleDRM display; boot continues");
            systemd::ready("no connected simpledrm display");
            ExitCode::SUCCESS
        }
        Ok(display::DisplayOutcome::Cancelled) => {
            eprintln!("premouth: yield arrived before modeset; cancelled cleanly");
            ExitCode::SUCCESS
        }
        Ok(display::DisplayOutcome::Released {
            black_flushed,
            closefb_ok,
            ..
        }) => {
            if black_flushed && closefb_ok {
                ExitCode::SUCCESS
            } else {
                eprintln!("premouth: release completed with reported failures");
                ExitCode::from(3)
            }
        }
        Ok(display::DisplayOutcome::ReleaseFailed {
            black_flushed,
            closefb_ok,
            reason,
        }) => {
            eprintln!(
                "premouth: release failed: {reason} (black_flushed={}, closefb_ok={})",
                u8::from(black_flushed),
                u8::from(closefb_ok)
            );
            ExitCode::from(3)
        }
        Ok(display::DisplayOutcome::Aborted(reason)) => {
            eprintln!("premouth: display aborted before takeover: {reason}");
            systemd::ready("display aborted");
            ExitCode::from(1)
        }
        Err(e) => {
            eprintln!("premouth: display session error: {e}");
            ExitCode::from(1)
        }
    }
}
