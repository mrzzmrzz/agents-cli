#!/bin/sh
# agents-cli installer
#   curl -fsSL https://raw.githubusercontent.com/mrzzmrzz/agents-cli/main/install.sh | bash
set -e

BIN_DIR="${AGENTS_BIN_DIR:-$HOME/.local/bin}"
RAW_URL="https://raw.githubusercontent.com/mrzzmrzz/agents-cli/main/agents"

mkdir -p "$BIN_DIR"
tmp=$(mktemp "$BIN_DIR/.agents.XXXXXX")
trap 'rm -f "$tmp"' EXIT
trap 'exit 1' HUP INT TERM
curl -fsSL "$RAW_URL" -o "$tmp"
chmod 755 "$tmp"
mv -f "$tmp" "$BIN_DIR/agents"
echo "✓ agents installed to $BIN_DIR/agents"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "⚠ $BIN_DIR is not in PATH, add to your shell config: export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac
