# ADR-012: Structured Logging Evaluation

## Status
Accepted

## Context
Step 4 of the Engineering Excellence roadmap includes the following item: "Evaluate minimal structured logging additions only behind an opt-in flag that does not change the default excellent Rich console + detailed file log experience."

Scribe's current logging strategy uses standard Python `logging` with Rich handlers for CLI output and file handlers for debug logs. While structured logging (e.g. JSON logs, OpenTelemetry) is standard for cloud-native services, Scribe is a local-first desktop CLI tool. 

## Decision
We have decided **against** implementing structured JSON logging or an OpenTelemetry stack for the following reasons:
1. **Target Audience**: Scribe users are primarily running a local desktop application, where human-readable file logs (e.g., `scribe.log`) are easier to attach to bug reports than JSON lines.
2. **Maintenance Overhead**: Adding a secondary logging system (like `structlog`) behind an opt-in flag adds conditional branching to every log call or requires complex logger wrappers, violating our goal of keeping the codebase maintainable.
3. **No Central Aggregation**: As a local tool with no telemetry by design, there is no centralized logging server (like Datadog or ELK) that would consume the JSON structured logs anyway.

## Consequences
- Scribe will maintain its excellent `Rich` console formatting for end users and standard text-based file logging for developers.
- The roadmap item is considered completed by this evaluation.
