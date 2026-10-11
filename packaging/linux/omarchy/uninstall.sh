#!/usr/bin/env bash
# Remove Scribe's marked Hyprland blocks and the uv tool. User data stays.
set -euo pipefail

if command -v scribe >/dev/null 2>&1; then
  scribe voice omarchy-remove || true
elif [[ -x "${HOME}/.local/bin/scribe" ]]; then
  "${HOME}/.local/bin/scribe" voice omarchy-remove || true
else
  echo "scribe voice omarchy-remove was skipped because scribe is not on PATH." >&2
fi

if command -v uv >/dev/null 2>&1; then
  uv tool uninstall scribe || true
else
  echo "uv tool uninstall scribe was skipped because uv is not on PATH." >&2
fi

cat <<'EOF'
Scribe's Hyprland voice markers are removed when the command can run.
XDG Scribe config, data, and state directories and legacy ~/.scribe were left in place.
Defaults: ~/.config/scribe, ~/.local/share/scribe, ~/.local/state/scribe.
Absolute XDG_CONFIG_HOME, XDG_DATA_HOME, and XDG_STATE_HOME overrides are preserved too.
Recordings and transcripts in all selected output folders stay on disk.
Reload Hyprland with: hyprctl reload
Upgrade by running install.sh again.
EOF
