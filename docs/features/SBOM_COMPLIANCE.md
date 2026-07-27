# SBOM Compliance

Scribe exports its locked runtime dependency graph as a CycloneDX Software Bill
of Materials (SBOM). CI generates and retains this artifact on every run.

## Generate a CycloneDX SBOM

From the project root:

```bash
mkdir -p .agent/build
uv export --locked --package scribe --no-dev --no-default-groups \
  --no-emit-workspace --format cyclonedx1.5 \
  --output-file .agent/build/scribe-sbom.cdx.json
```

PowerShell users can create the directory with
`New-Item -ItemType Directory -Force .agent/build`. The export comes directly
from `uv.lock`, so it does not depend on whichever packages happen to be
installed in the active environment. Review the file before sharing it because
dependency details can be operationally sensitive.

The required `security` CI job uploads the same file as the `scribe-sbom`
artifact. SBOM generation inventories dependencies; the separate blocking
audit evaluates known vulnerabilities under the reviewed exception policy.

## Scan for Known Vulnerabilities

Run the local diagnostic surface, which applies the documented ADR-004 policy:

```bash
uv run scribe doctor
```

The exact blocking release command, including every reviewed Torch exception,
is documented in `docs/DEVELOPMENT.md` and enforced by
`.github/workflows/ci.yml`. CI remains the release gate.
