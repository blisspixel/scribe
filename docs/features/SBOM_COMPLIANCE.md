# SBOM Compliance

Scribe can generate a local Software Bill of Materials (SBOM) with `pip-audit`,
which is part of the locked development environment.

## Generate a CycloneDX SBOM

From the project root:

```bash
uv sync --locked --group dev
uv run python -c "from pathlib import Path; Path('.agent/build').mkdir(parents=True, exist_ok=True)"
uv run pip-audit --format cyclonedx-json --output .agent/build/scribe-sbom.cdx.json \
  --ignore-vuln PYSEC-2025-203 \
  --ignore-vuln PYSEC-2025-204 \
  --ignore-vuln PYSEC-2025-206 \
  --ignore-vuln PYSEC-2026-139 \
  --ignore-vuln PYSEC-2026-2286 \
  --ignore-vuln CVE-2025-2999 \
  --ignore-vuln CVE-2025-3000 \
  --ignore-vuln CVE-2025-3001
```

The command writes the complete resolved environment inventory to an ignored
build directory. Review the file before sharing it because dependency and local
environment details can be operationally sensitive.

## Scan for Known Vulnerabilities

Run the local diagnostic surface, which applies the documented ADR-004 policy:

```bash
uv run scribe doctor
```

The exact blocking release command, including every reviewed Torch exception,
is documented in `docs/DEVELOPMENT.md` and enforced by
`.github/workflows/ci.yml`. CI remains the release gate.
