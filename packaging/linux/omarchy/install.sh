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

cat <<'EOF'
Scribe installs a local ML runtime. Allow roughly 1-2 GB for a CPU tool environment
or several GB more for CUDA, plus download/cache space; versions and extras vary.
uv selects the PyTorch backend automatically from available drivers.
File model weights download separately on first use; voice keeps its own profile.
EOF

if [[ -f "${ROOT}/pyproject.toml" ]] && grep -q 'name = "scribe"' "${ROOT}/pyproject.toml"; then
  uv tool install --python 3.14 --force --torch-backend auto "scribe[tray] @ ${ROOT}"
else
  uv tool install --python 3.14 --force --torch-backend auto --with "av<19" \
    "scribe[tray] @ git+https://github.com/blisspixel/scribe.git@v2.13.1"
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
