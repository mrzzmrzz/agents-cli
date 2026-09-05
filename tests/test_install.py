import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest


INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agents-install-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin_dir = self.root / "target-bin"
        self.bin_dir.mkdir()
        self.path_dir = self.root / "path"
        self.path_dir.mkdir()

        for command in ("chmod", "mkdir", "mktemp", "mv", "rm"):
            executable = shutil.which(command)
            if executable is None:
                self.fail(f"required test utility not found: {command}")
            (self.path_dir / command).symlink_to(executable)

        curl = self.path_dir / "curl"
        curl.write_text(
            "#!/bin/sh\n"
            "while [ \"$#\" -gt 0 ]; do\n"
            "  case \"$1\" in\n"
            "    -o) output=$2; shift 2 ;;\n"
            "    *) shift ;;\n"
            "  esac\n"
            "done\n"
            "printf '%s' \"$FAKE_CURL_CONTENT\" > \"$output\"\n"
            "[ \"$FAKE_CURL_RESULT\" = success ] || exit 22\n"
        )
        curl.chmod(0o755)

    def run_installer(self, *, result="success", content="new executable\n"):
        env = {
            "AGENTS_BIN_DIR": str(self.bin_dir),
            "FAKE_CURL_CONTENT": content,
            "FAKE_CURL_RESULT": result,
            "HOME": str(self.root / "home"),
            "PATH": str(self.path_dir),
        }
        return subprocess.run(
            ["/bin/sh", str(INSTALLER)],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def assert_no_download_temps(self):
        self.assertEqual(list(self.bin_dir.glob(".agents.*")), [])

    def test_successful_install_is_executable(self):
        result = self.run_installer(content="downloaded agent\n")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        installed = self.bin_dir / "agents"
        self.assertEqual(installed.read_text(), "downloaded agent\n")
        self.assertEqual(stat.S_IMODE(installed.stat().st_mode), 0o755)
        self.assert_no_download_temps()

    def test_partial_download_failure_preserves_prior_executable(self):
        installed = self.bin_dir / "agents"
        installed.write_text("working version\n")
        installed.chmod(0o751)

        result = self.run_installer(result="failure", content="partial download")

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(installed.read_text(), "working version\n")
        self.assertEqual(stat.S_IMODE(installed.stat().st_mode), 0o751)
        self.assert_no_download_temps()

    def test_success_replaces_symlink_without_changing_source(self):
        source = self.root / "source-agent"
        source.write_text("source version\n")
        source.chmod(0o744)
        installed = self.bin_dir / "agents"
        installed.symlink_to(source)

        result = self.run_installer(content="replacement version\n")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(installed.is_symlink())
        self.assertEqual(installed.read_text(), "replacement version\n")
        self.assertEqual(stat.S_IMODE(installed.stat().st_mode), 0o755)
        self.assertEqual(source.read_text(), "source version\n")
        self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o744)
        self.assert_no_download_temps()

    def test_failure_preserves_symlink_and_source(self):
        source = self.root / "source-agent"
        source.write_text("source version\n")
        source.chmod(0o744)
        installed = self.bin_dir / "agents"
        installed.symlink_to(source)

        result = self.run_installer(result="failure", content="partial download")

        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(installed.is_symlink())
        self.assertEqual(os.readlink(installed), str(source))
        self.assertEqual(source.read_text(), "source version\n")
        self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o744)
        self.assert_no_download_temps()


if __name__ == "__main__":
    unittest.main()
