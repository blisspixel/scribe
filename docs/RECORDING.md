# Recording Guide

Scribe records authorized meetings through OBS Studio. Recording is treated as a
data-preservation workflow: an existing capture is protected, startup requires
positive progress, unexpected stops remain failures, and usable partial media is
retained.

## Before an important recording

Install OBS Studio, configure the intended scene and audio sources, and make one
short test recording in OBS itself. Confirm that the file contains every expected
audio channel.

Then run the read-only Scribe preflight:

```bash
scribe doctor
scribe rec --check
```

The check verifies the configured OBS WebSocket endpoint and reports whether an
OBS process is running without an available control port. It does not start or
stop a recording.

For high-value meetings, also verify these external conditions:

- The destination disk has enough free space for the full session.
- OBS is using the intended recording path, format, encoder, scene, and profile.
- The microphone, system audio, and capture sources show activity in OBS.
- Sleep, automatic restart, battery, and cloud-sync policies cannot interrupt the
  session.
- Required recording consent and authorization have been obtained.

## Start and stop

```bash
scribe rec "Team Meeting"
scribe rec "Cloud Meeting" --method openrouter --max-spend 5
```

`scribe record` exposes the advanced form of the same workflow. Scribe shows the
effective output folder and settings before capture. During a terminal recording,
type `s` or `stop` and press Enter, or press Ctrl+C, to request a safe stop.

Recording and transcription have separate data boundaries. The default `auto`
method transcribes locally. An explicit `--method openrouter` uploads the finished
recording after capture, and `--max-spend` sets that input's
reported-cost guard. A provider key limit is still required for an absolute cap.
See [Cloud Transcription](CLOUD_TRANSCRIPTION.md) before enabling upload.

Keep the OBS window available during an important session. Its meters and status
bar are the independent source of truth for capture devices and encoder health.

## Startup proof

The normal path controls OBS through its local WebSocket interface. Scribe does
not accept an active-state flag by itself. After requesting start, at least one
OBS output counter, bytes or duration, must increase between samples.

Scribe also snapshots existing media and looks for a new MP4 or MKV whose size is
increasing. File visibility is separate from encoder progress because OBS can
buffer writes or save to a path Scribe cannot inspect. When WebSocket counters
prove capture but the file is not yet visible, Scribe keeps recording and prints
a warning instead of stopping a potentially valid meeting.

The emergency command-line path has no authoritative output counters, so it
requires a fresh growing file before it reports capture as confirmed.

## Defensive control rules

Scribe applies these rules in every mode:

- An OBS recording that was already active is never stopped, replaced, or joined.
- A growing media file is never moved or renamed.
- An unreachable OBS process is never terminated automatically.
- Recovery is refused when an OBS recording mux process indicates active capture.
- A stale, unreachable OBS process may trigger one non-destructive second-instance
  launch using OBS's supported multi-instance and start-recording options.
- An unexpected OBS stop preserves the partial file and returns failure.
- A completed file is renamed only after its size is stable.

These rules prefer retaining media over making the terminal workflow appear
successful.

## Control paths

| Situation | Scribe behavior | User action |
|---|---|---|
| WebSocket is available and idle | Starts through WebSocket and requires advancing output counters | Watch OBS meters and the Scribe timer |
| OBS is already recording | Refuses to interfere and exits with an actionable error | Finish the existing recording manually |
| OBS process exists but WebSocket is closed | Attempts one non-destructive recovery instance if no recording mux is active | Watch for the new OBS instance and confirmation |
| OBS executable is found but WebSocket remains unavailable | Uses OBS's supported start option and requires a fresh growing file | Keep OBS visible; stop manually if Scribe cannot reconnect |
| OBS executable is not found | Waits for a manually started fresh growing file | Open OBS and click Start Recording |
| Capture stops before a Scribe stop request | Preserves the partial media and reports failure | Inspect the file and OBS log before retrying |
| File is still growing after stop | Leaves it at the OBS path and reports failure | Wait for OBS to finalize; do not move the file |

## Platform setup

### Windows

Use a current OBS Studio install and its built-in WebSocket server. The default
endpoint is `localhost:4455`. Confirm the expected profile, scene collection,
recording path, and audio devices. Quick Record launchers can be installed with:

```bash
scribe shortcut
scribe shortcut --desktop
```

### macOS

Grant OBS Screen Recording and Microphone permissions. Fully quit and reopen OBS
after changing permissions. Scribe launches the OBS application bundle so its
resources and normal permission identity are preserved.

### Linux

Ensure `obs` is on `PATH` and run it in the active graphical session. Confirm that
the desktop audio stack, portal or display permissions, and selected OBS sources
work in a direct OBS test before using Scribe.

On Omarchy, OBS is preinstalled at `/usr/bin/obs`. Add PipeWire sources in OBS
before the first `scribe rec`: an audio input for the microphone, an audio
output monitor for system sound, and a screen or window capture. The window
picker comes from `xdg-desktop-portal-hyprland`. Enable the built-in WebSocket
server and use the same password Scribe has. Make one short recording inside
OBS and confirm the file contains the microphone and the system audio you
expect.

`scribe rec` is separate from Omarchy's Alt+Print Screen capture. Do not run
both at once. Scribe will not stop or adopt a capture it did not start.

## If confirmation fails

Do not immediately kill OBS or delete its configuration. First inspect the OBS
window for an active recording, encoder errors, source meters, and the configured
recording path. If any capture is active, protect it and stop it only when the
meeting is finished.

If no capture is active:

1. Run `scribe rec --check` and read the exact endpoint or process warning.
2. Confirm the WebSocket password in Scribe matches OBS.
3. Make a short direct OBS recording and verify its output file.
4. Close OBS normally, reopen it, and rerun the check.
5. Run `scribe doctor` and inspect the latest Scribe log.

See [Troubleshooting](TROUBLESHOOTING.md#obs-recording-fails) for symptom-specific
recovery and [Responsible Use](RESPONSIBLE_USE.md) for consent, privacy, and data
handling requirements.

## Reliability boundary

Scribe can validate control responses, output progress, file growth, finalization,
and session evidence. It cannot guarantee external hardware, OBS scenes and
plugins, operating-system audio routing, available disk space, power, or device
permissions. For a meeting that cannot be repeated, use a short preflight capture
and an independent authorized backup recording when policy permits it.
