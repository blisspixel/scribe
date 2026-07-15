# ADR-011: Responsible-use guardrails (recording consent and disclaimers)

## Status

Accepted (2026-06).

## Context

Scribe records conversations and calls and can send audio or transcripts to cloud
providers. Recording-consent law varies by jurisdiction and some places require
all-party consent; regulated data (HIPAA/PHI, payment, classified) is out of scope;
and cloud features transmit user content to third parties. The project needs clear,
honest, non-alarmist guardrails that inform users and protect the project, without
pretending to give legal advice or blocking legitimate use.

## Decision

Add lightweight responsible-use guardrails:

- **One-time recording-consent notice.** The first interactive run of `record`/`rec`
  shows a short notice and asks the user to confirm they will obtain any legally
  required consent. The acknowledgement is stored once at
  `~/.scribe/recording_consent_ack`, so it is asked only once. The gate is
  deliberately non-blocking where prompting is impossible: a non-interactive run
  (no TTY: scheduled jobs, pipes, CI) prints a one-line reminder and proceeds, and
  `SCRIBE_ASSUME_CONSENT=1` silences even that. Declining in an interactive run
  cancels the recording.
- **Disclaimers.** A `docs/RESPONSIBLE_USE.md` guide and a README "Responsible Use and Legal"
  section cover recording consent, regulated/sensitive data, cloud data sharing,
  output accuracy, the no-warranty disclaimer, the unresolved license state, and
  user responsibility.

Every notice states plainly that it is not legal advice.

## Consequences

- Users are informed of the consent and data-sharing implications at the point of
  use, once, without friction on every run.
- Automation is not broken: non-interactive recording proceeds with a one-line
  reminder rather than hanging on a prompt.
- This is a guardrail, not a compliance feature. Scribe does not and cannot verify
  consent or jurisdiction; responsibility remains with the user, as stated. The
  consent-state examples are illustrative and explicitly not represented as a
  complete or current list. A licensed attorney should review the language before
  any commercial reliance.
