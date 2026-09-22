# agents-cli

A small CLI to install, update, and uninstall **Claude, Codex, Amp, Pi, and Cursor Agent**.
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

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Tests use temporary files, fake CLIs, and Unix sockets; no real packages or services
are changed. Python is only required for tests.
