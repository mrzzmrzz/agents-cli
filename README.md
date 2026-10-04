# agents-cli

A small CLI to install, update, and uninstall **Claude, Codex, Amp, Pi, and Cursor Agent**,
and to archive their sessions across machines and report token usage.
One zsh script, using official native installers for Claude / Codex / Amp / Cursor Agent and npm for Pi.

## Install

Requires **zsh**, **bash**, and **curl**; **Node.js and npm** for Pi.

```sh
curl -fsSL https://raw.githubusercontent.com/mrzzmrzz/agents-cli/main/install.sh | bash
```

Installs to `~/.local/bin/agents`; add `~/.local/bin` to your `PATH`.
Set `AGENTS_BIN_DIR` when running the installer to use another directory.

## Usage

```
agents                  Show installed agents, versions, and paths
agents list             List all supported agents
agents install <x|all>  Install one agent or all missing agents
agents update [x]       Update one agent or all installed agents
agents uninstall <x>    Uninstall an agent (asks for confirmation)
agents sync [agent] [host]   Archive sessions from configured hosts
agents usage [options]       Token usage and cost across sessions
```

Aliases: `ls` → `list`, `up` → `update`, `rm` → `uninstall`.

Updates and uninstalls accept default native installation paths and packages under
the active npm global root. Other layouts are rejected rather than modifying the
wrong copy; use their original installer or fix `PATH`. The displayed channel is
the supported channel, not automatic installation detection.

Codex installs and updates use `curl -fsSL https://chatgpt.com/codex/install.sh | sh`
with installer prompts disabled. `CODEX_HOME` and `CODEX_INSTALL_DIR` follow the
official installer defaults (`~/.codex` and `~/.local/bin`). Uninstall removes only
the standalone package and its launchers, preserving configuration and sessions.

If Codex was previously installed through npm, migrate once with the official
installer, then ensure its launcher precedes the npm command on `PATH`:

```sh
curl -fsSL https://chatgpt.com/codex/install.sh | sh
export PATH="${CODEX_INSTALL_DIR:-$HOME/.local/bin}:$PATH"
```

Existing npm installations are not automatically removed. Custom services that
launch an npm path must be updated to launch the standalone CLI.

Cursor Agent installs with `curl -fsSL https://cursor.com/install | bash`.
The command registered here is `cursor-agent`; the official installer also links
`agent` to the same binary under `~/.local/share/cursor-agent`. Updates use
`cursor-agent update`. Uninstall removes that package directory and only the
`cursor-agent` and `agent` launchers that point into it, preserving `~/.cursor`.

## Updates and running agents

- **Codex:** checks the local app server under `CODEX_HOME` (default `~/.codex`)
  after every update, including retries. A stale server with a detected restart
  manager is restarted and its version verified; a stopped server is not started.
  The CLI and native daemon share the
  standalone installation managed by the official Codex installer.
- **Service selection:** uses `AGENTS_CODEX_RESTART_CMD` if set, then an active
  `codex-app-server.service` (user manager, or system manager as root), then
  the native daemon if its PID record matches a live process and its start time.
  Automatic systemd selection requires the default Codex home.
  Custom/systemd services must launch the updated CLI.
- **Unmanaged Codex servers:** a running socket alone does not establish daemon
  ownership. If no restart manager is detected, the update succeeds with a reminder
  showing the server's unchanged version. Restart it through its original launcher
  after active tasks finish, or configure `AGENTS_CODEX_RESTART_CMD`.
- **Other agents:** existing sessions and separately managed servers need their own
  restart. The CLI prints a reminder instead of terminating unknown processes.

For a custom Codex service, supply a trusted shell command:

```sh
AGENTS_CODEX_RESTART_CMD='systemctl --user restart my-codex.service' agents update codex
```

**Restarts can interrupt active tasks.** Remote servers and custom WebSocket endpoints
are not managed. Batch updates continue after failures and return a nonzero exit code
if any update or verification fails. Use cron or a systemd timer for periodic runs;
`agents` does not install a scheduler.

## Sessions: sync and usage

```
agents sync [agent] [host]   Archive Claude / Codex sessions from your machines
agents usage [options]       Token usage and estimated cost across the archive
```

`agents sync` copies each host's session logs into one archive directory (a synced
folder such as OneDrive or Dropbox works well), one rsync per host over SSH. It is
one-way: sessions deleted on a host, for example by the agent's own cleanup, stay in
the archive, while a file that changes on the host replaces its archived copy. Only
session data is copied, never credentials or settings:

| Agent  | Archived from the agent's home |
|--------|--------------------------------|
| claude | `~/.claude/projects` (transcripts and per-project memory), `history.jsonl` |
| codex  | `~/.codex/sessions`, `archived_sessions`, `memories`, `history.jsonl`, `session_index.jsonl`, `AGENTS.md` |

The archive mirrors these paths as `<archive>/hosts/<host>/.claude/…` and `.codex/…`;
an item that is a symlink to somewhere outside the agent's home is archived as content.

Hosts are configured per machine in `~/.config/agents/sync.conf` (or
`$AGENTS_SYNC_CONFIG`), never in this repository:

```
archive ~/OneDrive/agents          # where sessions are archived
self    laptop                     # this machine; read from $HOME, not over SSH
rsync   /opt/homebrew/bin/rsync    # optional: the local rsync
host    laptop       100.64.0.1    /opt/homebrew/bin/rsync
host    workstation  100.64.0.2    /opt/homebrew/bin/rsync
host    gpu-box      gpu-box       # any ssh target, including ~/.ssh/config aliases
```

A host line's optional third field is the rsync on that host. Sync needs rsync 3.x
on both ends; macOS ships `openrsync` at `/usr/bin/rsync`, so point Macs at
Homebrew's (`AGENTS_RSYNC` overrides the local one too). SSH must work
non-interactively (keys; host keys already accepted). Host names cannot be a period
or agent name. Run `agents sync` from one machine at a time, so the synced folder
never sees two writers of one file.

`agents usage` reads the archive (or this machine's own sessions when sync is not
configured) and reports tokens and estimated API cost:

```
agents usage                          # monthly, per agent
agents usage daily --since 2026-09-01
agents usage total --by host,model
agents usage codex workstation weekly --json
```

Periods are `daily`, `weekly` (labelled by their Monday), `monthly` (default) and
`total`, in this machine's time zone; `--since`/`--until` are inclusive days. `--by`
groups by any of `agent`, `host`, `model` (or `none`); agent and host names filter.

Each model response is counted once, at its final usage, wherever it was logged:
Claude Code writes a response once per content block (only the last carries the
final output count), and Codex sub-agents and forks replay their parent's history;
a replayed response stays on the day it actually happened (with `--since`, a parent
file untouched since then is skipped, so its replay may count on the replay day).
Malformed lines are ignored; unreadable files are skipped with a warning.

Costs are estimates from [LiteLLM's price table](https://github.com/BerriAI/litellm),
downloaded from GitHub at most once a day into `~/.cache/agents` (`AGENTS_PRICING`
points at a local copy instead; `--no-cost` skips pricing). Long-context tiers and
1-hour cache writes are priced separately; models missing from the table are listed
as unpriced. Parsing runs on every CPU core, and `--since` skips files untouched
since then; installing `orjson` makes it faster still. Requires **python3** (3.8+).

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Tests use temporary files, fake CLIs, and Unix sockets; no real packages or services
are changed. Sync tests need rsync 3.x.
