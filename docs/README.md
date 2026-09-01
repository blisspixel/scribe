# Scribe Documentation

Documentation for Scribe, a local-first transcription and recording CLI.

## Core Documentation

### Getting Started
- [Main README](../README.md) - Concise overview and quick start
- [Recording Guide](RECORDING.md) - OBS setup, startup proof, defensive control, safe stop, and recovery
- [CLI Guide](CLI.md) - User workflows, flags, exit behavior, and failure evidence
- [Resident Voice Guide](VOICE.md) - Tray setup, ownership, platforms, diagnostics, and recovery
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Common issues and solutions
- [RESPONSIBLE_USE.md](RESPONSIBLE_USE.md) - Recording consent, sensitive data, cloud sharing, accuracy, and legal limits
- [Support](../SUPPORT.md) - Safe diagnostics and issue-reporting guidance
- [Code of Conduct](../CODE_OF_CONDUCT.md) - Community behavior and enforcement

### Architecture & Design
- [ARCHITECTURE.md](ARCHITECTURE.md) - System architecture and design patterns
- [AGENTIC_BALANCE.md](AGENTIC_BALANCE.md) - Where Scribe uses deterministic rules versus model judgment
- [Music Mode Architecture](features/MUSIC_MODE_ARCHITECTURE.md) - Segment-based transcription deep dive
- [Resident Voice Tray Utility Plan](features/VOICE_TRAY_UTILITY_PLAN.md) - Current Windows implementation, native prototype boundary, and remaining validation
- [Polyglot Architecture Plan](features/POLYGLOT_ARCHITECTURE_PLAN.md) - Current Go and Rust extraction status and distribution gaps

### Development
- [DEVELOPMENT.md](DEVELOPMENT.md) - Development setup and workflows
- [Contributing](../CONTRIBUTING.md) - Contribution scope, data hygiene, and review expectations
- [API_REFERENCE.md](API_REFERENCE.md) - Complete API documentation
- [EVALUATION.md](EVALUATION.md) - Reproducible WER and real-time-factor evaluation

### Operations
- [DEPLOYMENT.md](DEPLOYMENT.md) - Local install, self-managed operation, and backup guidance
- [PERFORMANCE_TUNING.md](PERFORMANCE_TUNING.md) - Optimization and benchmarking
- [SBOM Compliance](features/SBOM_COMPLIANCE.md) - Generate a local CycloneDX software bill of materials
- [Security Policy](../SECURITY.md) - Reporting guidance and documented trust boundaries

### Project Status
- [ROADMAP](../ROADMAP.md) - Current priorities and scope boundaries
- [CHANGELOG](../CHANGELOG.md) - Shipped changes and development history

## Additional Resources

- **features/** - Feature-specific documentation
- **adr/** - Accepted architecture and policy decisions

## Documentation Philosophy

Keep it clean, professional, and essential:
- Only document what's actively referenced
- Archive historical/session docs
- Focus on architecture and usage
- Keep it up to date
