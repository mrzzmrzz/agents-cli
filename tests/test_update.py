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
import json, os, pathlib, sys
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
    if not s.get("stale_after_restart"): s["server"] = s["codex"]
    finish()
if name == "sleep": finish()
if name == "restart-codex": restart()
if name == "systemctl":
    if "is-active" in args:
        manager = "user" if "--user" in args else "system"
        finish(0 if s.get("manager") == manager else 3)
    if "restart" in args: restart()
    finish(1)
if name == "npm":
    agent = "codex" if "@openai/codex@latest" in args else "pi"
    if s.get("update_fail") == agent: finish(1, "install failed")
    s[agent] = s.get("new_" + agent, s.get(agent, "1.0.0"))
    finish()
if args == ["--version"]: finish(text=name + " " + s[name])
if name == "codex":
    if args == ["features", "list"]:
        finish(1 if s.get("config_fail") else 0, "config check")
    if args == ["app-server", "daemon", "restart"]: restart()
    if args == ["app-server", "daemon", "version"]:
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
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.state_path = self.root / "state.json"
        self.state = {"codex": "1.0.0", "new_codex": "1.1.0",
                      "server": "1.0.0", "calls": []}
        for name in ("codex", "npm", "systemctl", "sleep", "restart-codex"):
            self.install_mock(name)
        self.env = {"PATH": str(self.bin) + ":/usr/bin:/bin",
                    "HOME": str(self.home), "NO_COLOR": "1",
                    "TEST_STATE": str(self.state_path)}
        self.socket = socket.socket(socket.AF_UNIX)
        self.addCleanup(self.socket.close)
        self.socket_path = self.home / ".codex/app-server-control/app-server-control.sock"
        self.socket_path.parent.mkdir(parents=True)
        self.socket.bind(str(self.socket_path))

    def install_mock(self, name):
        p = self.bin / name
        p.write_text("#!" + sys.executable + "\n" + MOCK)
        p.chmod(0o755)

    def run_update(self, *args):
        self.state_path.write_text(json.dumps(self.state))
        result = subprocess.run([ZSH, str(AGENTS), "update", *args],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.state = json.loads(self.state_path.read_text())
        return result

    def restarts(self):
        return [c for c in self.state["calls"]
                if "restart" in c or c[0] == "restart-codex"]

    def test_update_restarts_and_verifies_native_daemon(self):
        r = self.run_update("codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.restarts(), [["codex", "app-server", "daemon", "restart"]])
        self.assertIn("1.1.0 verified", r.stdout)

    def test_up_to_date_package_repairs_stale_server(self):
        self.state["codex"] = "1.1.0"
        r = self.run_update("codex")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.restarts()), 1)

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

    def test_update_failure_never_touches_server(self):
        self.state["update_fail"] = "codex"
        r = self.run_update("codex")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(any("app-server" in c for c in self.state["calls"]))

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
        self.state["manager"] = "user"
        r = self.run_update("codex")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.restarts(), [["systemctl", "--user", "restart", "codex-app-server.service"]])

    @unittest.skipUnless(os.geteuid() == 0, "system service only used as root")
    def test_root_systemd_service(self):
        self.state["manager"] = "system"
        r = self.run_update("codex")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.restarts(), [["systemctl", "restart", "codex-app-server.service"]])

    def test_explicit_restart_command(self):
        self.env["AGENTS_CODEX_RESTART_CMD"] = "restart-codex"
        r = self.run_update("codex")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.restarts(), [["restart-codex"]])

    def test_custom_codex_home_avoids_default_systemd_service(self):
        self.env["CODEX_HOME"] = str(self.home / ".codex-custom")
        self.socket.close()
        self.socket = socket.socket(socket.AF_UNIX)
        self.addCleanup(self.socket.close)
        p = Path(self.env["CODEX_HOME"]) / "app-server-control/app-server-control.sock"
        p.parent.mkdir(parents=True)
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


if __name__ == "__main__":
    unittest.main()
