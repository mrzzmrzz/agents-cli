# agents-cli

A minimal manager for AI coding-agent CLIs — one zsh script to install, update, and uninstall claude / codex / amp / pi / opencode.

```
● claude     2.1.247    native   ~/.local/share/claude/versions/2.1.247
● codex      0.150.1    npm      ~/.local/.../node_modules/@openai/codex/bin/codex.js
● amp        0.0.17...  native   ~/.amp/bin/amp
○ opencode   —          curl -fsSL https://opencode.ai/install | bash
```

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/mrzzmrzz/agents-cli/main/install.sh | bash
```

Installs to `~/.local/bin/agents` (override with `AGENTS_BIN_DIR`). Or clone and symlink:

```sh
git clone git@github.com:mrzzmrzz/agents-cli.git
ln -s "$PWD/agents-cli/agents" ~/bin/agents   # or any directory in PATH
```

## Usage

```
agents [show]            installed agents (version / channel / binary path)
agents list              all supported agents and their status
agents install <x|all>   install
agents update [x]        update everything, or just x
agents uninstall <x>     uninstall (asks for confirmation)
```

Aliases: `ls`=list, `up`=update, `rm`=uninstall.

## Updates and running agents

After a successful Codex update, `agents` checks the local app server's version.
If a server is listening on the default control socket and its version differs
from the installed CLI, `agents` validates the new CLI's configuration, restarts
the server, and verifies that it reports the installed version. This also repairs
a stale server when npm reports that Codex is already up to date. A stopped server
is left stopped. No polling process is installed.

Restart selection:

1. `AGENTS_CODEX_RESTART_CMD`, if set (a trusted shell command).
2. An active `codex-app-server.service` in the current user's systemd manager, or
   the system manager when running as root. Automatic systemd selection applies
   only to the default `~/.codex` home.
3. Codex's built-in `codex app-server daemon restart`.

The service must launch the updated CLI. If it still launches an older copy,
verification fails instead of claiming success. For a custom service manager:

```sh
AGENTS_CODEX_RESTART_CMD='systemctl --user restart my-codex.service' agents update codex
```

Restarting a shared server can disconnect clients and interrupt active tasks.
Only the local default control socket under `CODEX_HOME` (or `~/.codex`) is checked;
custom WebSocket endpoints and servers on other hosts are not restarted.

Other agents are updated without terminating their running sessions. Claude,
Amp, and Pi sessions should be restarted or resumed using the new executable.
OpenCode can also run a separate server (`opencode serve` / `opencode web`);
restart that server through its own manager. Those processes don't share Codex's
daemon lifecycle, so `agents` prints a reminder when their version changes rather
than guessing which processes to kill. See the official
[Claude update docs](https://code.claude.com/docs/en/setup),
[Amp update docs](https://ampcode.com/docs/cli),
[Pi modes](https://github.com/earendil-works/pi/tree/main/packages/coding-agent), and
[OpenCode server docs](https://opencode.ai/docs/server/).

An update or Codex restart/verification failure returns a nonzero exit status,
while remaining agents in a batch are still updated. Retrying `agents update codex`
rechecks the server even if the package version has not changed.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Tests use isolated fake CLIs and a temporary Unix socket; no packages or real
agent services are changed. Python is needed only to run tests.

## Design

- **Official native channels first**, no homebrew (its releases lag behind): claude / amp / opencode use their official install scripts; codex / pi use npm (their primary release channel, new versions land immediately).
- **Registry-driven**: each agent is one `via^install^update^uninstall` line in `meta()`; adding a tool takes one line in `KNOWN` and one in `meta()`.
- Install/update run quietly and replay the last 20 lines of output only on failure; a failed `update` of one agent doesn't stop the rest.
- `uninstall` asks for y/N confirmation; removing claude/amp only deletes the binaries and install directories, keeping `~/.claude` and other config.
- Colored output (tty detection, respects `NO_COLOR`), version column width computed dynamically.
