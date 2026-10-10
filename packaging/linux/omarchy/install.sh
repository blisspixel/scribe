#!/usr/bin/env bash
# Install Scribe from this GitHub tree and add the marked Hyprland voice block.
# Linux voice is experimental. This is not a tested Omarchy install.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it with: omarchy pkg add uv" >&2
  echo "The same package is: sudo pacman -S uv" >&2
  exit 1
fi

if [[ -f "${ROOT}/pyproject.toml" ]] && grep -q 'name = "scribe"' "${ROOT}/pyproject.toml"; then
  uv tool install --python 3.12 --force "scribe[tray] @ ${ROOT}"
else
  uv tool install --python 3.12 --force \
    "scribe[tray] @ git+https://github.com/blisspixel/scribe.git@v2.11.0"
fi

uv tool update-shell || true

if command -v scribe >/dev/null 2>&1; then
  scribe voice omarchy-install
elif [[ -x "${HOME}/.local/bin/scribe" ]]; then
  "${HOME}/.local/bin/scribe" voice omarchy-install
else
  echo "Open a new terminal, then run: scribe voice omarchy-install" >&2
  exit 1
fi

cat <<'EOF'
Scribe voice markers were requested.
This script is not a tested Omarchy install.
Run: scribe voice check
Confirm the chords with Super+K, then run: hyprctl reload
Also run: hyprctl configerrors
Upgrade by running this script again.
Linux voice stays experimental until microphone selection, focus changes,
correct-target insertion, cancellation, device loss, and recovery are shown live.
EOF
