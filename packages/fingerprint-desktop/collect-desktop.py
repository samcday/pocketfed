#!/usr/bin/env python3
"""Read-only desktop inventory. Send over SSH stdin; save JSON locally.

No PAM transactions, fingerprint D-Bus methods, service activation, account
changes, biometric records or privileged homed user records. GetHomeByName
returns only basic account/home-state metadata.
"""
import datetime
import json
from pathlib import Path
import subprocess


def run(argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=20)
    return {"argv": argv, "returncode": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr}


out = {"captured_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
out["hostname"] = run(["hostname"])
out["kernel"] = run(["uname", "-r"])
out["packages"] = run(["rpm", "-q", "phosh", "phrog", "greetd",
                       "gnome-control-center", "fprintd", "fprintd-pam",
                       "libfprint", "pocketfed-fpc-auth", "phosh-fingerprint-auth",
                       "systemd", "pam", "authselect"])
out["authselect"] = run(["authselect", "current"])
schemas = run(["gsettings", "list-schemas"])
out["gdm_schema"] = {"returncode": schemas["returncode"],
                     "present": "org.gnome.login-screen" in schemas["stdout"].splitlines(),
                     "stderr": schemas["stderr"]}
out["service_state"] = run(["systemctl", "is-active", "phrog", "greetd",
                            "systemd-homed", "fprintd"])
out["fingerprint_units"] = run(["systemctl", "show", "fprintd.service",
    "pocketfed-fpc-auth.socket", "phosh-fingerprint-auth.socket",
    "pocketfed-keymaster-startup.service", "-p", "Id", "-p", "LoadState",
    "-p", "ActiveState", "-p", "UnitFileState", "-p", "MainPID"])
out["pam"] = {}
for name in ("phosh", "greetd", "phosh-fingerprint", "system-auth", "password-auth", "fingerprint-auth", "postlogin"):
    path = Path("/etc/pam.d", name)
    if not path.exists():
        path = Path("/usr/lib/pam.d", name)
    out["pam"][str(path)] = {"target": str(path.resolve()),
                            "text": path.read_text() if path.exists() else None}
out["greetd_config"] = {str(path): path.read_text()
                        for directory in ("/etc/greetd", "/etc/phrog")
                        for path in Path(directory).glob("*.toml")}
out["home_mount"] = run(["findmnt", "-rn", "-o", "SOURCE,TARGET,FSTYPE", "/home/sam"])
out["home_mapper"] = run(["cryptsetup", "status", "home-sam"])
if subprocess.run(["systemctl", "is-active", "--quiet", "systemd-homed"]).returncode == 0:
    out["home_metadata"] = run(["busctl", "call", "org.freedesktop.home1",
        "/org/freedesktop/home1", "org.freedesktop.home1.Manager", "GetHomeByName", "s", "sam"])
out["authselect_fingerprint_system_auth_preview"] = run([
    "authselect", "test", "local", "with-systemd-homed", "with-fingerprint", "--system-auth"])
out["authselect_fingerprint_auth_preview"] = run([
    "authselect", "test", "local", "with-systemd-homed", "with-fingerprint", "--fingerprint-auth"])
print(json.dumps(out, indent=2))
