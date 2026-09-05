# agents-cli

A small CLI to install, update, and uninstall **Claude, Codex, Amp, Pi, and OpenCode**.
One zsh script, using official native installers for Claude / Amp / OpenCode and npm for Codex / Pi.

## Install

Requires **zsh**, **bash**, and **curl**; **Node.js and npm** for Codex and Pi.

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
```

Aliases: `ls` → `list`, `up` → `update`, `rm` → `uninstall`.

Updates and uninstalls accept default native installation paths and packages under
the active npm global root. Other layouts are rejected rather than modifying the
wrong copy; use their original installer or fix `PATH`. The displayed channel is
the supported channel, not automatic installation detection.

## Updates and running agents

- **Codex:** checks the local app server under `CODEX_HOME` (default `~/.codex`)
  after every update, including retries. A stale server is restarted and its version
  verified; a stopped server is not started. Native daemon updates also prepare and
  validate the separate standalone binary before restarting.
- **Service selection:** uses `AGENTS_CODEX_RESTART_CMD` if set, then an active
  `codex-app-server.service` (user manager, or system manager as root), otherwise
  the native daemon. Automatic systemd selection requires the default Codex home.
  Custom/systemd services must launch the updated CLI.
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

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Tests use temporary files, fake CLIs, and Unix sockets; no real packages or services
are changed. Python is only required for tests.
