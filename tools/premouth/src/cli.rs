use std::path::PathBuf;

use crate::handoff::DEFAULT_SOCKET;

#[derive(Debug, Clone, PartialEq)]
pub struct RunOptions {
    pub duration_s: f64,
    pub fps: u32,
    pub band_px: u32,
    pub socket: PathBuf,
    pub guard_timeout_s: u64,
    pub capture_out: Option<PathBuf>,
    pub fixture: Option<PathBuf>,
    pub stats: Option<PathBuf>,
    pub dt_base: Option<PathBuf>,
    pub verbose: bool,
}

impl RunOptions {
    pub fn defaults() -> Self {
        RunOptions {
            duration_s: 5.0,
            fps: 60,
            band_px: 32,
            socket: PathBuf::from(DEFAULT_SOCKET),
            guard_timeout_s: 20,
            capture_out: None,
            fixture: None,
            stats: None,
            dt_base: None,
            verbose: false,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct CaptureOptions {
    pub out: PathBuf,
    pub dt_base: Option<PathBuf>,
}

#[derive(Debug, Clone, PartialEq)]
pub struct PreviewOptions {
    pub fixture: PathBuf,
    pub out: Option<PathBuf>,
    pub duration_s: f64,
    pub fps: u32,
    pub band_px: u32,
}

#[derive(Debug, Clone, PartialEq)]
pub struct YieldOptions {
    pub socket: PathBuf,
    pub timeout_s: f64,
}

#[derive(Debug, Clone, PartialEq)]
pub enum Command {
    Run(RunOptions),
    Capture(CaptureOptions),
    Preview(PreviewOptions),
    Yield(YieldOptions),
    Help,
    Version,
}

pub fn usage() -> &'static str {
    "premouth - experimental Sargo ABL framebuffer capture and dissolve\n\
     \n\
     USAGE:\n\
       premouth run [OPTIONS]        capture ABL, reproduce it, dissolve to black, yield\n\
       premouth capture [OPTIONS]    capture-only probe; never opens DRM\n\
       premouth preview [OPTIONS]    offline fixture animation; never touches hardware\n\
       premouth --yield [OPTIONS]    ask a running daemon to yield the display\n\
     \n\
     RUN OPTIONS:\n\
       --duration SECS        dissolve duration, default 5.0\n\
       --fps N               target updates per second, default 60\n\
       --band-px N           spatial dissolve band width in rows, default 32\n\
       --socket PATH         handoff socket, default /run/premouth/handoff.sock\n\
       --guard-timeout SECS  passive framebuffer guard lifetime, default 20, 0 disables\n\
       --capture-out DIR     save raw capture, PPM and provenance before modeset\n\
       --fixture PPM         use an explicit fixture instead of live capture (test only)\n\
       --stats PATH          write measured counters\n\
       --dt-base PATH        override device tree base directory\n\
       -v, --verbose         more diagnostics on stderr\n\
     \n\
     CAPTURE OPTIONS:\n\
       --out DIR             probe output directory, default /run/premouth/capture\n\
       --dt-base PATH        override device tree base directory\n\
     \n\
     PREVIEW OPTIONS:\n\
       --fixture PPM         required input fixture\n\
       --out DIR             write preview-initial.ppm and preview-final.ppm\n\
       --duration SECS       default 5.0\n\
       --fps N               default 60\n\
       --band-px N           default 32\n\
     \n\
     YIELD OPTIONS:\n\
       --socket PATH         daemon socket, default /run/premouth/handoff.sock\n\
       --timeout SECS        bounded response wait, default 1.0\n"
}

pub fn parse(args: &[String]) -> Result<Command, String> {
    let args = Args::new(args);
    let first = args
        .peek()
        .ok_or_else(|| "missing subcommand; see premouth --help".to_string())?
        .to_string();
    match first.as_str() {
        "run" => parse_run(args),
        "capture" => parse_capture(args),
        "preview" => parse_preview(args),
        "--yield" | "yield" => parse_yield(args),
        "--help" | "-h" | "help" => Ok(Command::Help),
        "--version" | "-V" | "version" => Ok(Command::Version),
        other => Err(format!("unknown command {other:?}; see premouth --help")),
    }
}

struct Args {
    items: Vec<String>,
    pos: usize,
}

impl Args {
    fn new(items: &[String]) -> Self {
        Args {
            items: items.to_vec(),
            pos: 0,
        }
    }

    fn peek(&self) -> Option<&str> {
        self.items.get(self.pos).map(|s| s.as_str())
    }

    fn next(&mut self) -> Option<String> {
        let item = self.items.get(self.pos).cloned();
        if item.is_some() {
            self.pos += 1;
        }
        item
    }

    fn value(&mut self, inline: Option<String>, flag: &str) -> Result<String, String> {
        if let Some(value) = inline {
            return Ok(value);
        }
        self.next()
            .ok_or_else(|| format!("{flag} requires a value"))
    }
}

fn split_flag(arg: &str) -> (&str, Option<String>) {
    match arg.split_once('=') {
        Some((flag, value)) => (flag, Some(value.to_string())),
        None => (arg, None),
    }
}

fn parse_run(mut args: Args) -> Result<Command, String> {
    let _ = args.next();
    let mut o = RunOptions::defaults();
    while let Some(arg) = args.next() {
        let (flag, inline) = split_flag(&arg);
        match flag {
            "--duration" => o.duration_s = parse_f64(&args.value(inline, flag)?, flag, 0.1, 600.0)?,
            "--fps" => o.fps = parse_u32(&args.value(inline, flag)?, flag, 1, 240)?,
            "--band-px" => o.band_px = parse_u32(&args.value(inline, flag)?, flag, 0, 4096)?,
            "--socket" => o.socket = PathBuf::from(args.value(inline, flag)?),
            "--guard-timeout" => {
                o.guard_timeout_s = parse_u32(&args.value(inline, flag)?, flag, 0, 600)? as u64
            }
            "--capture-out" => o.capture_out = Some(PathBuf::from(args.value(inline, flag)?)),
            "--fixture" => o.fixture = Some(PathBuf::from(args.value(inline, flag)?)),
            "--stats" => o.stats = Some(PathBuf::from(args.value(inline, flag)?)),
            "--dt-base" => o.dt_base = Some(PathBuf::from(args.value(inline, flag)?)),
            "--verbose" | "-v" => o.verbose = true,
            "--help" | "-h" => return Ok(Command::Help),
            _ => return Err(format!("unknown run option {flag:?}")),
        }
    }
    Ok(Command::Run(o))
}

fn parse_capture(mut args: Args) -> Result<Command, String> {
    let _ = args.next();
    let mut o = CaptureOptions {
        out: PathBuf::from("/run/premouth/capture"),
        dt_base: None,
    };
    while let Some(arg) = args.next() {
        let (flag, inline) = split_flag(&arg);
        match flag {
            "--out" => o.out = PathBuf::from(args.value(inline, flag)?),
            "--dt-base" => o.dt_base = Some(PathBuf::from(args.value(inline, flag)?)),
            "--help" | "-h" => return Ok(Command::Help),
            _ => return Err(format!("unknown capture option {flag:?}")),
        }
    }
    Ok(Command::Capture(o))
}

fn parse_preview(mut args: Args) -> Result<Command, String> {
    let _ = args.next();
    let mut fixture = None;
    let mut out = None;
    let mut duration_s = 5.0f64;
    let mut fps = 60u32;
    let mut band_px = 32u32;
    while let Some(arg) = args.next() {
        let (flag, inline) = split_flag(&arg);
        match flag {
            "--fixture" => fixture = Some(PathBuf::from(args.value(inline, flag)?)),
            "--out" => out = Some(PathBuf::from(args.value(inline, flag)?)),
            "--duration" => duration_s = parse_f64(&args.value(inline, flag)?, flag, 0.1, 600.0)?,
            "--fps" => fps = parse_u32(&args.value(inline, flag)?, flag, 1, 240)?,
            "--band-px" => band_px = parse_u32(&args.value(inline, flag)?, flag, 0, 4096)?,
            "--help" | "-h" => return Ok(Command::Help),
            _ => return Err(format!("unknown preview option {flag:?}")),
        }
    }
    let fixture = fixture.ok_or_else(|| "preview requires --fixture PPM".to_string())?;
    Ok(Command::Preview(PreviewOptions {
        fixture,
        out,
        duration_s,
        fps,
        band_px,
    }))
}

fn parse_yield(mut args: Args) -> Result<Command, String> {
    let _ = args.next();
    let mut socket = PathBuf::from(DEFAULT_SOCKET);
    let mut timeout_s = 1.0f64;
    while let Some(arg) = args.next() {
        let (flag, inline) = split_flag(&arg);
        match flag {
            "--socket" => socket = PathBuf::from(args.value(inline, flag)?),
            "--timeout" => timeout_s = parse_f64(&args.value(inline, flag)?, flag, 0.05, 600.0)?,
            "--help" | "-h" => return Ok(Command::Help),
            _ => return Err(format!("unknown yield option {flag:?}")),
        }
    }
    Ok(Command::Yield(YieldOptions { socket, timeout_s }))
}

fn parse_u32(value: &str, flag: &str, min: u32, max: u32) -> Result<u32, String> {
    let parsed = value
        .parse::<u32>()
        .map_err(|_| format!("{flag}: invalid integer {value:?}"))?;
    if parsed < min || parsed > max {
        return Err(format!("{flag}: {parsed} outside [{min}, {max}]"));
    }
    Ok(parsed)
}

fn parse_f64(value: &str, flag: &str, min: f64, max: f64) -> Result<f64, String> {
    let parsed = value
        .parse::<f64>()
        .map_err(|_| format!("{flag}: invalid number {value:?}"))?;
    if parsed.is_nan() || parsed < min || parsed > max {
        return Err(format!("{flag}: {parsed} outside [{min}, {max}]"));
    }
    Ok(parsed)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(v: &[&str]) -> Vec<String> {
        v.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn run_defaults() {
        match parse(&args(&["run"])).unwrap() {
            Command::Run(o) => {
                assert_eq!(o.duration_s, 5.0);
                assert_eq!(o.fps, 60);
                assert_eq!(o.band_px, 32);
                assert_eq!(o.guard_timeout_s, 20);
                assert_eq!(o.socket, PathBuf::from(DEFAULT_SOCKET));
                assert!(o.fixture.is_none());
            }
            other => panic!("unexpected {other:?}"),
        }
    }

    #[test]
    fn run_accepts_inline_and_separate_values() {
        match parse(&args(&[
            "run",
            "--duration",
            "2.5",
            "--fps=30",
            "--fixture",
            "x.ppm",
        ]))
        .unwrap()
        {
            Command::Run(o) => {
                assert_eq!(o.duration_s, 2.5);
                assert_eq!(o.fps, 30);
                assert_eq!(o.fixture, Some(PathBuf::from("x.ppm")));
            }
            other => panic!("unexpected {other:?}"),
        }
    }

    #[test]
    fn rejects_bad_options() {
        assert!(parse(&args(&["run", "--duration", "abc"])).is_err());
        assert!(parse(&args(&["run", "--duration", "9999"])).is_err());
        assert!(parse(&args(&["run", "--bogus"])).is_err());
        assert!(parse(&args(&["preview"])).is_err());
        assert!(parse(&args(&[])).is_err());
    }

    #[test]
    fn parses_yield_forms() {
        match parse(&args(&["--yield"])).unwrap() {
            Command::Yield(o) => {
                assert_eq!(o.socket, PathBuf::from(DEFAULT_SOCKET));
                assert_eq!(o.timeout_s, 1.0);
            }
            other => panic!("unexpected {other:?}"),
        }
        match parse(&args(&["--yield", "--socket", "/tmp/s", "--timeout", "1"])).unwrap() {
            Command::Yield(o) => {
                assert_eq!(o.socket, PathBuf::from("/tmp/s"));
                assert_eq!(o.timeout_s, 1.0);
            }
            other => panic!("unexpected {other:?}"),
        }
    }
}
