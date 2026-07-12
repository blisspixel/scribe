# SBOM Compliance

Scribe users who require compliance artifacts can generate a Software Bill of Materials (SBOM) using \pip-audit\, which is already integrated into the Scribe development and CI pipeline.

## Generating an SBOM

To generate an SBOM in CycloneDX format, run the following command from the Scribe project root:

\\ash
uv run pip-audit --format cyclonedx-json -o scribe-sbom.json
\
This command will output a file named \scribe-sbom.json\ containing the complete list of dependencies and their versions, structured according to the CycloneDX standard.

## Security Scanning

Scribe uses \pip-audit\ internally to scan for known vulnerabilities. This check is run automatically in CI and can be triggered locally via:

\\ash
scribe doctor
\
Any detected vulnerabilities will be highlighted in the doctor report.
