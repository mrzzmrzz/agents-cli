#!/bin/sh
# agents-cli installer
#   curl -fsSL https://raw.githubusercontent.com/mrzzmrzz/agents-cli/main/install.sh | bash
set -e

BIN_DIR="${AGENTS_BIN_DIR:-$HOME/.local/bin}"
RAW_URL="https://raw.githubusercontent.com/mrzzmrzz/agents-cli/main/agents"

mkdir -p "$BIN_DIR"
curl -fsSL "$RAW_URL" -o "$BIN_DIR/agents"
chmod +x "$BIN_DIR/agents"
echo "✓ agents installed to $BIN_DIR/agents"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "⚠ $BIN_DIR is not in PATH, add to your shell config: export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac
