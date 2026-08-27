# agents-cli

极简的 AI coding-agent 管理入口 — 一个 zsh 脚本，统一管理 claude / codex / amp / pi / opencode 的安装、更新、卸载。
A minimal manager for AI coding-agent CLIs, in a single zsh script.

```
● claude     2.1.247    native   ~/.local/share/claude/versions/2.1.247
● codex      0.150.1    npm      ~/.local/.../node_modules/@openai/codex/bin/codex.js
● amp        0.0.17...  native   ~/.amp/bin/amp
○ opencode   —          curl -fsSL https://opencode.ai/install | bash
```

## 安装 / Install

```sh
curl -fsSL https://raw.githubusercontent.com/mrzzmrzz/agents-cli/main/install.sh | bash
```

装到 `~/.local/bin/agents`（可用 `AGENTS_BIN_DIR` 覆盖）。或者 clone 后 symlink：

```sh
git clone git@github.com:mrzzmrzz/agents-cli.git
ln -s "$PWD/agents-cli/agents" ~/bin/agents   # 或任意 PATH 内目录
```

## 用法 / Usage

```
agents [show]            已安装的 agent (版本 / 渠道 / 二进制路径)
agents list              全部支持的 agent 及安装状态
agents install <x|all>   安装
agents update [x]        更新全部, 或只更新 x
agents uninstall <x>     卸载 (需确认)
```

别名 / aliases: `ls`=list, `up`=update, `rm`=uninstall。

## 设计 / Design

- **优先官方原生渠道**，不走 homebrew（发版滞后）：claude / amp / opencode 用官方安装脚本，codex / pi 用 npm（官方第一渠道，发版即可用）。
- **Registry 驱动**：每个 agent 是 `meta()` 里的一行 `via^install^update^uninstall`，新增工具只需在 `KNOWN` 和 `meta()` 各加一行。
- 更新/安装静默执行，只在失败时回放输出的最后 20 行；`update` 单个失败不中断其余。
- `uninstall` 需要 y/N 确认；claude/amp 的卸载只删二进制与安装目录，保留 `~/.claude`、配置等。
- 输出带颜色（tty 检测，尊重 `NO_COLOR`），版本列宽动态计算。
