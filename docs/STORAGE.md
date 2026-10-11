# User files and Linux storage paths

Scribe keeps selected recording and transcript output separate from its own
configuration, vocabulary, state, and live voice controls. CLI flags override
`SCRIBE_*` environment variables and `.env`, which override the user config file.
An explicit output or log folder always wins over the defaults below.

On Linux, new files use the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/latest/):

| Files | Linux location | Default when the variable is empty, unset, or relative |
|---|---|---|
| Configuration | `$XDG_CONFIG_HOME/scribe/config.toml` | `~/.config/scribe/config.toml` |
| User vocabulary | `$XDG_DATA_HOME/scribe/vocab/` | `~/.local/share/scribe/vocab/` |
| Optional Kokoro voice assets and Quick Record wrapper | `$XDG_DATA_HOME/scribe/` | `~/.local/share/scribe/` |
| Performance metrics and voice status | `$XDG_STATE_HOME/scribe/` | `~/.local/state/scribe/` |
| Diagnostic logs | `$XDG_STATE_HOME/scribe/logs/` | `~/.local/state/scribe/logs/` |
| Live voice socket, token, and instance lock | `$XDG_RUNTIME_DIR/scribe/` | Legacy `~/.scribe/`, with one warning when runtime is unset |

Persistent XDG overrides must be absolute paths. Relative values are ignored.
The runtime override is stricter: a nonempty `XDG_RUNTIME_DIR` must be an existing,
user-owned directory with permissions `0700`, without symbolic links in its
path. Scribe creates its private `scribe/` child with `0700` and validates it too.
Unsafe explicit runtime values fail with guidance; Scribe does not silently use
another directory. Control tokens, sockets, and lock files are user-owned and
private. The login session normally provides the runtime directory and removes
it on logout. Do not put this directory in a synced home or a persistent backup.
When no runtime variable is available, the legacy fallback must also be private
and owned by your user.

The default transcript destination is the localized or relocated Videos directory
plus `Transcriptions/`. Scribe reads the standard `XDG_VIDEOS_DIR` entry in
`$XDG_CONFIG_HOME/user-dirs.dirs` (default `~/.config/user-dirs.dirs`) without
executing shell code. It supports the documented quoted `$HOME/Path` and absolute
`/Path` forms, including shell escapes. If no usable entry is present, it uses
`~/Videos/Transcriptions`. See the upstream
[user directory format](https://manpages.ubuntu.com/manpages/noble/man5/user-dirs.dirs.5.html).
A configured `[output].folder`, `SCRIBE_OUTPUT_FOLDER`, or `-o/--output` keeps its
usual precedence.

## Existing Linux installations

No bulk migration runs. If the XDG config file is absent, Scribe continues reading
`~/.scribe/config.toml`. An existing XDG config takes precedence; malformed XDG
config is not replaced by legacy settings. `scribe info` shows which file is in
use and identifies a legacy file. Explicitly saving with `scribe init` writes to
the XDG config directory and preserves unknown legacy TOML tables and fields.
The original legacy file remains untouched. Back it up before manually moving or
removing it. If both files exist, edit the XDG file that `scribe info` reports.

Named vocabulary lookup searches XDG user vocabulary first, then
`~/.scribe/vocab/`, then bundled presets. An explicit vocabulary file path keeps
working. Complete legacy Kokoro assets and the legacy recording-consent
acknowledgement remain readable. Existing metrics, logs, and other legacy files
are left on disk; new state writes use the XDG state directory.

Stop resident voice before upgrading to this layout, then restart it using the
updated Scribe command. The runtime socket and lock locations change together;
an owner running the previous version still uses the previous location.

## Windows, macOS, and removal

Windows and macOS keep `~/.scribe/config.toml`, `~/.scribe/vocab/`, voice assets,
metrics, voice status, and live control locations. Diagnostic logs default to
`~/.scribe/logs/`. The setup wizard keeps its existing macOS `~/Movies/Transcriptions` default
and Windows `~/Videos/Transcriptions` default; existing non-Linux configuration
and settings defaults are unchanged.

Uninstalling the tool or removing Omarchy markers preserves XDG Scribe config,
data and state directories, legacy `~/.scribe`, and all selected output folders.
Back up config, custom vocabulary, and output you want to retain. Remove these
locations manually only after reviewing their contents. Runtime files belong to
the login session; stopping voice closes its control socket.
