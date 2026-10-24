# Omarchy install helpers

These scripts install and remove the GitHub release of Scribe on a Linux
machine. They are not a package-index submission, and they are not a tested
Omarchy installation.

`install.sh` requires `uv` (`omarchy pkg add uv` or `sudo pacman -S uv`). It
installs `scribe[tray]` on Python 3.14, then runs `scribe voice omarchy-install`.
From a checkout, that install uses the checkout. Otherwise it uses the
`v2.13.1` Git tag.

`uninstall.sh` runs `scribe voice omarchy-remove` and `uv tool uninstall scribe`.
It preserves XDG Scribe config, data, and state directories and legacy `~/.scribe`.
See [user storage paths](../../../docs/STORAGE.md) before upgrading resident voice.
Upgrade by running `install.sh` again.

After install, run `scribe voice check`, confirm the chords with Super+K, then
`hyprctl reload` and `hyprctl configerrors`. A zero exit from the check does
not open the microphone and does not validate hardware.

See [the deployment guide](../../../docs/DEPLOYMENT.md#omarchy) and
[the voice guide](../../../docs/VOICE.md#omarchy).
