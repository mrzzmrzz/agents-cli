import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest


AGENTS = Path(__file__).resolve().parents[1] / "agents"
ZSH = shutil.which("zsh")
MOCK = r'''
import json, os, pathlib, socket, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
p = pathlib.Path(os.environ["TEST_STATE"])
s = json.loads(p.read_text())
s["calls"].append([name, *args])
def save(): p.write_text(json.dumps(s))
def finish(code=0, text=""):
    save()
    if text: print(text)
    sys.exit(code)
def restart():
    if s.get("restart_fail"): finish(1, "restart refused")
    if not s.get("stale_after_restart"):
        s["server"] = s["standalone"] if name == "codex" else s["codex"]
    finish()
if name == "sleep": finish()
if name == "curl":
    if s.get("download_fail"): finish(22, "download failed")
    if "https://chatgpt.com/codex/install.sh" in args:
        finish(text="exec " + sys.executable + " " + str(pathlib.Path(sys.argv[0]).with_name("install-standalone")))
    if "install_claude" in s:
        binary = pathlib.Path(os.environ["HOME"]) / ".local/bin/claude"
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text("#!/bin/sh\necho '" + s["install_claude"] + "'\n")
        binary.chmod(0o755)
    finish()
if name == "install-standalone":
    assert os.environ["CODEX_NON_INTERACTIVE"] == "1"
    if s.get("standalone_fail") or s.get("update_fail") == "codex": finish(1, "standalone install failed")
    s["codex"] = s["standalone"] = s.get("new_codex", "1.1.0")
    home = pathlib.Path(os.environ.get("CODEX_HOME", os.environ["HOME"] + "/.codex"))
    binary = home / "packages/standalone/current/bin/codex"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(pathlib.Path(sys.argv[0]).read_text())
    binary.chmod(0o755)
    launcher = pathlib.Path(os.environ.get("CODEX_INSTALL_DIR", os.environ["HOME"] + "/.local/bin")) / "codex"
    launcher.parent.mkdir(parents=True, exist_ok=True)
    if launcher.is_symlink(): launcher.unlink()
    launcher.symlink_to(binary)
    finish()
if name == "restart-codex": restart()
if name == "systemctl":
    if "is-active" in args:
        manager = "user" if "--user" in args else "system"
        finish(0 if s.get("manager") == manager else 3)
    if "restart" in args: restart()
    finish(1)
if name == "npm":
    if args == ["root", "-g"]:
        finish(text=s.get("npm_root", str(pathlib.Path(sys.argv[0]).parent.parent / "node_modules")))
    agent = "codex" if "@openai/codex@latest" in args else "pi"
    if s.get("update_fail") == agent: finish(1, "install failed")
    s[agent] = s.get("new_" + agent, s.get(agent, "1.0.0"))
    finish()
if args == ["--version"]:
    finish(text=name + " " + s[name])
if name == "codex":
    if args == ["features", "list"]:
        finish(1 if s.get("config_fail") else 0, "config check")
    if args == ["app-server", "daemon", "restart"]: restart()
    if args == ["app-server", "daemon", "version"]:
        if s.get("socket_probe"):
            home = os.environ.get("CODEX_HOME", os.environ["HOME"] + "/.codex")
            socket_path = home + "/app-server-control/app-server-control.sock"
            with socket.socket(socket.AF_UNIX) as client:
                try:
                    client.connect(socket_path)
                except OSError as error:
                    print(f"Error: failed to connect to {socket_path}\n\nCaused by:\n"
                          f"    {error.strerror} (os error {error.errno})", file=sys.stderr)
                    finish(1)
        if s.get("status_error"):
            print(s["status_error"], file=sys.stderr)
            finish(1)
        if s.get("status_fail"): finish(1, "status unavailable")
        finish(text=json.dumps({"status": s.get("status", "running"),
                               "cliVersion": s["codex"],
                               "appServerVersion": s["server"]}, indent=2))
finish(1, "unexpected command")
'''


@unittest.skipUnless(ZSH, "zsh is required")
class UpdateTests(unittest.TestCase):
    def setUp(self):
        # macOS's default TMPDIR is too long for a Unix socket pathname.
        self.temp = tempfile.TemporaryDirectory(prefix="agents-test-", dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.state_path = self.root / "state.json"
        self.state = {"codex": "1.0.0", "new_codex": "1.1.0",
                      "server": "1.0.0", "standalone": "1.0.0", "calls": []}
        for name in ("codex", "npm", "systemctl", "sleep", "restart-codex", "curl", "install-standalone"):
            self.install_mock(name)
        self.env = {"PATH": str(self.bin) + ":/usr/bin:/bin",
                    "HOME": str(self.home), "NO_COLOR": "1",
                    "TEST_STATE": str(self.state_path)}
        self.socket = socket.socket(socket.AF_UNIX)
        self.addCleanup(self.socket.close)
        self.socket_path = self.home / ".codex/app-server-control/app-server-control.sock"
        self.socket_path.parent.mkdir(parents=True)
        self.socket.bind(str(self.socket_path))
        self.daemon_pid_path = self.home / ".codex/app-server-daemon/app-server.pid"
        self.daemon_pid_path.parent.mkdir(parents=True)
        self.daemon_record = {
            "pid": os.getpid(),
            "processStartTime": subprocess.check_output(
                ["ps", "-p", str(os.getpid()), "-o", "lstart="],
                env={**self.env, "LC_ALL": "C"}, text=True).strip(),
        }
        self.daemon_pid_path.write_text(json.dumps(self.daemon_record))

    def install_mock(self, name):
        p = self.bin / name
        if name in ("codex", "pi"):
            if name == "codex":
                target = self.home / ".codex/packages/standalone/current/bin/codex"
            else:
                target = self.root / "node_modules/@earendil-works/pi-coding-agent/bin/pi"
            target.parent.mkdir(parents=True, exist_ok=True)
            p.symlink_to(target)
            p = target
        p.write_text("#!" + sys.executable + "\n" + MOCK)
        p.chmod(0o755)

    def run_agents(self, *args, input=None):
        self.state_path.write_text(json.dumps(self.state))
        result = subprocess.run([ZSH, str(AGENTS), *args], input=input,
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.state = json.loads(self.state_path.read_text())
        return result

    def run_update(self, *args):
        return self.run_agents("update", *args)

    def restarts(self):
        return [c for c in self.state["calls"]
                if "restart" in c or c[0] == "restart-codex"]

    def test_update_restarts_and_verifies_native_daemon(self):
        r = self.run_update("codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.state["standalone"], "1.1.0")
        self.assertEqual(self.restarts(), [["codex", "app-server", "daemon", "restart"]])
        self.assertIn("1.1.0 verified", r.stdout)

    def test_up_to_date_cli_repairs_stale_server(self):
        self.state["codex"] = "1.1.0"
        r = self.run_update("codex")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.restarts()), 1)

    def test_unmanaged_server_is_left_running_with_restart_guidance(self):
        self.daemon_pid_path.unlink()
        self.state["codex"] = "1.1.0"
        r = self.run_update("codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(self.restarts())
        self.assertEqual(self.state["server"], "1.0.0")
        self.assertIn("app-server remains at 1.0.0", r.stdout)
        self.assertIn("AGENTS_CODEX_RESTART_CMD", r.stdout)
        self.assertNotIn("restarting codex app-server", r.stdout)
        self.assertNotIn("verified", r.stdout)

    def test_invalid_daemon_records_do_not_authorize_restart(self):
        records = [
            "not JSON",
            json.dumps({**self.daemon_record, "pid": 999999999}),
            json.dumps({**self.daemon_record, "pid": 0}),
            json.dumps({**self.daemon_record, "pid": -1}),
            json.dumps({**self.daemon_record, "processStartTime": "old process"}),
            json.dumps({"pid": os.getpid()}),
        ]
        for record in records:
            with self.subTest(record=record):
                self.daemon_pid_path.write_text(record)
                r = self.run_update("codex")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertFalse(self.restarts())
                self.assertEqual(self.state["server"], "1.0.0")
                self.assertIn("app-server remains at 1.0.0", r.stdout)

    def test_inactive_systemd_does_not_imply_native_daemon_ownership(self):
        self.daemon_pid_path.unlink()
        self.state["manager"] = "auto-restart"
        r = self.run_update("codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(self.restarts())
        self.assertEqual(self.state["server"], "1.0.0")

    def test_batch_continues_with_unmanaged_server(self):
        self.daemon_pid_path.unlink()
        self.install_mock("pi")
        self.state.update(pi="2.0.0", new_pi="2.1.0")
        r = self.run_update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(self.restarts())
        self.assertEqual(self.state["pi"], "2.1.0")
        self.assertEqual(self.state["server"], "1.0.0")

    def test_matching_versions_do_not_restart(self):
        self.state["codex"] = self.state["server"] = "1.1.0"
        r = self.run_update("codex")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.restarts())

    def test_stopped_server_is_not_started(self):
        self.socket.close()
        self.socket_path.unlink()
        r = self.run_update("codex")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.restarts())
        self.assertFalse(any("app-server" in c for c in self.state["calls"]))
        self.assertEqual(self.state["standalone"], "1.1.0")

    def test_update_failure_never_touches_server(self):
        self.state["update_fail"] = "codex"
        r = self.run_update("codex")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(any("app-server" in c for c in self.state["calls"]))

    def test_stale_socket_is_left_stopped(self):
        self.socket.close()
        self.state["socket_probe"] = True
        r = self.run_update("codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("stale socket", r.stdout)
        self.assertEqual(r.stderr, "")
        self.assertEqual(self.state["standalone"], "1.1.0")
        self.assertFalse(self.restarts())
        self.assertTrue(self.socket_path.exists())

    def test_connection_refused_on_macos_and_linux(self):
        self.state["codex"] = "1.1.0"
        for errno in (61, 111):
            with self.subTest(errno=errno):
                self.state["status_error"] = (
                    f"Error: failed to connect to {self.socket_path}\n\n"
                    f"Caused by:\n    Connection refused (os error {errno})")
                r = self.run_update("codex")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("stale socket", r.stdout)
                self.assertEqual(r.stderr, "")
                self.assertFalse(self.restarts())

    def test_other_connection_errors_are_reported(self):
        for error in ("Permission denied (os error 13)", "Connection reset by peer (os error 54)"):
            with self.subTest(error=error):
                self.state["status_error"] = f"Error: failed to connect to {self.socket_path}\n{error}"
                r = self.run_update("codex")
                self.assertNotEqual(r.returncode, 0)
                self.assertIn(error, r.stderr)
                self.assertFalse(self.restarts())

    def test_config_failure_preserves_running_server(self):
        self.state["config_fail"] = True
        r = self.run_update("codex")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.restarts())

    def test_restart_failure_is_reported(self):
        self.state["restart_fail"] = True
        r = self.run_update("codex")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("restart failed", r.stderr)

    def test_restart_success_with_wrong_version_is_failure(self):
        self.state["stale_after_restart"] = True
        r = self.run_update("codex")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("did not report version 1.1.0", r.stderr)
        self.assertEqual(len(self.restarts()), 1)

    def test_status_failure_does_not_blindly_restart(self):
        self.state["status_fail"] = True
        r = self.run_update("codex")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.restarts())

    def test_unknown_status_is_failure(self):
        self.state["status"] = "unknown"
        r = self.run_update("codex")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.restarts())

    def test_user_systemd_service(self):
        self.daemon_pid_path.unlink()
        self.state["manager"] = "user"
        r = self.run_update("codex")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.restarts(), [["systemctl", "--user", "restart", "codex-app-server.service"]])

    @unittest.skipUnless(os.geteuid() == 0, "system service only used as root")
    def test_root_systemd_service(self):
        self.daemon_pid_path.unlink()
        self.state["manager"] = "system"
        r = self.run_update("codex")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.restarts(), [["systemctl", "restart", "codex-app-server.service"]])

    def test_explicit_restart_command(self):
        self.daemon_pid_path.unlink()
        self.env["AGENTS_CODEX_RESTART_CMD"] = "restart-codex"
        r = self.run_update("codex")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.restarts(), [["restart-codex"]])

    def test_custom_codex_home_avoids_default_systemd_service(self):
        self.env["CODEX_HOME"] = str(self.home / ".codex-custom")
        old_home = self.home / ".codex"
        old_home.rename(self.env["CODEX_HOME"])
        (self.bin / "codex").unlink()
        (self.bin / "codex").symlink_to(Path(self.env["CODEX_HOME"]) / "packages/standalone/current/bin/codex")
        self.socket.close()
        self.socket = socket.socket(socket.AF_UNIX)
        self.addCleanup(self.socket.close)
        p = Path(self.env["CODEX_HOME"]) / "app-server-control/app-server-control.sock"
        p.unlink()
        self.socket.bind(str(p))
        self.state["manager"] = "user"
        r = self.run_update("codex")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.restarts(), [["codex", "app-server", "daemon", "restart"]])

    def test_batch_continues_after_codex_restart_failure(self):
        self.install_mock("pi")
        self.state.update(pi="2.0.0", new_pi="2.1.0", restart_fail=True)
        r = self.run_update()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.state["pi"], "2.1.0")
        self.assertIn("pi: restart existing sessions", r.stdout)

    def test_other_agents_do_not_restart_codex(self):
        self.install_mock("pi")
        self.state.update(pi="2.0.0", new_pi="2.1.0")
        r = self.run_update("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.restarts())
        self.assertFalse(any(c[0] == "codex" for c in self.state["calls"]))

    def test_standalone_failures_preserve_server(self):
        for failure in ("download_fail", "standalone_fail", "config_fail"):
            with self.subTest(failure=failure):
                self.state[failure] = True
                r = self.run_update("codex")
                self.assertNotEqual(r.returncode, 0)
                self.assertFalse(self.restarts())
                self.assertEqual(self.state["server"], "1.0.0")
                del self.state[failure]

    def test_wrong_npm_prefix_blocks_update_and_uninstall(self):
        self.install_mock("pi")
        self.state["pi"] = "2.0.0"
        self.state["npm_root"] = str(self.root / "other-prefix/node_modules")
        for command in ("update", "uninstall"):
            with self.subTest(command=command):
                r = self.run_agents(command, "pi", input="y\n")
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("unsupported installation", r.stderr)
                self.assertTrue(all(c == ["npm", "root", "-g"] for c in self.state["calls"]))

    def test_unsupported_native_install_is_not_modified(self):
        self.install_mock("amp")
        for command in ("update", "uninstall"):
            r = self.run_agents(command, "amp", input="y\n")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("unsupported installation", r.stderr)
            self.assertFalse(self.state["calls"])

    def test_install_without_visible_command_fails(self):
        r = self.run_agents("install", "claude")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not on PATH", r.stderr)

    def test_install_verifies_visible_version(self):
        self.env["PATH"] = str(self.home / ".local/bin") + ":" + self.env["PATH"]
        for version in ("unreadable", "1.2.3"):
            with self.subTest(version=version):
                self.state["install_claude"] = version
                r = self.run_agents("install", "claude")
                if version == "unreadable":
                    self.assertNotEqual(r.returncode, 0)
                    self.assertIn("version is unreadable", r.stderr)
                else:
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertIn("1.2.3 installed", r.stdout)
                (self.home / ".local/bin/claude").unlink()

    def test_fresh_codex_install_prepares_standalone_without_npm(self):
        (self.bin / "codex").unlink()
        shutil.rmtree(self.home / ".codex/packages/standalone")
        self.env["PATH"] = str(self.home / ".local/bin") + ":" + self.env["PATH"]
        r = self.run_agents("install", "codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.home / ".local/bin/codex").is_file())
        self.assertFalse(any(c[0] == "npm" or "app-server" in c for c in self.state["calls"]))

    def test_codex_uninstall_preserves_user_data_and_unrelated_launcher(self):
        root = self.home / ".codex"
        (root / "config.toml").write_text("user config")
        launchers = self.home / ".local/bin"
        launchers.mkdir(parents=True)
        (launchers / "codex").symlink_to(self.bin / "codex")
        helper = launchers / "codex-code-mode-host"
        helper.write_text("unrelated executable")
        r = self.run_agents("uninstall", "codex", input="y\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((root / "packages/standalone").exists())
        self.assertFalse((launchers / "codex").is_symlink())
        self.assertEqual(helper.read_text(), "unrelated executable")
        self.assertEqual((root / "config.toml").read_text(), "user config")

    def test_unmanaged_codex_binary_is_rejected(self):
        binary = self.bin / "codex"
        content = binary.read_text()
        binary.unlink()
        binary.write_text(content)
        binary.chmod(0o755)
        r = self.run_update("codex")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unsupported installation", r.stderr)
        self.assertEqual(self.state["calls"], [])


if __name__ == "__main__":
    unittest.main()
