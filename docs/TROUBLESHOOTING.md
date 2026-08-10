# Troubleshooting Guide

**Last Updated:** 2026-07-28 (hardware-aware PyTorch repair and recording launcher recovery)

## Quick Diagnostics

Always start with system diagnostics:
```bash
scribe doctor
```

This runs all comprehensive checks and provides actionable recommendations.

## Common Issues

### GPU Not Detected

**Symptoms:**
- "No GPU detected" message
- Slow transcription (Scribe transcribes on CPU - still local and $0, just slower)

> Note: with $0-first defaults, no GPU does **not** mean paid API. `--method auto`
> transcribes locally on CPU; the paid OpenAI API is only used if you pass
> `--method openai` explicitly. Run `scribe doctor` for a $0-readiness report.

**Diagnosis:**
```bash
python -c "import torch; print(torch.cuda.is_available())"
python -c "import torch; print(torch.cuda.get_device_name(0))"
```

**Solutions:**

1. **Install the hardware-compatible PyTorch build:**
```bash
uv pip install torch torchaudio --torch-backend cu130 --reinstall-package torch --reinstall-package torchaudio
python -c "import torch, torchaudio; print(torch.cuda.is_available(), torch.version.cuda, torchaudio.__version__)"
```

For a global Scribe tool installed from a clone, rebuild its isolated environment
with `uv tool install --force --editable . --python 3.12 --torch-backend cu130`.
For pip-only environments, use the current command from the official PyTorch
installation selector rather than a hard-coded CUDA wheel index.

2. **Check CUDA installation:**
```bash
nvcc --version
nvidia-smi
```

3. **Update NVIDIA drivers:**
- `scribe doctor` now includes a CUDA driver age check. If it flags your driver as "Very old" (e.g. < 525), modern PyTorch may degrade or fail to detect your GPU.
- Download latest drivers from the NVIDIA website.
- Restart after installation.

4. **Verify CUDA version compatibility:**
- Let uv select a build compatible with the installed driver.
- Check PyTorch CUDA version: `python -c "import torch; print(torch.version.cuda)"`


### FFmpeg Not Found

**Symptoms:**
- "ffmpeg not found" error
- Cannot convert audio/video files
- ProcessError during conversion

**Diagnosis:**
```bash
ffmpeg -version
ffprobe -version
```

**Solutions:**

**Windows:**
```bash
winget install FFmpeg.FFmpeg
# Or download from https://ffmpeg.org/download.html
```

**macOS:**
```bash
brew install ffmpeg
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install ffmpeg
```

**Verify installation:**
```bash
which ffmpeg
which ffprobe
```

### URL Download Issues (yt-dlp)

**Symptoms:**
- `scribe url` fails with DownloadError
- "yt-dlp not installed" message
- HTTP 403 Forbidden errors
- Download times out or produces empty file

**Diagnosis:**
```bash
scribe doctor          # Check yt-dlp availability
yt-dlp --version       # Verify installation
```

**Solutions:**

1. **Install yt-dlp:**
```bash
pip install yt-dlp
```

2. **Update yt-dlp (sites frequently change their anti-bot protections):**
```bash
pip install --upgrade yt-dlp
```

3. **HTTP 403 Forbidden:**
   - Most common cause: outdated yt-dlp - update first (step 2)
   - Try browser cookies to authenticate: `scribe url <link> --cookies edge`
   - Supported browsers: `edge`, `chrome`, `firefox`, `safari`, `opera`, `brave`
   - Scribe automatically retries up to 10 times with exponential backoff

4. **Video unavailable or age-restricted:**
   - Check the URL is accessible in a browser
   - Use `--cookies` to authenticate via your logged-in browser session
   - Age-restricted content requires cookies: `scribe url <link> --cookies chrome`

5. **Download timeout:**
```bash
# Increase timeout (default 600 seconds)
export SCRIBE_DOWNLOAD_TIMEOUT=1200
```

### Poor Transcription Quality

**Symptoms:**
- Inaccurate transcription
- Missing words
- Garbled text

**Diagnosis:**
1. Check audio quality
2. Verify model being used
3. Check for background noise

**Solutions:**

1. **Use highest quality model (default):**
```bash
scribe transcribe audio.mp4 --model large-v3
```

2. **Improve audio quality:**
- Use quality microphone
- Minimize background noise
- Ensure proper microphone placement
- Record in quiet environment

3. **Use custom vocabulary for technical terms:**
```bash
scribe transcribe meeting.mp4 --vocabulary tech-terms.txt
```

4. **Check audio normalization:**
- Scribe automatically normalizes audio
- Verify input audio isn't corrupted
- Check file format is supported

5. **Try different language setting:**
```bash
scribe transcribe audio.mp4 --language es  # Spanish
```

### API Errors

**Symptoms:**
- "API key not found"
- "Rate limit exceeded"
- "Invalid API key"
- 401, 403, 429 errors

**Diagnosis:**
```bash
scribe info  # Check API key configuration
scribe health --provider openai  # Test connectivity
```

**Solutions:**

1. **Verify API key:**
```bash
# Check .env file
cat .env | grep API_KEY

# Or check environment
echo $OPENAI_API_KEY
```

2. **Set API key:**
```bash
export OPENAI_API_KEY=sk-proj-...
export XAI_API_KEY=xai-...
```

3. **Check API quota:**
- Log into provider dashboard
- Verify billing is active
- Check usage limits

4. **Rate limiting:**
- Wait and retry
- Use different provider
- Implement exponential backoff (automatic in Scribe)

5. **Network issues:**
```bash
# Test connectivity
curl https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY"
```

### Out of Memory (OOM) Errors

**Symptoms:**
- "CUDA out of memory"
- Process crashes during transcription
- GPU memory errors

**Diagnosis:**
```bash
nvidia-smi  # Check GPU memory usage
```

**Solutions:**

1. **Use smaller model:**
```bash
scribe transcribe audio.mp4 --model large-v2  # Faster, less memory
scribe transcribe audio.mp4 --model medium    # Even faster
```

2. **Close other GPU applications:**
- Close games, video editors, etc.
- Check `nvidia-smi` for other processes

3. **Reduce beam size (advanced):**
- Edit GPU config in code
- Lower beam size = less memory, slightly lower quality

4. **Fall back to API:**
```bash
scribe transcribe audio.mp4 --method openai
```

5. **Upgrade GPU:**
- RTX 4090 (24GB) recommended for large-v3
- RTX 4080 (16GB) works with large-v3
- RTX 3090 (24GB) works but slower

### File Format Errors

**Symptoms:**
- "Unsupported audio format"
- "Cannot identify image file"
- AudioFormatError

**Diagnosis:**
```bash
ffprobe input_file.ext
```

**Solutions:**

1. **Supported formats:**
- Audio: WAV, MP3, M4A, FLAC, OGG
- Video: MP4, MKV, WEBM

2. **Convert to supported format:**
```bash
ffmpeg -i input.avi -c:a libmp3lame output.mp3
```

3. **Check file corruption:**
```bash
ffmpeg -v error -i input.mp4 -f null -
```

4. **Verify file size:**
- Files must be > 1KB
- Check disk space

### Garbled Text Output (Windows)

**Symptoms:**
- Weird characters in console (ô instead of quotes)
- Emoji rendering issues
- Unicode errors

**Solutions:**

Scribe treats terminal and progress output as presentation-only. A closed pipe or
unsupported output encoding cannot rewrite a saved result. When an active log
exists, it retains both the original error and the terminal-delivery error in
UTF-8. Scribe then exits 1 and attempts one plain stderr notice. Configure UTF-8
to retain the complete Rich display:

1. **Set UTF-8 encoding (temporary):**
```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

2. **Set UTF-8 encoding (permanent):**
```powershell
# Add to PowerShell profile
notepad $PROFILE

# Add this line:
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

3. **Use Windows Terminal:**
- Better Unicode support
- Download from Microsoft Store

### OBS Recording Issues

**Symptoms:**
- "Could not connect to OBS WebSocket"
- "OBS WebSocket error"
- Recording doesn't start
- OBS asks about safe mode on launch

**Diagnosis:**
```bash
scribe info  # Check OBS configuration
```

**How Scribe manages OBS (automatic):**

Scribe now handles most OBS issues automatically:
- Kills stale OBS processes before launching fresh
- Cleans crash sentinel files that trigger the safe-mode dialog
- Launches with `--disable-shutdown-check` to bypass crash recovery
- Stops leftover recordings before starting a new one
- Reconnects WebSocket if connection drops mid-recording
- Retries the full kill→launch cycle if the first attempt fails

**Solutions if automatic recovery fails:**

1. **Enable OBS WebSocket:**
- Open OBS Studio
- Tools → WebSocket Server Settings
- Enable WebSocket server
- Set password

2. **Configure Scribe:**
```bash
# In .env file
SCRIBE_OBS_HOST=localhost
SCRIBE_OBS_PORT=4455
SCRIBE_OBS_PASSWORD=your_password
```

3. **Authentication mismatch:**
- Scribe will warn: "OBS authentication failed - check SCRIBE_OBS_PASSWORD"
- Ensure the password in `.env` matches OBS WebSocket Server Settings
- Leave `SCRIBE_OBS_PASSWORD` empty if OBS has no password set

4. **OBS keeps asking about safe mode:**
- Scribe handles this automatically, but if it persists:
- Delete `%APPDATA%\obs-studio\global.ini` (Windows) or `~/.config/obs-studio/global.ini` (Linux)
- Or launch OBS once manually, dismiss the dialog, and close cleanly

5. **"No recording file detected":**
- Check OBS Settings → Output → Recording Path
- Scribe will tell you where it searched and for how long
- Ensure the recording path is writable

6. **Verify WebSocket version:**
- Scribe requires WebSocket v5
- Update OBS if needed

7. **Firewall issues:**
- Allow OBS through firewall
- Check port 4455 is not blocked

### Quick Record / Desktop / Taskbar Shortcut Issues

**Symptoms:**
- Launcher "crashes" or window disappears immediately
- Taskbar pinned icon shows generic/backslash (\) instead of Scribe icon
- No output or "file not found" when double-clicking the desktop/taskbar launcher
- Wrong `scribe` binary used (e.g. dev venv instead of stable global)

**Diagnosis:**
- The launcher is a thin native shortcut + adaptive wrapper (`.cmd` on Windows).
- It prefers a stable `scribe` on your PATH (e.g. from `uv tool install`).
- Windows taskbar pinning is picky about icons when the target is a script/cmd.

**Solutions:**

1. **Use a stable global `scribe` before creating the launcher** (strongly recommended):
   ```powershell
   uv tool install --python 3.12 git+https://github.com/blisspixel/scribe.git
   uv tool update-shell   # open a new shell
   scribe shortcut --desktop
   ```
   Then drag the new Desktop `.lnk` to the taskbar.

2. **If taskbar icon is wrong after pinning**:
   - Right-click the pinned item → Properties → Change Icon
   - Browse to `%USERPROFILE%\.scribe\scribe.ico` and select it.
   - Unpin + repin the fresh desktop `.lnk` if needed.
   - (Icon cache sometimes needs Explorer restart or logout.)

3. **Remake cleanly**:
   ```powershell
   scribe shortcut --remove
   scribe shortcut --desktop
   ```
   An existing `Scribe Quick Record` taskbar pin is refreshed too. If Explorer still
   displays a cached old icon or target, unpin it and drag the fresh Desktop `.lnk` back.

4. **The generated files (for debugging)**:
   - `~/.scribe/Scribe Quick Record.cmd` (adaptive wrapper with pauses + fallback)
   - Desktop / Start Menu `.lnk` files (icon is set on the `.lnk`)
   - The `.lnk` targets `cmd.exe`, which invokes the stable wrapper instead of embedding a Python, temporary, or virtual-environment `scribe.EXE` path.

5. **Console stays open**: The launcher sets `SCRIBE_FROM_SHORTCUT=1` and the code ensures pauses + "Press Enter" on Windows for dedicated launches.

6. **Wrong binary used**:
   - Run `where scribe` (or `Get-Command scribe`) to see what your PATH resolves to.
   - Prefer a global tool install over running from a project `.venv`.

The launcher is deliberately adaptive so it survives upgrades when you have a stable `scribe` on PATH.

### Slow Transcription

**Symptoms:**
- Transcription slower than expected
- Lower than advertised speed ratios

**Diagnosis:**
1. Check GPU utilization: `nvidia-smi`
2. Check CPU usage
3. Verify model being used

**Solutions:**

1. **Verify GPU is being used:**
```bash
scribe transcribe audio.mp4 --method local
```

2. **Check GPU utilization:**
```bash
# Should show high GPU usage during transcription
watch -n 1 nvidia-smi
```

3. **Close background applications:**
- Free up GPU memory
- Free up CPU resources

4. **Use faster model:**
```bash
scribe transcribe audio.mp4 --model large-v2  # Faster
scribe transcribe audio.mp4 --model medium    # Even faster
```

5. **Check thermal throttling:**
- Monitor GPU temperature
- Ensure adequate cooling
- Clean dust from GPU

6. **Audio preprocessing time:**
- Audio normalization takes ~10% of duration
- This is normal and ensures quality

### Meme Generation Failures

**Symptoms:**
- "Failed to generate meme"
- "Safety blocked"
- Low quality scores

**Diagnosis:**
```bash
scribe meme transcript.md --show-reasoning
```

**Solutions:**

1. **Safety filter blocking:**
- Content may be flagged as inappropriate
- Try different transcript section
- Adjust spice level: `--spice 3`

2. **Low quality scores:**
- Increase QA attempts: `--qa-attempts 5`
- Lower threshold: `--qa-threshold 7.0`
- Try different provider

3. **Provider issues:**
```bash
# Try different provider
scribe meme transcript.docx --provider openai
scribe meme transcript.md --provider xai
```

4. **Image generation errors:**
- Check API key for image provider
- Verify provider supports images
- Check API quota

### Test Failures

**Symptoms:**
- Tests fail when running pytest
- Import errors in tests
- Module not found errors

**Solutions:**

1. **Reconcile the locked development environment:**
```bash
uv sync --locked --group dev
```

2. **Clear Python cache:**
```bash
find . -type d -name __pycache__ -exec rm -rf {} +
find . -type f -name "*.pyc" -delete
```

3. **Run a specific test:**
```bash
uv run pytest tests/unit/test_file.py::test_name -vv
```

4. **Check Python version:**
```bash
uv run python --version  # Must be 3.12 or 3.13
```

## Error Codes

Scribe uses specific exit codes:

- **0:** All requested work completed, including confirmed instrumental results
- **1:** Failure or partial completion, including missing inputs or requested artifacts
- **2:** Invalid arguments
- **3:** External tool failure (FFmpeg, OBS, CUDA)
- **4:** API error

For `scribe batch` and `scribe music`, `--continue-on-error` means later inputs
are still attempted. It does not turn a partial run into success. The final summary
lists every partial or failed item and the command exits 1. Use `--stop-on-error`
to stop after the first processing failure. A confirmed instrumental track is a
successful terminal outcome, so it does not stop later tracks. If every default
batch input is missing, the command still prints one ASCII-safe summary with zero
successes and every failed item before exiting 1. Stop mode exits after the first
literal missing-path warning without an aggregate summary.

Every started file, URL, batch item, recording, and music track writes a unique
`*_session_summary.json` record. Its `outcome` is `success`, `partial`, `failed`,
or `instrumental`. A recording can therefore retain usable audio or a transcript
while reporting a failed requested extra as `partial`; music can retain usable
lyrics when only some vocal segments fail. Incomplete commands print the exact
summary path. If summary persistence fails, Scribe reports that evidence gap
separately without replacing the original error.

## Logging

### Enable Debug Logging
```bash
export SCRIBE_LOG_LEVEL=DEBUG
scribe transcribe audio.mp4
```

### Check Log Files

Use the exact `Log file:` path printed with a command error. Scribe writes
timestamped `scribe_<session>_<timestamp>.log` files in the configured log
folder. If the command did not print a path, run `scribe support-bundle` to
collect opaque recent-log metadata, then inspect the configured log folder
locally. Bundle JSON never includes log filenames or contents.

### Log Levels
- **DEBUG:** Detailed information for debugging
- **INFO:** General information (default)
- **WARNING:** Warning messages
- **ERROR:** Error messages only

## Performance Issues

### Disk Space
```bash
# Check available space
df -h

# Clean old outputs
rm -rf output/old_files/
```

### Memory Usage
```bash
# Monitor memory
top
htop

# Check Scribe memory usage
ps aux | grep scribe
```

### Network Issues
```bash
# Test API connectivity
curl -I https://api.openai.com
ping api.openai.com

# Check DNS
nslookup api.openai.com
```

## Getting Help

### Before Asking for Help

1. Run diagnostics:
```bash
scribe doctor
```

2. Check the exact `Log file:` path printed with the command error. Scribe uses
   timestamped `scribe_<session>_<timestamp>.log` files and does not create a
   `logs/latest.log` alias. If no log path was printed, run:
```bash
scribe support-bundle
```
   The bundle includes opaque recent-log metadata, not log filenames or contents.
   Each run reserves a unique output file, including concurrent or same-second
   runs. Review the JSON before sharing it. If bundle creation itself fails,
   inspect any log path that was actually printed and verify the output directory
   is writable before retrying.

3. Test with simple file:
```bash
scribe transcribe short_test.mp3
```

4. Verify installation:
```bash
scribe version
scribe info
```

### When Reporting Issues

Include:
1. Scribe version: `scribe version`
2. System info: `scribe info`
3. Diagnostic output: `scribe doctor`
4. Complete error message and the printed session-summary path
5. Steps to reproduce
6. Log file (if applicable, shared separately because support bundles exclude contents)

### Resources

- GitHub Issues: https://github.com/blisspixel/scribe/issues
- Documentation: `docs/` directory
- System diagnostics: `scribe doctor`
- Provider health: `scribe health`

## Advanced Troubleshooting

### Python Environment Issues
```bash
# Check Python version
python --version

# Check installed packages
pip list | grep scribe
pip list | grep torch

# Verify virtual environment
which python
```

### CUDA Issues
```bash
# Check CUDA version
nvcc --version

# Check CUDA libraries
ldconfig -p | grep cuda  # Linux
```

### Provider-Specific Issues

**OpenAI:**
- Check API status: https://status.openai.com
- Verify model availability
- Check rate limits

**XAI/Grok:**
- Verify API key format: `xai-...`
- Check XAI dashboard for quota
- Ensure model access

**Anthropic:**
- Verify API key format: `sk-ant-...`
- Check Claude model availability
- Note: No image generation support

**Gemini:**
- Verify API key
- Check Google AI Studio for quota
- Ensure model access

### Clean Reinstall
```bash
# Uninstall
pip uninstall scribe

# Remove cache
rm -rf ~/.cache/scribe
rm -rf src/scribe/__pycache__

# Reinstall
pip install -e .
```

## Still Having Issues?

1. Search existing GitHub issues
2. Check documentation thoroughly
3. Run full diagnostics
4. Create detailed bug report with:
   - System information
   - Error messages
   - Steps to reproduce
   - Log files
