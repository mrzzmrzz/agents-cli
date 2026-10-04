import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


AGENTS = Path(__file__).resolve().parents[1] / "agents"
ZSH = shutil.which("zsh")


def find_rsync():
    """A real rsync 3.x (macOS's openrsync lacks --ignore-missing-args)."""
    for candidate in ("/opt/homebrew/bin/rsync", "/usr/local/bin/rsync", shutil.which("rsync")):
        if candidate and Path(candidate).exists():
            out = subprocess.run([candidate, "--version"], capture_output=True, text=True).stdout
            if out.startswith("rsync  version 3"):
                return candidate
    return None


RSYNC = find_rsync()

# Stands in for ssh: runs the remote command locally with HOME set to that host's tree.
FAKE_SSH = r'''
import os, pathlib, subprocess, sys
args = sys.argv[1:]
while args and args[0] == "-o":
    args = args[2:]
host, command = args[0], " ".join(args[1:])
home = pathlib.Path(os.environ["FAKE_REMOTES"]) / host
sys.exit(subprocess.call(["/bin/sh", "-c", command], cwd=home, env={**os.environ, "HOME": str(home)}))
'''

PRICES = {
    "claude-test": {"input_cost_per_token": 1e-06, "output_cost_per_token": 1e-05,
                    "cache_creation_input_token_cost": 2e-06,
                    "cache_creation_input_token_cost_above_1hr": 3e-06,
                    "cache_read_input_token_cost": 1e-07},
    "gpt-test": {"input_cost_per_token": 1e-06, "output_cost_per_token": 1e-05,
                 "cache_read_input_token_cost": 1e-07,
                 "input_cost_per_token_above_200k_tokens": 2e-06,
                 "output_cost_per_token_above_200k_tokens": 2e-05,
                 "cache_read_input_token_cost_above_200k_tokens": 2e-07},
}


def jsonl(path, *rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def claude_reply(msg_id, ts, inp, cw, cw1h, cr, out, model="claude-test", request="req"):
    entry = {"type": "assistant", "timestamp": ts,
             "message": {"id": msg_id, "model": model,
                         "usage": {"input_tokens": inp, "output_tokens": out,
                                   "cache_creation_input_tokens": cw, "cache_read_input_tokens": cr,
                                   "cache_creation": {"ephemeral_1h_input_tokens": cw1h}}}}
    if request:
        entry["requestId"] = request
    return entry


def codex_meta(**payload):
    return {"timestamp": "2026-01-01T00:00:00Z", "type": "session_meta", "payload": payload}


def codex_count(ordinal, ts, total, last):
    def usage(inp, cached, out):
        return {"input_tokens": inp, "cached_input_tokens": cached,
                "output_tokens": out, "total_tokens": inp + out}
    return {"timestamp": ts, "ordinal": ordinal, "type": "event_msg",
            "payload": {"type": "token_count",
                        "info": {"total_token_usage": usage(*total), "last_token_usage": usage(*last)}}}


def codex_turn(ordinal, ts, model="gpt-test"):
    return {"timestamp": ts, "ordinal": ordinal, "type": "turn_context", "payload": {"model": model}}


def restamp(entries, day):
    """Replayed history: same records, new timestamps (as Codex writes them)."""
    return [{**e, "timestamp": f"{day}T12:00:00Z"} for e in entries]


@unittest.skipUnless(ZSH, "zsh is required")
class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agents-sessions-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "home"
        self.remotes = self.root / "remotes"
        self.archive = self.root / "archive"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        ssh = self.bin / "ssh"
        ssh.write_text("#!" + sys.executable + "\n" + FAKE_SSH)
        ssh.chmod(0o755)
        self.config = self.root / "sync.conf"
        self.config.write_text(f"archive {self.archive}\nself laptop\n"
                               f"host laptop -\nhost server server {RSYNC or 'rsync'}\n")
        pricing = self.root / "prices.json"
        pricing.write_text(json.dumps(PRICES))
        self.env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.home), "NO_COLOR": "1",
                    "TZ": "UTC", "AGENTS_SYNC_CONFIG": str(self.config),
                    "AGENTS_PRICING": str(pricing), "FAKE_REMOTES": str(self.remotes)}
        if RSYNC:
            self.env["AGENTS_RSYNC"] = RSYNC

    def agents(self, *args):
        return subprocess.run([ZSH, str(AGENTS), *args], env=self.env,
                              capture_output=True, text=True, timeout=60)

    def usage_json(self, *args):
        r = self.agents("usage", "--json", *args)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    # ── sync ──

    @unittest.skipUnless(RSYNC, "rsync 3.x is required")
    def test_sync_archives_session_items_from_every_host(self):
        jsonl(self.home / ".claude/projects/p/a.jsonl", {"n": 1})
        (self.home / ".claude/settings.json").write_text("{}")
        jsonl(self.remotes / "server/.codex/sessions/2026/01/01/r.jsonl", {"n": 2})
        (self.remotes / "server/.codex/auth.json").write_text("secret")

        r = self.agents("sync")

        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.archive / "hosts/laptop/.claude/projects/p/a.jsonl").exists())
        self.assertTrue((self.archive / "hosts/server/.codex/sessions/2026/01/01/r.jsonl").exists())
        self.assertFalse((self.archive / "hosts/laptop/.claude/settings.json").exists())
        self.assertFalse((self.archive / "hosts/server/.codex/auth.json").exists())
        log = (self.archive / "archive.log").read_text().splitlines()
        self.assertEqual(len(log), 2)  # one rsync per host
        self.assertTrue(all(line.endswith("\tok") for line in log))
        self.assertIn("up to date", self.agents("sync").stdout)

    @unittest.skipUnless(RSYNC, "rsync 3.x is required")
    def test_sync_never_deletes_archived_sessions(self):
        session = self.home / ".claude/projects/p/a.jsonl"
        jsonl(session, {"n": 1})
        self.agents("sync", "claude", "laptop")
        session.unlink()

        r = self.agents("sync", "claude", "laptop")

        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.archive / "hosts/laptop/.claude/projects/p/a.jsonl").exists())

    @unittest.skipUnless(RSYNC, "rsync 3.x is required")
    def test_failed_host_is_reported_and_others_continue(self):
        jsonl(self.home / ".claude/projects/p/a.jsonl", {"n": 1})  # server has no home at all

        r = self.agents("sync", "claude")

        self.assertNotEqual(r.returncode, 0)
        self.assertIn("failed", r.stdout)
        self.assertTrue((self.archive / "hosts/laptop/.claude/projects/p/a.jsonl").exists())

    def test_sync_rejects_unknown_names_and_missing_config(self):
        r = self.agents("sync", "nope")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unknown agent or host", r.stderr)

        self.env["AGENTS_SYNC_CONFIG"] = str(self.root / "missing.conf")
        r = self.agents("sync")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no sync config", r.stderr)

    def test_readme_config_example_parses(self):
        readme = (AGENTS.parent / "README.md").read_text()
        block = readme.split("archive ~/", 1)[1].split("```", 1)[0]
        self.config.write_text("archive ~/" + block)

        r = self.agents("sync", "nope")

        self.assertIn("hosts: laptop workstation gpu-box", r.stderr)

    def test_config_rejects_reserved_host_names_and_extra_fields(self):
        for line in ("host daily somewhere", "host codex somewhere", "host a b c d"):
            with self.subTest(line=line):
                self.config.write_text(f"archive {self.archive}\n{line}\n")
                r = self.agents("sync")
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("sync.conf", r.stderr)

    def test_config_tolerates_crlf_and_hash_inside_values(self):
        archive = self.root / "arc#1"
        self.config.write_bytes(f"archive {archive}  # comment\r\nhost box box\r\n".encode())

        r = self.agents("sync", "nope")

        self.assertIn("hosts: box", r.stderr)
        r = self.agents("usage")
        self.assertIn(f"no archive at {archive}", r.stderr)

    @unittest.skipUnless(RSYNC, "rsync 3.x is required")
    def test_sync_copies_linked_items_but_never_files_they_point_into(self):
        shared = self.root / "shared/memories"
        shared.mkdir(parents=True)
        (shared / "note.md").write_text("remember")
        (self.home / ".codex").mkdir(parents=True)
        (self.home / ".codex/memories").symlink_to(shared)  # item linked outside home
        (self.home / ".codex/auth.json").write_text("secret")
        jsonl(self.home / ".codex/sessions/s.jsonl", {"n": 1})
        (self.home / ".codex/sessions/leak.json").symlink_to("../auth.json")

        r = self.agents("sync", "codex", "laptop")

        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        archived = self.archive / "hosts/laptop/.codex"
        self.assertEqual((archived / "memories/note.md").read_text(), "remember")
        self.assertTrue((archived / "sessions/leak.json").is_symlink())
        self.assertFalse((archived / "auth.json").exists())

    def test_sync_refuses_rsync_without_version_3(self):
        fake = self.bin / "openrsync"
        fake.write_text("#!/bin/sh\necho 'openrsync: protocol version 29'\n")
        fake.chmod(0o755)
        self.env["AGENTS_RSYNC"] = str(fake)

        r = self.agents("sync")

        self.assertNotEqual(r.returncode, 0)
        self.assertIn("needs rsync 3.x", r.stderr)
        self.assertFalse((self.archive / "archive.log").exists())

    # ── usage ──

    def write_archive(self):
        hosts = self.archive / "hosts"
        jsonl(hosts / "laptop/.claude/projects/p/s.jsonl",
              # one response, logged per content block; output grows to its final count
              claude_reply("m1", "2026-01-05T10:00:00Z", 10, 100, 40, 1000, 2),
              claude_reply("m1", "2026-01-05T10:00:01Z", 10, 100, 40, 1000, 2),
              claude_reply("m1", "2026-01-05T10:00:02Z", 10, 100, 40, 1000, 199),
              # newer Claude Code versions omit requestId
              claude_reply("m3", "2026-01-05T11:00:00Z", 5, 0, 0, 50, 1, request=None),
              claude_reply("m3", "2026-01-05T11:00:01Z", 5, 0, 0, 50, 7, request=None),
              claude_reply("m0", "2026-01-05T10:00:03Z", 0, 0, 0, 0, 0, model="<synthetic>"))
        jsonl(hosts / "server/.claude/projects/p/s.jsonl",
              claude_reply("m2", "2026-02-01T00:00:00Z", 20, 0, 0, 0, 7))

        codex = hosts / "server/.codex/sessions/2026/01"
        parent = [codex_count(1, "2026-01-02T00:00:01Z", (100, 60, 10), (100, 60, 10)),  # before its model
                  codex_turn(2, "2026-01-02T00:00:02Z"),
                  codex_count(3, "2026-01-02T00:00:03Z", (100, 60, 10), (100, 60, 10)),  # re-sent event
                  codex_count(4, "2026-01-02T00:00:04Z", (300_100, 60, 30), (300_000, 0, 20))]
        jsonl(codex / "02/rollout-a.jsonl", codex_meta(id="a"), *parent)
        # A sub-agent thread replays its parent, re-stamped, then works on its own;
        # its start ordinal counts the parent's events, so it says nothing about its lines.
        jsonl(codex / "03/rollout-b.jsonl", codex_meta(id="b", subagent_history_start_ordinal=99),
              *restamp(parent, "2026-01-03"), codex_turn(5, "2026-01-03T13:00:00Z"),
              codex_count(6, "2026-01-03T13:00:01Z", (300_150, 60, 35), (50, 0, 5)))
        # ... and a user fork replays it with no marker at all.
        jsonl(codex / "04/rollout-c.jsonl", codex_meta(id="c", forked_from_id="a"),
              *restamp(parent, "2026-01-04"),
              codex_count(5, "2026-01-04T13:00:00Z", (300_160, 60, 36), (60, 0, 6)))

    def test_usage_counts_each_response_once_at_its_final_usage(self):
        self.write_archive()

        report = self.usage_json("total")

        rows = {row["agent"]: row for row in report["rows"]}
        self.assertEqual(rows["claude"], {
            "period": "total", "agent": "claude", "input": 35, "output": 213,
            "cache_write": 100, "cache_read": 1050, "total": 1398,
            # 60 5-minute + 40 1-hour cache writes
            "cost": round(35e-6 + 60 * 2e-6 + 40 * 3e-6 + 1050 * 1e-7 + 213e-5, 4)})
        codex = rows["codex"]
        self.assertEqual((codex["input"], codex["cache_read"], codex["output"]),
                         (40 + 300_000 + 50 + 60, 60, 10 + 20 + 5 + 6))
        # the 300k-token prompt is billed at the above-200k tier
        expected = (40e-6 + 60e-7 + 10e-5) + (300_000 * 2e-6 + 20 * 2e-5) + (50e-6 + 5e-5) + (60e-6 + 6e-5)
        self.assertAlmostEqual(codex["cost"], round(expected, 4))
        self.assertEqual(report["unpriced_models"], [])

    def test_replayed_responses_stay_on_their_original_day(self):
        self.write_archive()

        daily = self.usage_json("daily", "codex")

        self.assertEqual([(r["period"], r["total"]) for r in daily["rows"]],
                         [("2026-01-02", 300_130), ("2026-01-03", 55), ("2026-01-04", 66)])

    def test_usage_filters_and_groups(self):
        self.write_archive()

        monthly = self.usage_json("claude", "--by", "host")
        self.assertEqual([(r["period"], r["host"], r["total"]) for r in monthly["rows"]],
                         [("2026-01", "laptop", 1371), ("2026-02", "server", 27)])

        until = self.usage_json("daily", "--since", "20260103", "--until", "2026-01-04", "--by", "none")
        self.assertEqual([(r["period"], r["total"]) for r in until["rows"]],
                         [("2026-01-03", 55), ("2026-01-04", 66)])

        weekly = self.usage_json("weekly", "codex", "--by", "none")
        self.assertEqual([r["period"] for r in weekly["rows"]], ["2025-12-29"])  # Monday

        server = self.usage_json("total", "server", "codex", "--by", "model", "--no-cost")
        self.assertEqual([r["model"] for r in server["rows"]], ["gpt-test"])
        self.assertNotIn("cost", server["totals"])

    def test_earliest_copy_decides_model_and_price(self):
        codex = self.archive / "hosts/server/.codex/sessions/2026/01"
        same = ((1000, 0, 100), (1000, 0, 100))
        # the larger file is parsed first, but the smaller one holds the original
        jsonl(codex / "02/big.jsonl", codex_turn(1, "2026-01-02T00:00:00Z", model="cheap"),
              codex_count(2, "2026-01-02T00:00:00Z", *same), {"pad": "x" * 10_000})
        jsonl(codex / "01/small.jsonl", codex_turn(1, "2026-01-01T00:00:00Z", model="pricey"),
              codex_count(2, "2026-01-01T00:00:00Z", *same))
        prices = json.loads(Path(self.env["AGENTS_PRICING"]).read_text())
        prices["cheap"] = {"input_cost_per_token": 1e-06, "output_cost_per_token": 1e-06}
        prices["pricey"] = {"input_cost_per_token": 1e-04, "output_cost_per_token": 1e-04}
        Path(self.env["AGENTS_PRICING"]).write_text(json.dumps(prices))

        report = self.usage_json("total", "--by", "model")

        self.assertEqual([(r["model"], r["cost"]) for r in report["rows"]], [("pricey", 0.11)])

    def test_offset_timestamps_are_converted_to_utc(self):
        jsonl(self.archive / "hosts/laptop/.claude/projects/p/s.jsonl",
              claude_reply("m1", "2026-01-02T01:00:00+08:00", 1, 0, 0, 0, 1))  # Jan 1, 17:00 UTC

        daily = self.usage_json("daily", "--by", "none")

        self.assertEqual([r["period"] for r in daily["rows"]], ["2026-01-01"])

    def test_days_follow_the_local_time_zone(self):
        self.write_archive()
        self.env["TZ"] = "Asia/Shanghai"  # UTC+8: both days unchanged

        daily = self.usage_json("daily", "claude", "--by", "none")

        self.assertEqual([r["period"] for r in daily["rows"]], ["2026-01-05", "2026-02-01"])
        self.env["TZ"] = "America/Los_Angeles"  # UTC-8: Feb 1 00:00 UTC is still Jan 31
        daily = self.usage_json("daily", "claude", "--by", "none")
        self.assertEqual([r["period"] for r in daily["rows"]], ["2026-01-05", "2026-01-31"])

    def test_bad_logs_are_skipped_not_fatal(self):
        self.write_archive()
        broken = self.archive / "hosts/laptop/.claude/projects/p/broken.jsonl"
        jsonl(broken, claude_reply("x1", "2026", 1, 0, 0, 0, 1),           # malformed timestamp
              claude_reply("x2", 1700000000, 1, 0, 0, 0, 1),               # numeric timestamp
              claude_reply("x3", "2026-01-05T10:00:00Z", "5", 0, 0, 0, 1))  # string count -> 0
        broken.write_text(broken.read_text() + '{"message": {"usage": {\n')  # truncated line
        unreadable = self.archive / "hosts/laptop/.claude/projects/p/locked.jsonl"
        jsonl(unreadable, claude_reply("x4", "2026-01-05T10:00:00Z", 1, 0, 0, 0, 1))
        unreadable.chmod(0)
        self.addCleanup(unreadable.chmod, 0o644)

        r = self.agents("usage", "total", "claude", "--json")

        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["totals"]["total"], 1398 + 1)
        if os.geteuid() != 0:
            self.assertIn("skipped unreadable", r.stderr)

    def test_table_ends_with_totals(self):
        self.write_archive()
        lines = self.agents("usage", "monthly").stdout.splitlines()
        self.assertTrue(lines[0].startswith("MONTHLY"))
        self.assertTrue(lines[-1].startswith("TOTAL"))

        lines = self.agents("usage", "total", "--by", "none").stdout.splitlines()
        self.assertEqual(len(lines), 2)  # header and the total itself

    def test_unpriced_models_are_reported(self):
        jsonl(self.archive / "hosts/laptop/.claude/projects/p/s.jsonl",
              claude_reply("m1", "2026-01-05T10:00:00Z", 1, 0, 0, 0, 1, model="no-input-price"),
              claude_reply("m2", "2026-01-05T10:00:00Z", 1, 0, 0, 0, 1, model="mystery"))
        prices = json.loads(Path(self.env["AGENTS_PRICING"]).read_text())
        prices["no-input-price"] = {"output_cost_per_token": 1e-05}
        Path(self.env["AGENTS_PRICING"]).write_text(json.dumps(prices))

        report = self.usage_json("total")

        self.assertEqual(report["unpriced_models"], ["mystery", "no-input-price"])
        self.assertEqual(report["totals"]["cost"], 0)

    def test_usage_without_sync_config_reads_local_sessions(self):
        self.env["AGENTS_SYNC_CONFIG"] = str(self.root / "missing.conf")
        jsonl(self.home / ".claude/projects/p/s.jsonl",
              claude_reply("m1", "2026-03-01T00:00:00Z", 1, 0, 0, 0, 1))

        report = self.usage_json("total", "--by", "host")

        self.assertEqual(report["rows"][0]["host"], "local")
        self.assertEqual(report["totals"]["total"], 2)

    def test_usage_argument_errors(self):
        r = self.agents("usage")
        self.assertIn("no archive", r.stderr)

        self.write_archive()
        for args, message in ((["--bogus"], "unknown argument"), (["--by"], "--by takes"),
                              (["--by", "agent,nope"], "--by takes"), (["--since", "x"], "bad date")):
            with self.subTest(args=args):
                r = self.agents("usage", *args)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn(message, r.stderr)


if __name__ == "__main__":
    unittest.main()
