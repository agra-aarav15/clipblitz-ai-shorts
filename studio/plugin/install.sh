#!/usr/bin/env sh
# One command to put ClipBlitz Studio in an agent host.
#
#   sh plugin/install.sh
#
# It registers the marketplace this checkout ships (cloned from GitHub), installs
# the plugin, and prints where it landed. The plugin talks to the Studio checkout
# next to it on this machine only: nothing uploads, no API key, no account.
# If the Claude Code CLI is missing, install it first and re-run this script.
set -e

REPO="agra-aarav15/clipblitz-ai-shorts"
MARKET="clipblitz"
PLUGIN="clipblitz-studio"

if ! command -v claude >/dev/null 2>&1; then
  echo "The Claude Code CLI ('claude') is not on PATH."
  echo "Install Claude Code, then run this script again - or do two commands by hand:"
  echo "  claude plugin marketplace add $REPO"
  echo "  claude plugin install ${PLUGIN}@${MARKET}"
  exit 1
fi

claude plugin marketplace add "$REPO"
claude plugin install "${PLUGIN}@${MARKET}"

echo "installed ${PLUGIN}@${MARKET}"
echo "ask for clips in plain words, or run: /cut <video or URL> [how many]"
