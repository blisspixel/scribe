# Security Policy

## Supported versions

Security fixes are applied to `main` and the newest published release. Older
minor releases receive fixes only when the change can be backported safely.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting flow under the repository Security
tab when it is available. Do not include API keys, transcripts, recordings, or
other sensitive user data in a public issue. If private reporting is unavailable,
open a minimal public issue asking for a private contact channel without
disclosing exploit details.

Include the affected version or commit, operating system, impact, reproduction
steps, and whether the issue requires a malicious local file, local process,
network peer, or cloud provider response.

## Trust boundaries

Scribe is local-first, not isolation software. Its important boundaries are:

- Local transcription keeps audio and transcript content on the machine.
- Explicit cloud transcription, notes, humor, and image features send selected
  content to the configured provider.
- API keys are secrets and must never be included in logs, support bundles, test
  fixtures, or bug reports.
- OBS, FFmpeg, model files, optional native binaries, and user-selected media are
  external inputs. Obtain executables and models from trusted sources.
- The native tray prototype is an explicit developer override until signed and
  attested release artifacts exist.

The blocking dependency audit and its reviewed Torch exceptions are documented
in [ADR-004](docs/adr/ADR-004-dependency-vulnerability-audit-policy.md). A passing
audit does not make untrusted model checkpoints or executables safe.

## Disclosure expectations

Please allow reasonable time to reproduce, patch, and release a fix before public
disclosure. Reports made in good faith for defensive purposes are welcome.
