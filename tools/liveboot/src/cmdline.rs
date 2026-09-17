//! Kernel command line editing for a liveboot image.
//!
//! The device image's own `aboot.img` already carries a working command line:
//! `<S> root=LABEL=pfroot rw rootwait rootfstype=ext4 ostree=true quiet rhgb ... <E>`.
//! Liveboot reuses that image byte for byte and only rewrites the command line,
//! so the edits here are the whole difference between an installed boot and a
//! USB-served one.

use std::fmt;

/// One command line token: either a bare flag or a `key=value` pair.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Arg {
    pub key: String,
    pub value: Option<String>,
}

impl Arg {
    fn parse(token: &str) -> Self {
        match token.split_once('=') {
            Some((key, value)) => Self {
                key: key.to_string(),
                value: Some(value.to_string()),
            },
            None => Self {
                key: token.to_string(),
                value: None,
            },
        }
    }
}

impl fmt::Display for Arg {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match &self.value {
            Some(value) => write!(f, "{}={}", self.key, value),
            None => f.write_str(&self.key),
        }
    }
}

/// Command line arguments that only make sense for an installed boot.
///
/// `root=`/`rootfstype=` are replaced because the served device is not the eMMC
/// one, and crucially the internal eMMC root carries the same `pfroot` label, so
/// leaving `root=LABEL=pfroot` in place can silently boot the installed system
/// instead of the one under test. The splash arguments go because a liveboot run
/// is diagnosed over the UART, and a splash hides the console.
const DROPPED: &[&str] = &[
    "root",
    "rootfstype",
    "rootflags",
    "quiet",
    "rhgb",
    "splash",
    "plymouth.ignore-serial-consoles",
];

/// How to rewrite an installed image's command line for one liveboot run.
#[derive(Clone, Debug)]
pub struct LivebootCmdline {
    /// smoo export id holding the root filesystem image.
    pub export_id: u32,
    /// Unique per-run token. The guest reporter echoes it and the UART harness
    /// gates its SysRq reboot on it, so a stale console capture can never be
    /// mistaken for this run.
    pub run_token: String,
    /// Serial console, e.g. `ttyMSM0,115200n8`.
    pub console: String,
    /// Copy-on-write size handed to the smoo dracut module.
    pub cow_size: Option<String>,
    /// Extra arguments appended verbatim, last, so they win.
    pub extra: Vec<String>,
}

impl LivebootCmdline {
    pub fn new(export_id: u32, run_token: impl Into<String>) -> Self {
        Self {
            export_id,
            run_token: run_token.into(),
            console: "ttyMSM0,115200n8".to_string(),
            cow_size: None,
            extra: Vec::new(),
        }
    }
}

/// Split a command line, dropping the `<S>`/`<E>` abl-exorcist markers if present.
///
/// The markers are re-applied when the image is repacked, so they must not be
/// carried through as ordinary arguments.
pub fn parse(cmdline: &str) -> Vec<Arg> {
    cmdline
        .split_ascii_whitespace()
        .filter(|token| *token != "<S>" && *token != "<E>")
        .map(Arg::parse)
        .collect()
}

/// Rewrite `base` for a liveboot run.
///
/// Arguments are kept in their original order; liveboot's own arguments are
/// appended. An argument already present in `base` that liveboot also sets is
/// dropped from its original position, so the liveboot value is unambiguous
/// rather than relying on last-wins parsing.
pub fn apply(base: &str, opts: &LivebootCmdline) -> String {
    fn set(key: &str, value: &str) -> Arg {
        Arg {
            key: key.into(),
            value: Some(value.into()),
        }
    }
    fn flag(key: &str) -> Arg {
        Arg {
            key: key.into(),
            value: None,
        }
    }

    let mut added: Vec<Arg> = vec![
        set("root", "/dev/smoo-root"),
        set("rootfstype", "ext4"),
        set("rd.smoo", "1"),
        set("rd.smoo.root", &opts.export_id.to_string()),
    ];
    if let Some(cow_size) = &opts.cow_size {
        added.push(set("rd.smoo.cow.size", cow_size));
    }
    added.extend([
        set("pocketfed.liveboot", &opts.run_token),
        set("console", &opts.console),
        flag("earlycon"),
        set("sysrq_always_enabled", "1"),
    ]);
    added.extend(opts.extra.iter().map(|extra| Arg::parse(extra)));

    let mut out: Vec<Arg> = parse(base)
        .into_iter()
        .filter(|arg| {
            !DROPPED.contains(&arg.key.as_str()) && !added.iter().any(|new| new.key == arg.key)
        })
        .collect();
    out.extend(added);

    out.iter().map(Arg::to_string).collect::<Vec<_>>().join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;

    const INSTALLED: &str = "<S> root=LABEL=pfroot rw rootwait rootfstype=ext4 ostree=true quiet \
                             rhgb plymouth.ignore-serial-consoles init_on_alloc=0 \
                             sysrq_always_enabled=1 module_blacklist=rpmsg_wwan_ctrl <E>";

    fn applied() -> String {
        apply(INSTALLED, &LivebootCmdline::new(2863311530, "run-abc123"))
    }

    #[test]
    fn markers_are_not_carried_through_as_arguments() {
        let parsed = parse(INSTALLED);
        assert!(parsed
            .iter()
            .all(|arg| arg.key != "<S>" && arg.key != "<E>"));
    }

    #[test]
    fn root_is_forced_to_the_served_device() {
        let out = applied();
        assert!(out.contains("root=/dev/smoo-root"));
        assert!(
            !out.contains("LABEL=pfroot"),
            "the internal eMMC carries the same label and must not stay reachable: {out}"
        );
        // Count whole tokens: "rd.smoo.root=" contains "root=" as a substring.
        assert_eq!(
            out.split(' ')
                .filter(|arg| arg.starts_with("root="))
                .count(),
            1
        );
    }

    #[test]
    fn smoo_export_is_named_in_decimal() {
        assert!(applied().contains("rd.smoo.root=2863311530"));
        assert!(applied().contains("rd.smoo=1"));
    }

    #[test]
    fn run_token_and_console_are_present() {
        let out = applied();
        assert!(out.contains("pocketfed.liveboot=run-abc123"));
        assert!(out.contains("console=ttyMSM0,115200n8"));
        assert!(out.contains("earlycon"));
    }

    #[test]
    fn splash_arguments_are_dropped_so_the_console_is_visible() {
        let out = applied();
        for dropped in ["quiet", "rhgb", "plymouth.ignore-serial-consoles"] {
            assert!(
                !out.split(' ').any(|arg| arg == dropped),
                "{dropped} in {out}"
            );
        }
    }

    #[test]
    fn unrelated_installed_arguments_survive_in_order() {
        let out = applied();
        let kept: Vec<&str> = out
            .split(' ')
            .filter(|arg| ["rw", "rootwait", "ostree=true", "init_on_alloc=0"].contains(arg))
            .collect();
        assert_eq!(
            kept,
            vec!["rw", "rootwait", "ostree=true", "init_on_alloc=0"]
        );
        assert!(out.contains("module_blacklist=rpmsg_wwan_ctrl"));
    }

    #[test]
    fn an_argument_liveboot_sets_is_not_duplicated_from_the_base() {
        // The installed command line already carries sysrq_always_enabled=1.
        assert_eq!(applied().matches("sysrq_always_enabled=").count(), 1);
    }

    #[test]
    fn cow_size_is_optional() {
        let mut opts = LivebootCmdline::new(1, "t");
        assert!(!apply(INSTALLED, &opts).contains("rd.smoo.cow.size"));
        opts.cow_size = Some("2G".into());
        assert!(apply(INSTALLED, &opts).contains("rd.smoo.cow.size=2G"));
    }

    #[test]
    fn extra_arguments_are_appended_last() {
        let mut opts = LivebootCmdline::new(1, "t");
        opts.extra = vec!["rd.smoo.log=debug".into(), "rd.break".into()];
        let out = apply(INSTALLED, &opts);
        assert!(out.ends_with("rd.smoo.log=debug rd.break"), "{out}");
    }
}
