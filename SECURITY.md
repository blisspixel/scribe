# Security Policy

## Supported versions

Security fixes are applied to `main` and the latest 2.11.x GitHub release. Earlier
release lines are not supported.

## Reporting a vulnerability

Report vulnerabilities through GitHub's private vulnerability reporting flow,
under this repository's Security tab ("Report a vulnerability"). Do not open a
public issue for a suspected vulnerability, and do not include API keys,
transcripts, recordings, or other sensitive user data in a report. If private
reporting is unavailable to you, open a minimal issue asking for a private
channel without disclosing exploit details.

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

The zero-exception blocking dependency audit and its secure ML compatibility
constraint are documented in
[ADR-004](docs/adr/ADR-004-dependency-vulnerability-audit-policy.md). A passing
audit does not make untrusted model checkpoints or executables safe.

## Dependency maintenance

GitHub dependency alerts are enabled. Automated dependency and security-fix pull
requests are intentionally disabled under the current direct-maintenance policy.
`.github/dependabot.yml` retains the uv, pre-commit, GitHub Actions, Go, and Rust
schedules so update pull requests can be enabled deliberately if that policy
changes. Maintainers currently reproduce applicable updates directly on `main`,
refresh the authoritative lockfiles, and run every required CI gate.

Security updates take priority over the weekly cadence. A compatibility pin must
name its reason, validation gap, and review trigger in an ADR or adjacent source
comment. Silently disabling an alert, audit, or required gate is not an accepted
remediation.

## Disclosure expectations

Please allow reasonable time to reproduce, patch, and release a fix before public
disclosure. Reports made in good faith for defensive purposes are welcome.
