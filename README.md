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

## Design

- **Official native channels first**, no homebrew (its releases lag behind): claude / amp / opencode use their official install scripts; codex / pi use npm (their primary release channel, new versions land immediately).
- **Registry-driven**: each agent is one `via^install^update^uninstall` line in `meta()`; adding a tool takes one line in `KNOWN` and one in `meta()`.
- Install/update run quietly and replay the last 20 lines of output only on failure; a failed `update` of one agent doesn't stop the rest.
- `uninstall` asks for y/N confirmation; removing claude/amp only deletes the binaries and install directories, keeping `~/.claude` and other config.
- Colored output (tty detection, respects `NO_COLOR`), version column width computed dynamically.
